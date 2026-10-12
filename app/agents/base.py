"""
Agent framework.

Each agent:
  * reads from / writes to a shared PipelineContext (blackboard pattern)
  * is timed, logged and counted automatically by BaseAgent.run()
  * may call the LLM via try_llm(), whose output is schema-validated; on any
    failure it returns None and the agent falls back to deterministic logic,
    so an LLM outage degrades quality rather than causing downtime.
"""

import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app.core.exceptions import AgentExecutionError, LLMError
from app.core.metrics import metrics
from app.llm.client import BaseLLMClient
from app.llm.prompts import wrap_candidate_data
from app.models.schemas import (
    AgentTrace,
    ATSAnalysis,
    ProfileAnalysis,
    ResumeContent,
    ResumeRequest,
    ReviewResult,
)

T = TypeVar("T", bound=BaseModel)


@dataclass
class PipelineContext:
    request: ResumeRequest
    request_id: str
    security_flags: int = 0
    profile: ProfileAnalysis | None = None
    ats: ATSAnalysis | None = None
    resume: ResumeContent | None = None
    review: ReviewResult | None = None
    review_feedback: list[str] = field(default_factory=list)
    revision_count: int = 0
    trace: list[AgentTrace] = field(default_factory=list)


class BaseAgent(ABC):
    name = "base_agent"

    def __init__(self, llm: BaseLLMClient) -> None:
        self.llm = llm
        self.logger = logging.getLogger(f"agents.{self.name}")

    async def run(self, ctx: PipelineContext) -> None:
        start = time.perf_counter()
        status, used_llm = "failed", False
        self.logger.info("agent.started", extra={"agent": self.name})
        try:
            used_llm = await self.execute(ctx)
            status = "fallback" if (self.llm.enabled and not used_llm) else "success"
        except Exception as exc:
            self.logger.exception("agent.failed", extra={"agent": self.name})
            raise AgentExecutionError(self.name) from exc
        finally:
            duration = time.perf_counter() - start
            ctx.trace.append(
                AgentTrace(agent=self.name, status=status, duration_ms=round(duration * 1000, 2), used_llm=used_llm)
            )
            metrics.inc("agent_runs_total", {"agent": self.name, "status": status}, help_text="Agent executions")
            metrics.observe("agent_duration_seconds", duration, {"agent": self.name}, "Agent execution time")
            self.logger.info(
                "agent.completed",
                extra={"agent": self.name, "status": status, "used_llm": used_llm, "duration_ms": round(duration * 1000, 2)},
            )

    @abstractmethod
    async def execute(self, ctx: PipelineContext) -> bool:
        """Do the agent's work. Return True if LLM output was used."""

    async def try_llm(self, system: str, payload: dict, schema: type[T]) -> T | None:
        """Call the LLM and validate its output against `schema`. Returns None on any failure."""
        if not self.llm.enabled:
            return None
        user_message = wrap_candidate_data(json.dumps(payload, indent=2, default=str))
        try:
            data = await self.llm.complete_json(system, user_message, agent=self.name)
            return schema.model_validate(data)
        except (LLMError, ValidationError) as exc:
            metrics.inc("llm_fallbacks_total", {"agent": self.name}, help_text="LLM outputs rejected or failed")
            self.logger.warning("agent.llm_fallback", extra={"agent": self.name, "reason": type(exc).__name__})
            return None
