"""
Agent 4 — Reviewer (quality gate).

Validates grammar, consistency, formatting structure and professionalism.
* Safe, mechanical problems are auto-fixed and recorded in `corrections_applied`.
* Judgement problems are reported as issues with a severity.
* A fabrication guard removes any skill that is not in the candidate's input.
If the review contains errors, the orchestrator sends the feedback back to
the Resume Writer for one revision cycle.
"""

from app.agents.base import BaseAgent, PipelineContext
from app.agents.text_utils import (
    canonical_skill,
    clean_whitespace,
    find_first_person,
    fix_spelling,
    has_metric,
    starts_with_action_verb,
    to_past_tense,
    word_count,
)
from app.llm.prompts import REVIEWER_SYSTEM
from app.models.schemas import ReviewerLLMOutput, ReviewIssue, ReviewResult

PENALTY = {"error": 15, "warning": 5, "info": 1}
APPROVAL_THRESHOLD = 60


class ReviewerAgent(BaseAgent):
    name = "reviewer"

    async def execute(self, ctx: PipelineContext) -> bool:
        resume, req = ctx.resume, ctx.request
        assert resume is not None, "Reviewer requires a generated resume"
        issues: list[ReviewIssue] = []
        corrections: list[str] = []

        def issue(severity: str, section: str, message: str) -> None:
            issues.append(ReviewIssue(severity=severity, section=section, message=message))

        # 1. Professional summary ------------------------------------------------
        summary, fixes = fix_spelling(clean_whitespace(resume.professional_summary))
        corrections += [f"Summary spelling: {f}" for f in fixes]
        resume.professional_summary = summary
        words = word_count(summary)
        if words < 30:
            issue("warning", "summary", f"Summary is short ({words} words); aim for 40-90 words")
        elif words > 120:
            issue("warning", "summary", f"Summary is long ({words} words); keep it under 90 words")
        if pronouns := find_first_person(summary):
            issue("error", "summary", f"Summary uses first-person pronouns ({', '.join(pronouns)}); use implied first person")

        # 2. Experience bullets ---------------------------------------------------
        seen: set[str] = set()
        formatted = 0
        for entry in resume.experience:
            role = f"{entry.job_title} at {entry.company}"
            kept: list[str] = []
            weak = 0
            for raw in entry.bullets:
                bullet, fixes = fix_spelling(raw)
                corrections += [f"{role} spelling: {f}" for f in fixes]
                bullet = clean_whitespace(bullet).rstrip(".;, ")
                bullet = bullet[:1].upper() + bullet[1:]
                if past := to_past_tense(bullet):
                    corrections.append(f"{role}: tense aligned → '{past.split(' ', 1)[0]}'")
                    bullet = past
                formatted += bullet != raw
                if bullet.lower() in seen:
                    corrections.append(f"{role}: removed duplicate bullet")
                    continue
                seen.add(bullet.lower())
                if not starts_with_action_verb(bullet):
                    weak += 1
                if word_count(bullet) > 40:
                    issue("warning", "experience", f"{role}: bullet exceeds 40 words; tighten it")
                if find_first_person(bullet):
                    issue("warning", "experience", f"{role}: bullet contains first-person language")
                kept.append(bullet)
            entry.bullets = kept
            if not kept:
                issue("warning", "experience", f"{role}: no achievement bullets; add 2-4 accomplishments")
                continue
            if weak:
                issue("warning", "experience", f"{role}: {weak} bullet(s) do not open with a strong action verb")
            if not any(has_metric(b) for b in kept):
                issue("info", "experience", f"{role}: add at least one measurable result")
        if formatted:
            corrections.append(f"Normalised formatting in {formatted} bullet(s) (capitalisation, punctuation, spacing)")

        # 3. Fabrication guard: skills must come from the candidate's own input ---
        allowed = {canonical_skill(s).lower() for s in req.skills}
        allowed |= {canonical_skill(t).lower() for p in req.projects for t in p.technologies}
        for category in list(resume.skills):
            kept_skills = [s for s in resume.skills[category] if canonical_skill(s).lower() in allowed]
            for removed in set(resume.skills[category]) - set(kept_skills):
                corrections.append(f"Removed unverified skill '{removed}' (not in candidate input)")
            if kept_skills:
                resume.skills[category] = kept_skills
            else:
                del resume.skills[category]

        # 4. Structural consistency ----------------------------------------------
        if len(resume.experience) != len(req.experience):
            issue("error", "experience", "Number of roles in resume does not match the candidate's input")
        if not resume.skills:
            issue("error", "skills", "Skills section is empty")
        if not resume.header.linkedin:
            issue("info", "header", "Add a LinkedIn URL to strengthen credibility")
        if not resume.education:
            issue("info", "education", "Education section is empty")

        # 5. Optional LLM proofread for grammar / professionalism -----------------
        llm_out = await self.try_llm(REVIEWER_SYSTEM, {"resume": resume.model_dump(exclude={"header"})}, ReviewerLLMOutput)
        if llm_out:
            issues.extend(llm_out.issues)

        score = max(0, 100 - sum(PENALTY[i.severity] for i in issues))
        ctx.review = ReviewResult(
            approved=not any(i.severity == "error" for i in issues) and score >= APPROVAL_THRESHOLD,
            quality_score=score,
            issues=issues,
            corrections_applied=corrections,
        )
        return llm_out is not None
