"""
API contracts. Strict validation (extra fields forbidden, length limits on every
field and list) is the first line of defence against malformed or abusive input.
"""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

YearMonth = Annotated[str, Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$", examples=["2023-06"])]
Skill = Annotated[str, Field(min_length=1, max_length=60)]
Bullet = Annotated[str, Field(min_length=3, max_length=500)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ============================================================================ #
# Request
# ============================================================================ #
class ContactInfo(StrictModel):
    full_name: str = Field(..., min_length=2, max_length=100)
    email: str = Field(..., max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    phone: str | None = Field(None, max_length=30)
    location: str | None = Field(None, max_length=100)
    linkedin: str | None = Field(None, max_length=200)
    portfolio: str | None = Field(None, max_length=200)


class ExperienceInput(StrictModel):
    job_title: str = Field(..., min_length=2, max_length=100)
    company: str = Field(..., min_length=1, max_length=100)
    location: str | None = Field(None, max_length=100)
    start_date: YearMonth
    end_date: YearMonth | None = Field(None, description="YYYY-MM, or null for current role")
    description: str = Field("", max_length=2000)
    achievements: list[Bullet] = Field(default_factory=list, max_length=15)

    @model_validator(mode="after")
    def _check_dates(self) -> "ExperienceInput":
        if self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date must not be earlier than start_date")
        return self


class ProjectInput(StrictModel):
    name: str = Field(..., min_length=2, max_length=120)
    description: str = Field(..., min_length=10, max_length=1000)
    technologies: list[Skill] = Field(default_factory=list, max_length=20)
    outcome: str | None = Field(None, max_length=300)


class EducationInput(StrictModel):
    degree: str = Field(..., min_length=2, max_length=120)
    field_of_study: str | None = Field(None, max_length=120)
    institution: str = Field(..., min_length=2, max_length=150)
    graduation_year: int | None = Field(None, ge=1950, le=2100)
    grade: str | None = Field(None, max_length=30)


class CertificationInput(StrictModel):
    name: str = Field(..., min_length=2, max_length=150)
    issuer: str | None = Field(None, max_length=100)
    year: int | None = Field(None, ge=1950, le=2100)


class ResumeRequest(StrictModel):
    contact: ContactInfo
    target_role: str = Field(..., min_length=2, max_length=100)
    target_job_description: str | None = Field(None, max_length=8000)
    skills: list[Skill] = Field(..., min_length=1, max_length=60)
    experience: list[ExperienceInput] = Field(default_factory=list, max_length=15)
    projects: list[ProjectInput] = Field(default_factory=list, max_length=10)
    education: list[EducationInput] = Field(default_factory=list, max_length=5)
    certifications: list[CertificationInput] = Field(default_factory=list, max_length=15)
    tone: Literal["professional", "executive", "technical"] = "professional"


# ============================================================================ #
# Agent outputs
# ============================================================================ #
class ProfileAnalysis(BaseModel):
    candidate_level: Literal["Entry-Level", "Mid-Level", "Senior", "Lead/Principal"]
    primary_domain: str
    secondary_domains: list[str] = []
    years_experience: float
    core_skills: list[str] = []
    career_highlights: list[str] = []
    strengths: list[str] = []
    gaps: list[str] = []


class ATSAnalysis(BaseModel):
    ats_score: int = Field(..., ge=0, le=100, description="Score of the profile as submitted")
    optimized_ats_score: int | None = Field(None, ge=0, le=100, description="Score of the generated resume")
    score_breakdown: dict[str, int]
    keyword_source: Literal["job_description", "role_profile"]
    matched_keywords: list[str]
    missing_keywords: list[str]
    formatting_suggestions: list[str] = []
    skill_alignment_suggestions: list[str] = []
    role_targeting_notes: list[str] = []


class ExperienceEntry(BaseModel):
    job_title: str
    company: str
    location: str | None = None
    date_range: str
    bullets: list[str]


class ProjectEntry(BaseModel):
    name: str
    description: str
    technologies: list[str] = []


class EducationEntry(BaseModel):
    degree: str
    institution: str
    year: int | None = None
    details: str | None = None


class ResumeContent(BaseModel):
    header: ContactInfo
    professional_summary: str
    skills: dict[str, list[str]]
    experience: list[ExperienceEntry]
    projects: list[ProjectEntry] = []
    education: list[EducationEntry] = []
    certifications: list[str] = []


class ReviewIssue(BaseModel):
    severity: Literal["info", "warning", "error"]
    section: str
    message: str


class ReviewResult(BaseModel):
    approved: bool
    quality_score: int = Field(..., ge=0, le=100)
    issues: list[ReviewIssue] = []
    corrections_applied: list[str] = []


# ============================================================================ #
# LLM output contracts (validated before use — never trust raw LLM output)
# ============================================================================ #
class ProfileLLMOutput(BaseModel):
    strengths: list[Annotated[str, Field(max_length=200)]] = Field(..., max_length=6)
    gaps: list[Annotated[str, Field(max_length=200)]] = Field(default_factory=list, max_length=6)
    career_highlights: list[Annotated[str, Field(max_length=250)]] = Field(default_factory=list, max_length=5)


class ATSLLMOutput(BaseModel):
    skill_alignment_suggestions: list[Annotated[str, Field(max_length=250)]] = Field(..., max_length=6)
    role_targeting_notes: list[Annotated[str, Field(max_length=250)]] = Field(default_factory=list, max_length=6)


class WriterLLMExperience(BaseModel):
    bullets: list[Annotated[str, Field(min_length=10, max_length=300)]] = Field(..., min_length=1, max_length=6)


class WriterLLMProject(BaseModel):
    description: str = Field(..., min_length=10, max_length=500)


class WriterLLMOutput(BaseModel):
    professional_summary: str = Field(..., min_length=50, max_length=900)
    experience: list[WriterLLMExperience]
    projects: list[WriterLLMProject] = []


class ReviewerLLMOutput(BaseModel):
    issues: list[ReviewIssue] = Field(default_factory=list, max_length=15)


# ============================================================================ #
# Response envelope
# ============================================================================ #
class AgentTrace(BaseModel):
    agent: str
    status: Literal["success", "fallback", "failed"]
    duration_ms: float
    used_llm: bool


class ResponseMetadata(BaseModel):
    llm_provider: str
    llm_model: str
    revision_count: int
    security_flags: int
    agent_trace: list[AgentTrace]


class ResumeResponse(BaseModel):
    request_id: str
    status: Literal["completed"] = "completed"
    generated_at: datetime
    processing_time_ms: float
    profile_analysis: ProfileAnalysis
    ats_analysis: ATSAnalysis
    resume: ResumeContent
    review: ReviewResult
    metadata: ResponseMetadata


class TokenRequest(StrictModel):
    api_key: str = Field(..., min_length=8, max_length=256)


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


class ErrorDetail(BaseModel):
    code: str
    message: str
    request_id: str


class ErrorResponse(BaseModel):
    error: ErrorDetail
