"""
Deterministic text utilities and ATS scoring.

Design principle: anything that must be *correct* (dates, years of experience,
ATS scores, keyword matching) is computed in code, never delegated to the LLM.
The LLM is only used for language generation, where it adds real value.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from app.agents.knowledge import (
    ACTION_VERBS,
    COMMON_MISSPELLINGS,
    FIRST_PERSON_PRONOUNS,
    SKILL_ALIASES,
    WEAK_PHRASES,
)

_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
_METRIC_RE = re.compile(r"\d+(\.\d+)?\s?%|[$€£₹]\s?\d|\b\d+(\.\d+)?\s?[kKmMbB]\b|\b\d+x\b|\b\d{2,}\b")
_PRONOUN_RE = re.compile(r"\b(" + "|".join(FIRST_PERSON_PRONOUNS) + r")\b", re.IGNORECASE)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?;])\s+|\n+")


# --------------------------------------------------------------------------- #
# Dates & experience
# --------------------------------------------------------------------------- #
def _month_index(ym: str) -> int:
    year, month = ym.split("-")
    return int(year) * 12 + int(month) - 1


def total_experience_years(ranges: list[tuple[str, str | None]], today: date | None = None) -> float:
    """Total years of experience with overlapping roles merged (no double counting)."""
    today = today or date.today()
    now_idx = today.year * 12 + today.month - 1
    intervals = sorted(
        (_month_index(start), (_month_index(end) if end else now_idx) + 1)
        for start, end in ranges
    )
    merged: list[list[int]] = []
    for start, end in intervals:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    months = sum(max(0, end - start) for start, end in merged)
    return round(months / 12, 1)


def format_date_range(start: str, end: str | None) -> str:
    def fmt(ym: str) -> str:
        year, month = ym.split("-")
        return f"{_MONTHS[int(month) - 1]} {year}"

    return f"{fmt(start)} – {fmt(end) if end else 'Present'}"


def candidate_level(years: float, titles: list[str]) -> str:
    seniority_titles = ("senior", "sr.", "lead", "principal", "head", "manager", "director", "architect")
    has_senior_title = any(any(s in t.lower() for s in seniority_titles) for t in titles)
    if years < 2:
        return "Entry-Level"
    if years < 6:
        return "Senior" if (has_senior_title and years >= 4) else "Mid-Level"
    if years < 10:
        return "Senior"
    return "Lead/Principal"


# --------------------------------------------------------------------------- #
# Skills & keywords
# --------------------------------------------------------------------------- #
def canonical_skill(skill: str) -> str:
    cleaned = " ".join(skill.strip().split())
    return SKILL_ALIASES.get(cleaned.lower(), cleaned)


def dedupe_skills(skills: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for skill in skills:
        canon = canonical_skill(skill)
        if canon and canon.lower() not in seen:
            seen.add(canon.lower())
            result.append(canon)
    return result


def _term_pattern(term: str) -> re.Pattern[str]:
    # Custom boundaries so terms like "C++", "CI/CD" and "Next.js" match correctly.
    return re.compile(r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])", re.IGNORECASE)


def _term_variants(term: str) -> list[str]:
    variants = {term}
    for alias, canon in SKILL_ALIASES.items():
        if canon.lower() == term.lower():
            variants.add(alias)
    return list(variants)


def contains_term(text: str, term: str) -> bool:
    return any(_term_pattern(v).search(text) for v in _term_variants(term))


def extract_keywords(text: str, vocabulary: list[str]) -> list[str]:
    """Return vocabulary terms present in text, ordered by first appearance."""
    found: list[tuple[int, str]] = []
    for term in dedupe_skills(vocabulary):
        if len(term) < 2:  # single letters like "R" produce too many false positives
            continue
        positions = [m.start() for v in _term_variants(term) for m in _term_pattern(v).finditer(text)]
        if positions:
            found.append((min(positions), term))
    return [term for _, term in sorted(found)]


# --------------------------------------------------------------------------- #
# Bullets & language quality
# --------------------------------------------------------------------------- #
def split_sentences(text: str) -> list[str]:
    return [s.strip(" -•*\t") for s in _SENTENCE_SPLIT_RE.split(text or "") if s.strip(" -•*\t")]


def word_count(text: str) -> int:
    return len(text.split())


def has_metric(text: str) -> bool:
    return bool(_METRIC_RE.search(text))


def starts_with_action_verb(text: str) -> bool:
    first = text.strip().split(" ", 1)[0].lower().strip(",.;:") if text.strip() else ""
    return first in ACTION_VERBS


def find_first_person(text: str) -> list[str]:
    return sorted({m.group(0).lower() for m in _PRONOUN_RE.finditer(text)})


def fix_spelling(text: str) -> tuple[str, list[str]]:
    corrections: list[str] = []

    def _replace(match: re.Match[str]) -> str:
        word = match.group(0)
        fixed = COMMON_MISSPELLINGS[word.lower()]
        corrections.append(f"{word} → {fixed}")
        return fixed.capitalize() if word[0].isupper() else fixed

    pattern = re.compile(r"\b(" + "|".join(COMMON_MISSPELLINGS) + r")\b", re.IGNORECASE)
    return pattern.sub(_replace, text), corrections


def clean_whitespace(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"\s+([,.;:])", r"\1", text)


_IRREGULAR_PAST = {
    "build": "built", "lead": "led", "write": "wrote", "run": "ran", "make": "made",
    "drive": "drove", "teach": "taught", "grow": "grew", "set": "set", "oversee": "oversaw", "do": "did",
}
_NOT_GERUNDS = {"being", "thing", "string", "spring", "during", "morning", "evening", "ceiling"}


def gerund_to_past(word: str) -> str | None:
    """creating → created, building → built. Returns None if not a gerund."""
    lower = word.lower()
    if not lower.endswith("ing") or len(lower) < 5 or lower in _NOT_GERUNDS:
        return None
    stem = lower[:-3]
    for base, past in _IRREGULAR_PAST.items():
        if stem in (base, base.rstrip("e"), base + base[-1]):
            return past
    return stem + "ed"


def normalize_bullet(text: str) -> str:
    """Turn raw user text into a resume-style bullet: action-led, no pronoun, no trailing period."""
    bullet = clean_whitespace(text.strip(" -•*\t"))
    # Drop a leading first-person subject: "I automated..." → "automated..."
    bullet = re.sub(r"^(i|we)\s+", "", bullet, flags=re.IGNORECASE)
    lowered = bullet.lower()
    for weak, strong in sorted(WEAK_PHRASES.items(), key=lambda kv: -len(kv[0])):
        if lowered.startswith(weak + " "):
            rest = bullet[len(weak) + 1:]
            first, _, remainder = rest.partition(" ")
            past = gerund_to_past(first)
            # "responsible for creating X" → "Created X"; otherwise "Managed X"
            bullet = f"{past} {remainder}".strip() if past else f"{strong} {rest}"
            break
    bullet = bullet.rstrip(".;, ")
    return bullet[:1].upper() + bullet[1:] if bullet else bullet


def to_past_tense(bullet: str) -> str | None:
    """'Manage reports' → 'Managed reports' when the opener is a present-tense action verb."""
    first, _, rest = bullet.partition(" ")
    lower = first.lower()
    for candidate in (lower + "d", lower + "ed", lower[:-1] + "ied" if lower.endswith("y") else None):
        if candidate and candidate in ACTION_VERBS and candidate != lower:
            return f"{candidate.capitalize()} {rest}".strip()
    return None


# --------------------------------------------------------------------------- #
# ATS scoring
# --------------------------------------------------------------------------- #
@dataclass
class ATSScore:
    total: int
    breakdown: dict[str, int]
    matched: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)


def score_ats(
    corpus: str,
    bullets: list[str],
    required_keywords: list[str],
    sections: dict[str, bool],
) -> ATSScore:
    """
    Weighted, explainable ATS score (0-100):
      keyword_match       50  — coverage of required keywords
      quantified_impact   20  — share of bullets containing a metric
      action_verbs        15  — share of bullets opening with a strong verb
      section_completeness 15 — presence of standard resume sections
    """
    matched = [k for k in required_keywords if contains_term(corpus, k)]
    missing = [k for k in required_keywords if k not in matched]
    coverage = len(matched) / len(required_keywords) if required_keywords else 1.0

    bullet_count = len(bullets) or 1
    metric_ratio = sum(has_metric(b) for b in bullets) / bullet_count
    verb_ratio = sum(starts_with_action_verb(b) for b in bullets) / bullet_count

    section_weights = {"experience": 4, "skills": 4, "education": 3, "projects_or_certs": 2, "linkedin": 2}
    section_points = sum(w for name, w in section_weights.items() if sections.get(name))

    breakdown = {
        "keyword_match": round(coverage * 50),
        "quantified_impact": round(min(1.0, metric_ratio / 0.6) * 20),  # full marks at 60% quantified
        "action_verbs": round(verb_ratio * 15),
        "section_completeness": section_points,
    }
    return ATSScore(total=min(100, sum(breakdown.values())), breakdown=breakdown, matched=matched, missing=missing)
