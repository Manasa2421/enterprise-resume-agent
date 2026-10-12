"""
Input sanitisation applied to every user-supplied string before it reaches an agent.

Defends against:
  * prompt injection ("ignore previous instructions...") embedded in profile text
  * control characters / zero-width characters used to hide instructions
  * role-tag spoofing (<system>, <assistant>) aimed at the LLM
"""

import re
from typing import Any

_INJECTION_PATTERNS = [
    r"ignore\s+(all\s+|any\s+)?(the\s+)?(previous|prior|above|earlier)\s+(instructions|prompts?|rules)",
    r"disregard\s+(all\s+|the\s+)?(previous|prior|above|system)\s+(instructions|prompts?|rules)",
    r"forget\s+(all\s+|your\s+)?(previous\s+)?instructions",
    r"you\s+are\s+now\s+(a|an|in)\b",
    r"(reveal|print|show|output)\s+(your|the)\s+(system\s+)?prompt",
    r"</?\s*(system|assistant|user|instructions?)\s*>",
    r"\bjailbreak\b",
    r"rate\s+(this|me|the)\s+(candidate|resume)\s+(as\s+)?(100|perfect)",
]
_INJECTION_RE = re.compile("|".join(_INJECTION_PATTERNS), re.IGNORECASE)
# Control chars (except tab/newline) and zero-width / bidi-override characters.
_HIDDEN_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u200b-\u200f\u202a-\u202e\u2060\ufeff]")


def sanitize_text(value: str) -> tuple[str, int]:
    """Return (clean_text, number_of_flags_raised)."""
    flags = 0
    cleaned, hidden = _HIDDEN_CHARS_RE.subn("", value)
    flags += 1 if hidden else 0
    cleaned, injections = _INJECTION_RE.subn("[removed]", cleaned)
    flags += injections
    return cleaned, flags


def sanitize_payload(data: Any) -> tuple[Any, int]:
    """Recursively sanitise every string in a dict/list structure."""
    if isinstance(data, str):
        return sanitize_text(data)
    if isinstance(data, dict):
        total = 0
        result = {}
        for key, value in data.items():
            result[key], flags = sanitize_payload(value)
            total += flags
        return result, total
    if isinstance(data, list):
        total = 0
        items = []
        for value in data:
            clean, flags = sanitize_payload(value)
            items.append(clean)
            total += flags
        return items, total
    return data, 0
