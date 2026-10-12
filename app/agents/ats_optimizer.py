"""
Agent 2 — ATS Optimization.

* Identifies the keywords an ATS will screen for — from the job description if
  supplied, otherwise from the role profile for the candidate's domain.
* Scores the profile with a transparent, weighted formula (see text_utils.score_ats).
* Produces formatting, skill-alignment and role-targeting suggestions.
* Re-scores the final generated resume so the improvement is measurable.
"""

from app.agents.base import BaseAgent, PipelineContext
from app.agents.knowledge import DOMAIN_KEYWORDS, SKILL_CATEGORIES, WEAK_PHRASES
from app.agents.text_utils import (
    extract_keywords,
    has_metric,
    score_ats,
    split_sentences,
    starts_with_action_verb,
    word_count,
)
from app.llm.prompts import ATS_OPTIMIZER_SYSTEM
from app.models.schemas import ATSAnalysis, ATSLLMOutput, ResumeContent, ResumeRequest

GENERAL_KEYWORDS = ["Communication", "Leadership", "Problem Solving", "Stakeholder Management", "Project Management"]
MAX_KEYWORDS = 20


def _vocabulary(req: ResumeRequest) -> list[str]:
    vocab = [k for kws in DOMAIN_KEYWORDS.values() for k in kws]
    vocab += [k for kws in SKILL_CATEGORIES.values() for k in kws]
    return vocab + list(req.skills)


def _profile_corpus(req: ResumeRequest) -> str:
    parts = list(req.skills)
    for e in req.experience:
        parts += [e.job_title, e.description, *e.achievements]
    for p in req.projects:
        parts += [p.name, p.description, p.outcome or "", *p.technologies]
    parts += [c.name for c in req.certifications]
    parts += [f"{ed.degree} {ed.field_of_study or ''}" for ed in req.education]
    return "\n".join(parts)


def _profile_bullets(req: ResumeRequest) -> list[str]:
    return [b for e in req.experience for b in (e.achievements + split_sentences(e.description))]


def _resume_corpus(resume: ResumeContent) -> str:
    parts = [resume.professional_summary]
    parts += [s for skills in resume.skills.values() for s in skills]
    for e in resume.experience:
        parts += [e.job_title, *e.bullets]
    for p in resume.projects:
        parts += [p.name, p.description, *p.technologies]
    parts += resume.certifications
    parts += [f"{ed.degree} {ed.details or ''}" for ed in resume.education]
    return "\n".join(parts)


class ATSOptimizationAgent(BaseAgent):
    name = "ats_optimizer"

    async def execute(self, ctx: PipelineContext) -> bool:
        req, profile = ctx.request, ctx.profile
        assert profile is not None, "Profile analysis must run before ATS optimisation"

        required: list[str] = []
        source = "role_profile"
        if req.target_job_description:
            required = extract_keywords(req.target_job_description, _vocabulary(req))[:MAX_KEYWORDS]
            source = "job_description" if required else source
        if not required:
            required = DOMAIN_KEYWORDS.get(profile.primary_domain, GENERAL_KEYWORDS)[:MAX_KEYWORDS]

        bullets = _profile_bullets(req)
        result = score_ats(
            corpus=_profile_corpus(req),
            bullets=bullets,
            required_keywords=required,
            sections={
                "experience": bool(req.experience),
                "skills": len(req.skills) >= 5,
                "education": bool(req.education),
                "projects_or_certs": bool(req.projects or req.certifications),
                "linkedin": bool(req.contact.linkedin),
            },
        )

        analysis = ATSAnalysis(
            ats_score=result.total,
            score_breakdown=result.breakdown,
            keyword_source=source,
            matched_keywords=result.matched,
            missing_keywords=result.missing,
            formatting_suggestions=self._formatting_suggestions(req, bullets),
            skill_alignment_suggestions=self._skill_suggestions(result.matched, result.missing),
            role_targeting_notes=self._role_notes(req, profile.candidate_level, profile.primary_domain, source),
        )

        llm_out = await self.try_llm(
            ATS_OPTIMIZER_SYSTEM,
            {
                "target_role": req.target_role,
                "computed_ats": analysis.model_dump(include={"ats_score", "matched_keywords", "missing_keywords"}),
                "candidate_level": profile.candidate_level,
                "profile": req.model_dump(exclude={"contact"}),
            },
            ATSLLMOutput,
        )
        if llm_out:
            analysis.skill_alignment_suggestions = llm_out.skill_alignment_suggestions or analysis.skill_alignment_suggestions
            analysis.role_targeting_notes = llm_out.role_targeting_notes or analysis.role_targeting_notes

        ctx.ats = analysis
        return llm_out is not None

    def score_resume(self, ctx: PipelineContext) -> int:
        """Score the *generated* resume against the same keyword set."""
        assert ctx.ats is not None and ctx.resume is not None
        resume = ctx.resume
        bullets = [b for e in resume.experience for b in e.bullets]
        result = score_ats(
            corpus=_resume_corpus(resume),
            bullets=bullets,
            required_keywords=ctx.ats.matched_keywords + ctx.ats.missing_keywords,
            sections={
                "experience": bool(resume.experience),
                "skills": sum(len(v) for v in resume.skills.values()) >= 5,
                "education": bool(resume.education),
                "projects_or_certs": bool(resume.projects or resume.certifications),
                "linkedin": bool(resume.header.linkedin),
            },
        )
        return result.total

    @staticmethod
    def _formatting_suggestions(req: ResumeRequest, bullets: list[str]) -> list[str]:
        suggestions = [
            "Use a single-column layout with standard headings (Summary, Experience, Skills, Education); "
            "ATS parsers often misread tables, text boxes and multi-column designs",
            "Submit as .docx or a text-based PDF (not a scanned image) so the ATS can extract text",
        ]
        if bullets:
            weak_verbs = sum(not starts_with_action_verb(b) for b in bullets)
            if weak_verbs / len(bullets) > 0.3:
                suggestions.append(f"{weak_verbs} of {len(bullets)} bullets do not open with a strong action verb")
            unquantified = sum(not has_metric(b) for b in bullets)
            if unquantified / len(bullets) > 0.5:
                suggestions.append(f"{unquantified} of {len(bullets)} bullets lack measurable results (%, $, time, volume)")
            if any(word_count(b) > 35 for b in bullets):
                suggestions.append("Shorten bullets longer than 35 words to one or two lines")
            if any(b.lower().lstrip(" -•").startswith(tuple(WEAK_PHRASES)) for b in bullets):
                suggestions.append("Replace passive openers such as 'Responsible for' with achievement-led verbs")
        if not req.contact.linkedin:
            suggestions.append("Add a LinkedIn profile URL to the header")
        return suggestions

    @staticmethod
    def _skill_suggestions(matched: list[str], missing: list[str]) -> list[str]:
        suggestions = []
        if matched:
            suggestions.append(f"Lead the skills section with matched keywords: {', '.join(matched[:6])}")
        if missing:
            suggestions.append(
                f"If you have genuine experience with {', '.join(missing[:5])}, add them to Skills and "
                "evidence them in a relevant bullet; do not list skills you cannot discuss in an interview"
            )
        return suggestions

    @staticmethod
    def _role_notes(req: ResumeRequest, level: str, domain: str, source: str) -> list[str]:
        notes = []
        target = req.target_role.lower()
        if not any(target in e.job_title.lower() or e.job_title.lower() in target for e in req.experience):
            notes.append(f"Mirror the exact target title '{req.target_role}' in the professional summary")
        if any(s in target for s in ("senior", "lead", "principal", "head")) and level in ("Entry-Level", "Mid-Level"):
            notes.append(f"Target role appears more senior than the profile ({level}); emphasise ownership and leadership scope")
        if source == "role_profile":
            notes.append(f"No job description supplied, keywords based on the standard {domain} role profile; "
                         "provide the job posting for precise matching")
        return notes
