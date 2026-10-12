"""
Agent 1 — Profile Analyzer.

Analyses skills, experience, projects, education and certifications to produce
a structured candidate profile: level, domain, years of experience, strengths
and gaps. Facts are computed deterministically; the LLM (if enabled) only
enriches the qualitative strengths / gaps / highlights.
"""

from app.agents.base import BaseAgent, PipelineContext
from app.agents.knowledge import DOMAIN_KEYWORDS, DOMAIN_TITLE_SIGNALS
from app.agents.text_utils import (
    candidate_level,
    contains_term,
    dedupe_skills,
    fix_spelling,
    has_metric,
    normalize_bullet,
    split_sentences,
    to_past_tense,
    total_experience_years,
)
from app.llm.prompts import PROFILE_ANALYZER_SYSTEM
from app.models.schemas import ProfileAnalysis, ProfileLLMOutput, ResumeRequest

GENERAL_DOMAIN = "General Professional"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def detect_domains(req: ResumeRequest) -> list[tuple[str, int]]:
    """Score each domain using target role (x3), past titles (x2) and skill overlap (x1)."""
    target = req.target_role.lower()
    titles = " ".join(e.job_title for e in req.experience).lower()
    skills_text = " ".join(req.skills)
    scores = []
    for domain, signals in DOMAIN_TITLE_SIGNALS.items():
        score = 3 * sum(s in target for s in signals) + 2 * sum(s in titles for s in signals)
        score += sum(contains_term(skills_text, kw) for kw in DOMAIN_KEYWORDS[domain])
        scores.append((domain, score))
    return sorted(scores, key=lambda x: -x[1])


def find_employment_gaps(req: ResumeRequest, min_gap_months: int = 6) -> list[str]:
    def idx(ym: str) -> int:
        y, m = ym.split("-")
        return int(y) * 12 + int(m)

    roles = sorted(req.experience, key=lambda e: e.start_date)
    gaps = []
    latest_end = None
    for role in roles:
        if latest_end is not None and idx(role.start_date) - latest_end > min_gap_months:
            gaps.append(f"Employment gap of {idx(role.start_date) - latest_end} months before {role.company}")
        end = idx(role.end_date) if role.end_date else 10**6
        latest_end = end if latest_end is None else max(latest_end, end)
    return gaps


class ProfileAnalyzerAgent(BaseAgent):
    name = "profile_analyzer"

    async def execute(self, ctx: PipelineContext) -> bool:
        req = ctx.request
        years = total_experience_years([(e.start_date, e.end_date) for e in req.experience])
        level = candidate_level(years, [e.job_title for e in req.experience])

        domain_scores = detect_domains(req)
        primary = domain_scores[0][0] if domain_scores[0][1] > 0 else GENERAL_DOMAIN
        secondary = [d for d, s in domain_scores[1:3] if s > 0]

        skills = dedupe_skills(req.skills)
        domain_kw = DOMAIN_KEYWORDS.get(primary, [])
        core_skills = sorted(skills, key=lambda s: (not any(s.lower() == k.lower() for k in domain_kw), skills.index(s)))[:8]

        achievements = [a for e in req.experience for a in e.achievements] + [
            s for e in req.experience for s in split_sentences(e.description)
        ]
        quantified = []
        for raw in (a for a in achievements if has_metric(a)):
            bullet = fix_spelling(normalize_bullet(raw))[0]
            quantified.append(to_past_tense(bullet) or bullet)

        profile = ProfileAnalysis(
            candidate_level=level,
            primary_domain=primary,
            secondary_domains=secondary,
            years_experience=years,
            core_skills=core_skills,
            career_highlights=quantified[:3],
            strengths=self._heuristic_strengths(req, primary, core_skills, years, len(quantified)),
            gaps=self._heuristic_gaps(req, len(quantified)),
        )

        llm_out = await self.try_llm(
            PROFILE_ANALYZER_SYSTEM,
            {
                "computed_facts": profile.model_dump(include={"candidate_level", "primary_domain", "years_experience"}),
                "target_role": req.target_role,
                # PII minimisation: contact details are never sent to the LLM.
                "profile": req.model_dump(exclude={"contact"}),
            },
            ProfileLLMOutput,
        )
        if llm_out:
            profile.strengths = llm_out.strengths or profile.strengths
            profile.gaps = llm_out.gaps or profile.gaps
            profile.career_highlights = llm_out.career_highlights or profile.career_highlights

        ctx.profile = profile
        return llm_out is not None

    @staticmethod
    def _heuristic_strengths(req: ResumeRequest, domain: str, core: list[str], years: float, quantified: int) -> list[str]:
        strengths = []
        if core:
            strengths.append(f"Solid {domain} toolkit including {', '.join(core[:3])}")
        if quantified >= 2:
            strengths.append(f"Demonstrated measurable business impact ({quantified} quantified achievements)")
        if years >= 6:
            strengths.append(f"Extensive hands-on industry experience ({years:g} years)")
        companies = {e.company.lower() for e in req.experience}
        if len(companies) >= 2:
            strengths.append(f"Cross-organisation experience across {_plural(len(companies), 'employer')}")
        if req.certifications:
            strengths.append(f"Expertise validated by {_plural(len(req.certifications), 'professional certification')}")
        if req.projects:
            strengths.append(f"Hands-on project portfolio ({_plural(len(req.projects), 'project')})")
        return strengths[:5]

    @staticmethod
    def _heuristic_gaps(req: ResumeRequest, quantified: int) -> list[str]:
        gaps = find_employment_gaps(req)
        if req.experience and quantified == 0:
            gaps.append("No quantified achievements — add metrics (%, $, time saved, volume)")
        if not req.experience:
            gaps.append("No professional experience listed — projects and education will carry the resume")
        if not req.education:
            gaps.append("No education history provided")
        if not req.certifications:
            gaps.append("No certifications listed — consider role-relevant credentials")
        return gaps[:5]
