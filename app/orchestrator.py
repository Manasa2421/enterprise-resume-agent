"""
Orchestrator — coordinates the agent pipeline.

    Profile Analyzer → ATS Optimizer → Resume Writer → Reviewer
                                            ↑              │
                                            └── feedback ──┘  (bounded revision loop)

Agents run sequentially because each depends on the previous agent's output.
The whole pipeline runs under a hard timeout, and every agent is traced.
"""

import asyncio
import logging
import time
from datetime import datetime, timezone

from app.agents.ats_optimizer import ATSOptimizationAgent
from app.agents.base import PipelineContext
from app.agents.profile_analyzer import ProfileAnalyzerAgent
from app.agents.resume_writer import ResumeWriterAgent
from app.agents.reviewer import ReviewerAgent
from app.core.config import Settings
from app.core.exceptions import PipelineTimeoutError
from app.core.metrics import metrics
from app.llm.client import BaseLLMClient
from app.models.schemas import ResponseMetadata, ResumeRequest, ResumeResponse
from app.security.sanitizer import sanitize_payload

logger = logging.getLogger("orchestrator")


class ResumeOrchestrator:
    def __init__(self, llm: BaseLLMClient, settings: Settings) -> None:
        self.llm = llm
        self.settings = settings
        self.profile_agent = ProfileAnalyzerAgent(llm)
        self.ats_agent = ATSOptimizationAgent(llm)
        self.writer_agent = ResumeWriterAgent(llm)
        self.reviewer_agent = ReviewerAgent(llm)

    async def generate(self, request: ResumeRequest, request_id: str) -> ResumeResponse:
        start = time.perf_counter()

        # Security: sanitise every string, then re-validate against the schema.
        clean_data, flags = sanitize_payload(request.model_dump())
        if flags:
            metrics.inc("security_flags_total", value=flags, help_text="Suspicious input patterns neutralised")
            logger.warning("security.input_sanitised", extra={"flags": flags})
        ctx = PipelineContext(request=ResumeRequest.model_validate(clean_data), request_id=request_id, security_flags=flags)

        logger.info("pipeline.started", extra={"target_role": ctx.request.target_role, "llm_provider": self.llm.provider})
        try:
            await asyncio.wait_for(self._run_pipeline(ctx), timeout=self.settings.pipeline_timeout_seconds)
        except asyncio.TimeoutError as exc:
            metrics.inc("pipeline_runs_total", {"outcome": "timeout"}, help_text="Pipeline executions")
            logger.error("pipeline.timeout", extra={"timeout_s": self.settings.pipeline_timeout_seconds})
            raise PipelineTimeoutError() from exc
        except Exception:
            metrics.inc("pipeline_runs_total", {"outcome": "error"}, help_text="Pipeline executions")
            raise

        elapsed = time.perf_counter() - start
        assert ctx.profile and ctx.ats and ctx.resume and ctx.review
        metrics.inc("pipeline_runs_total", {"outcome": "success"}, help_text="Pipeline executions")
        metrics.observe("pipeline_duration_seconds", elapsed, help_text="End-to-end pipeline latency")
        metrics.inc("resumes_approved_total" if ctx.review.approved else "resumes_flagged_total",
                    help_text="Resumes by reviewer verdict")
        logger.info(
            "pipeline.completed",
            extra={
                "duration_ms": round(elapsed * 1000, 2),
                "ats_score": ctx.ats.ats_score,
                "optimized_ats_score": ctx.ats.optimized_ats_score,
                "quality_score": ctx.review.quality_score,
                "approved": ctx.review.approved,
                "revisions": ctx.revision_count,
            },
        )

        return ResumeResponse(
            request_id=request_id,
            generated_at=datetime.now(timezone.utc),
            processing_time_ms=round(elapsed * 1000, 2),
            profile_analysis=ctx.profile,
            ats_analysis=ctx.ats,
            resume=ctx.resume,
            review=ctx.review,
            metadata=ResponseMetadata(
                llm_provider=self.llm.provider,
                llm_model=self.llm.model if self.llm.enabled else "deterministic-engine",
                revision_count=ctx.revision_count,
                security_flags=ctx.security_flags,
                agent_trace=ctx.trace,
            ),
        )

    async def _run_pipeline(self, ctx: PipelineContext) -> None:
        await self.profile_agent.run(ctx)
        await self.ats_agent.run(ctx)
        await self.writer_agent.run(ctx)
        await self.reviewer_agent.run(ctx)

        # Bounded self-correction loop: reviewer feedback goes back to the writer.
        while ctx.review and not ctx.review.approved and ctx.revision_count < self.settings.max_review_revisions:
            ctx.revision_count += 1
            ctx.review_feedback = [f"[{i.section}] {i.message}" for i in ctx.review.issues if i.severity != "info"]
            logger.info("pipeline.revision", extra={"revision": ctx.revision_count, "feedback_items": len(ctx.review_feedback)})
            await self.writer_agent.run(ctx)
            await self.reviewer_agent.run(ctx)

        ctx.ats.optimized_ats_score = self.ats_agent.score_resume(ctx)
