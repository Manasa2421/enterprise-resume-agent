"""HTTP endpoints. Business logic lives in the orchestrator; routes stay thin."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import PlainTextResponse

from app.core.config import Settings, get_settings
from app.core.metrics import metrics
from app.models.schemas import ErrorResponse, ResumeRequest, ResumeResponse, TokenRequest, TokenResponse
from app.orchestrator import ResumeOrchestrator
from app.security.auth import AuthContext, create_access_token, rate_limited_client, verify_api_key

ops_router = APIRouter(tags=["Operations"])
api_router = APIRouter(prefix="/api/v1")

_ERRORS = {
    401: {"model": ErrorResponse, "description": "Missing or invalid credentials"},
    422: {"model": ErrorResponse, "description": "Request validation failed"},
    429: {"model": ErrorResponse, "description": "Rate limit exceeded"},
    500: {"model": ErrorResponse, "description": "Internal error"},
    502: {"model": ErrorResponse, "description": "Agent failure"},
    504: {"model": ErrorResponse, "description": "Pipeline timeout"},
}


def get_orchestrator(request: Request) -> ResumeOrchestrator:
    return request.app.state.orchestrator


@ops_router.get("/health", summary="Liveness probe")
async def health() -> dict:
    return {"status": "ok"}


@ops_router.get("/ready", summary="Readiness probe")
async def ready(request: Request, settings: Settings = Depends(get_settings)) -> dict:
    orchestrator = getattr(request.app.state, "orchestrator", None)
    if orchestrator is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Not ready")
    return {
        "status": "ready",
        "version": settings.app_version,
        "environment": settings.environment,
        "llm_provider": orchestrator.llm.provider,
    }


@ops_router.get("/metrics", response_class=PlainTextResponse, summary="Prometheus metrics")
async def prometheus_metrics() -> str:
    # Expose on an internal network / scrape port only (see README → Deployment).
    return metrics.render()


@api_router.post("/auth/token", response_model=TokenResponse, tags=["Authentication"],
                 summary="Exchange an API key for a short-lived JWT", responses={401: _ERRORS[401]})
async def issue_token(body: TokenRequest, settings: Settings = Depends(get_settings)) -> TokenResponse:
    client_id = verify_api_key(body.api_key, settings)
    if client_id is None:
        metrics.inc("auth_failures_total", {"reason": "token_exchange_invalid_key"})
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
    token, expires_in = create_access_token(client_id, settings)
    return TokenResponse(access_token=token, expires_in=expires_in)


@api_router.post(
    "/resume/generate",
    response_model=ResumeResponse,
    tags=["Resume"],
    summary="Generate an ATS-optimised resume via the multi-agent pipeline",
    responses=_ERRORS,
)
async def generate_resume(
    body: ResumeRequest,
    request: Request,
    auth: AuthContext = Depends(rate_limited_client),
    orchestrator: ResumeOrchestrator = Depends(get_orchestrator),
) -> ResumeResponse:
    return await orchestrator.generate(body, request_id=request.state.request_id)
