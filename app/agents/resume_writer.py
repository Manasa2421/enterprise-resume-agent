"""
Agent 3 — Resume Writer.

Generates the professional summary, experience bullets, skills section and
project descriptions. Structural, factual sections (header, dates, education,
certifications, skills grouping) are always assembled deterministically from
the validated input, so the LLM can only influence *wording*, never facts.
"""

from app.agents.base import BaseAgent, PipelineContext
from app.agents.knowledge import SKILL_CATEGORIES
from app.agents.text_utils import (
    clean_whitespace,
    dedupe_skills,
    format_date_range,
    has_metric,
    normalize_bullet,
    split_sentences,
)
from app.llm.prompts import RESUME_WRITER_SYSTEM
from app.models.schemas import (
    EducationEntry,
    ExperienceEntry,
    ProjectEntry,
    ResumeContent,
    ResumeRequest,
    WriterLLMOutput,
)

MAX_BULLETS_PER_ROLE = 5

_LEVEL_ADJECTIVE = {
    "Entry-Level": "Motivated",
    "Mid-Level": "Results-driven",
    "Senior": "Seasoned",
    "Lead/Principal": "Accomplished",
}

_DOMAIN_VALUE = {
    "Data Analytics": "turning complex datasets into clear, actionable insights that drive business decisions",
    "Data Science & Machine Learning": "taking machine learning solutions from experimentation to production with measurable business value",
    "Software Engineering": "building reliable, maintainable software and collaborating effectively across engineering teams",
    "Frontend Development": "crafting fast, accessible and user-centred web experiences",
    "DevOps & Cloud": "automating infrastructure and improving the reliability and speed of delivery pipelines",
    "Cybersecurity": "strengthening security posture through proactive threat detection and rapid incident response",
    "Project Management": "delivering complex initiatives on time and on budget through clear communication and disciplined execution",
    "Digital Marketing": "running data-driven campaigns that grow traffic, engagement and conversion",
}
_DEFAULT_VALUE = "dependable execution, clear communication and continuous improvement"


def _join_list(items: list[str]) -> str:
    if len(items) <= 2:
        return " and ".join(items)
    return ", ".join(items[:-1]) + f" and {items[-1]}"


def _as_sentence(text: str) -> str:
    text = clean_whitespace(text).rstrip(".;, ")
    return (text[:1].upper() + text[1:] + ".") if text else ""


def categorize_skills(skills: list[str], priority: list[str]) -> dict[str, list[str]]:
    """Group skills into ATS-friendly categories, matched keywords first."""
    priority_lower = [p.lower() for p in priority]
    ordered = sorted(skills, key=lambda s: (s.lower() not in priority_lower, skills.index(s)))
    lookup = {item.lower(): cat for cat, items in SKILL_CATEGORIES.items() for item in items}
    grouped: dict[str, list[str]] = {}
    for skill in ordered:
        grouped.setdefault(lookup.get(skill.lower(), "Professional Skills"), []).append(skill)
    return grouped


class ResumeWriterAgent(BaseAgent):
    name = "resume_writer"

    async def execute(self, ctx: PipelineContext) -> bool:
        req, profile, ats = ctx.request, ctx.profile, ctx.ats
        assert profile is not None and ats is not None, "Writer requires profile and ATS analysis"

        resume = self._build_deterministic(req, profile.primary_domain, profile.candidate_level,
                                           profile.years_experience, profile.core_skills, ats.matched_keywords)

        llm_out = await self.try_llm(
            RESUME_WRITER_SYSTEM.replace("{tone}", req.tone),
            {
                "target_role": req.target_role,
                "profile_analysis": profile.model_dump(),
                "ats_keywords_to_use": ats.matched_keywords,
                "reviewer_feedback_to_fix": ctx.review_feedback,
                "profile": req.model_dump(exclude={"contact"}),
            },
            WriterLLMOutput,
        )
        used_llm = False
        if llm_out and len(llm_out.experience) == len(req.experience) and (
            not req.projects or len(llm_out.projects) == len(req.projects)
        ):
            resume.professional_summary = clean_whitespace(llm_out.professional_summary)
            for entry, generated in zip(resume.experience, llm_out.experience):
                entry.bullets = [normalize_bullet(b) for b in generated.bullets][:MAX_BULLETS_PER_ROLE]
            for entry, generated in zip(resume.projects, llm_out.projects):
                entry.description = _as_sentence(generated.description)
            used_llm = True
        elif llm_out:
            self.logger.warning("writer.llm_shape_mismatch", extra={"agent": self.name})

        # Reverse-chronological order: current roles first, then by most recent end date.
        order = sorted(
            range(len(req.experience)),
            key=lambda i: (req.experience[i].end_date is None, req.experience[i].end_date or "", req.experience[i].start_date),
            reverse=True,
        )
        resume.experience = [resume.experience[i] for i in order]
        ctx.resume = resume
        return used_llm

    def _build_deterministic(
        self, req: ResumeRequest, domain: str, level: str, years: float, core: list[str], matched: list[str]
    ) -> ResumeContent:
        all_skills = dedupe_skills(req.skills + [t for p in req.projects for t in p.technologies])
        return ResumeContent(
            header=req.contact,
            professional_summary=self._summary(req, domain, level, years, core, matched),
            skills=categorize_skills(all_skills, matched),
            experience=[
                ExperienceEntry(
                    job_title=e.job_title,
                    company=e.company,
                    location=e.location,
                    date_range=format_date_range(e.start_date, e.end_date),
                    bullets=self._bullets(e.achievements + split_sentences(e.description)),
                )
                for e in req.experience  # input order; sorted after LLM merge (see execute)
            ],
            projects=[
                ProjectEntry(
                    name=p.name,
                    description=" ".join(filter(None, [_as_sentence(p.description), _as_sentence(p.outcome or "")])),
                    technologies=dedupe_skills(p.technologies),
                )
                for p in req.projects
            ],
            education=[
                EducationEntry(
                    degree=f"{ed.degree} in {ed.field_of_study}" if ed.field_of_study else ed.degree,
                    institution=ed.institution,
                    year=ed.graduation_year,
                    details=f"Grade: {ed.grade}" if ed.grade else None,
                )
                for ed in sorted(req.education, key=lambda ed: ed.graduation_year or 0, reverse=True)
            ],
            certifications=[
                c.name + (f" — {c.issuer}" if c.issuer else "") + (f" ({c.year})" if c.year else "")
                for c in req.certifications
            ],
        )

    @staticmethod
    def _summary(req: ResumeRequest, domain: str, level: str, years: float, core: list[str], matched: list[str]) -> str:
        role = req.target_role.strip()
        seniority = ("senior", "sr.", "lead", "principal", "head of", "junior", "jr.")
        if level in ("Entry-Level", "Mid-Level"):
            # Integrity rule: never claim a seniority the candidate has not held.
            for prefix in seniority:
                if role.lower().startswith(prefix + " "):
                    role = role[len(prefix) + 1:].strip()
                    break
        adjective = _LEVEL_ADJECTIVE[level]
        opener = role if role.lower().startswith(seniority) else f"{adjective} {role}"
        area = domain if domain != "General Professional" else "the field"
        experience = (
            f"with {int(years)}+ years of experience in {area}" if years >= 1
            else f"with hands-on academic and project experience in {area}"
        )
        highlight = dedupe_skills([s for s in matched if s in core] + core)[:4]
        sentences = [f"{opener} {experience}."]
        if highlight:
            sentences.append(f"Skilled in {_join_list(highlight)}.")
        sentences.append(f"Known for {_DOMAIN_VALUE.get(domain, _DEFAULT_VALUE)}.")
        if req.certifications:
            sentences.append(f"Holds {_join_list([c.name for c in req.certifications[:2]])} certification"
                             f"{'s' if len(req.certifications[:2]) > 1 else ''}.")
        return " ".join(sentences)

    @staticmethod
    def _bullets(raw: list[str]) -> list[str]:
        seen: set[str] = set()
        bullets: list[str] = []
        for item in raw:
            bullet = normalize_bullet(item)
            if len(bullet.split()) >= 4 and bullet.lower() not in seen:
                seen.add(bullet.lower())
                bullets.append(bullet)
        # Quantified achievements first: recruiters scan the top bullets.
        bullets.sort(key=lambda b: not has_metric(b))
        return bullets[:MAX_BULLETS_PER_ROLE]
