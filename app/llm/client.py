"""
Provider-agnostic LLM client.

* `mock`      — no external calls; agents use their deterministic engines.
                Default, so the system runs (and tests pass) with no API key.
* `anthropic` — Anthropic Messages API.
* `openai`    — OpenAI Chat Completions API (JSON mode).

Agents depend only on `BaseLLMClient`, so adding a provider (Azure OpenAI,
Bedrock, a self-hosted model) means adding one class here.
"""

import json
import logging
import re
import time
from abc import ABC, abstractmethod

from app.core.config import Settings
from app.core.exceptions import LLMError
from app.core.metrics import metrics

logger = logging.getLogger("llm.client")

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def extract_json(text: str) -> dict:
    """Parse a JSON object from model output, tolerating code fences or stray prose."""
    cleaned = _FENCE_RE.sub("", text.strip())
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        raise LLMError("No JSON object found in model output")
    try:
        data = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        raise LLMError(f"Invalid JSON from model: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise LLMError("Model output JSON is not an object")
    return data


class BaseLLMClient(ABC):
    provider: str = "base"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.model = settings.llm_model

    @property
    def enabled(self) -> bool:
        return True

    async def complete_json(self, system: str, user: str, agent: str) -> dict:
        start = time.perf_counter()
        outcome = "success"
        try:
            text = await self._complete(system, user)
            return extract_json(text)
        except LLMError:
            outcome = "error"
            raise
        except Exception as exc:  # network errors, provider errors, timeouts
            outcome = "error"
            raise LLMError(f"{type(exc).__name__}: {exc}") from exc
        finally:
            duration = time.perf_counter() - start
            labels = {"provider": self.provider, "agent": agent, "outcome": outcome}
            metrics.inc("llm_requests_total", labels, help_text="LLM API calls")
            metrics.observe("llm_request_duration_seconds", duration, {"provider": self.provider}, "LLM latency")
            logger.info("llm.call", extra={"agent": agent, "outcome": outcome, "duration_ms": round(duration * 1000, 1)})

    @abstractmethod
    async def _complete(self, system: str, user: str) -> str: ...


class MockLLMClient(BaseLLMClient):
    provider = "mock"

    @property
    def enabled(self) -> bool:
        return False

    async def _complete(self, system: str, user: str) -> str:
        raise LLMError("LLM disabled (mock provider)")


class AnthropicLLMClient(BaseLLMClient):
    provider = "anthropic"

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        from anthropic import AsyncAnthropic  # imported lazily: optional dependency

        self._client = AsyncAnthropic(
            api_key=settings.llm_api_key,
            timeout=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,  # SDK retries with exponential backoff
        )

    async def _complete(self, system: str, user: str) -> str:
        response = await self._client.messages.create(
            model=self.model,
            max_tokens=self.settings.llm_max_tokens,
            temperature=self.settings.llm_temperature,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(block.text for block in response.content if block.type == "text")


class OpenAILLMClient(BaseLLMClient):
    provider = "openai"

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        from openai import AsyncOpenAI  # imported lazily: optional dependency

        self._client = AsyncOpenAI(
            api_key=settings.llm_api_key,
            timeout=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
        )

    async def _complete(self, system: str, user: str) -> str:
        response = await self._client.chat.completions.create(
            model=self.model,
            max_tokens=self.settings.llm_max_tokens,
            temperature=self.settings.llm_temperature,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        return response.choices[0].message.content or ""


def build_llm_client(settings: Settings) -> BaseLLMClient:
    clients: dict[str, type[BaseLLMClient]] = {
        "mock": MockLLMClient,
        "anthropic": AnthropicLLMClient,
        "openai": OpenAILLMClient,
    }
    return clients[settings.llm_provider](settings)
