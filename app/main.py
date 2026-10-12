"""
Application entry point (`uvicorn app.main:app`).

Request flow:
  client → request-context middleware (request ID, size limit, security headers,
  access log, metrics) → router → auth + rate-limit dependencies → orchestrator
"""

import logging
import re
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.routes import api_router, ops_router
from app.core.config import get_settings
from app.core.exceptions import AppError
from app.core.logging import request_id_ctx, setup_logging
from app.core.metrics import metrics
from app.llm.client import build_llm_client
from app.orchestrator import ResumeOrchestrator
from app.security.rate_limit import SlidingWindowRateLimiter

logger = logging.getLogger("app")

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
_DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")
_HTTP_ERROR_CODES = {400: "bad_request", 401: "unauthorized", 403: "forbidden", 404: "not_found",
                     405: "method_not_allowed", 413: "payload_too_large", 429: "rate_limited", 503: "unavailable"}


def _error(status: int, code: str, message: str, request_id: str, headers: dict | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "request_id": request_id}},
        headers=headers,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.orchestrator = ResumeOrchestrator(build_llm_client(settings), settings)
    app.state.rate_limiter = SlidingWindowRateLimiter(limit=settings.rate_limit_per_minute)
    logger.info("app.startup", extra={"version": settings.app_version, "environment": settings.environment,
                                      "llm_provider": settings.llm_provider})
    yield
    logger.info("app.shutdown")


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings.log_level)

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Multi-agent, ATS-optimised resume generation service.",
        lifespan=lifespan,
        # API docs are disabled in production to reduce attack surface.
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None if settings.is_production else "/redoc",
        openapi_url=None if settings.is_production else "/openapi.json",
    )

    if settings.cors_origin_list:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origin_list,
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "Content-Type", "X-API-Key", "X-Request-ID"],
        )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        incoming = request.headers.get("X-Request-ID", "")
        request_id = incoming if _REQUEST_ID_RE.match(incoming) else uuid.uuid4().hex  # reject log-injection attempts
        token = request_id_ctx.set(request_id)
        request.state.request_id = request_id
        start = time.perf_counter()
        try:
            length = request.headers.get("content-length")
            if length and (not length.isdigit() or int(length) > settings.max_request_bytes):
                response = _error(413, "payload_too_large", f"Request body exceeds {settings.max_request_bytes} bytes", request_id)
            else:
                response = await call_next(request)
        except Exception:
            logger.exception("http.unhandled_exception")
            response = _error(500, "internal_error", "An unexpected error occurred.", request_id)

        duration = time.perf_counter() - start
        route = request.scope.get("route")
        path = getattr(route, "path", "unmatched")  # route template keeps metric cardinality bounded
        labels = {"method": request.method, "path": path, "status": str(response.status_code)}
        metrics.inc("http_requests_total", labels, help_text="HTTP requests")
        metrics.observe("http_request_duration_seconds", duration, {"path": path}, "HTTP request latency")
        logger.info("http.request", extra={**labels, "duration_ms": round(duration * 1000, 2),
                                           "client_id": getattr(request.state, "client_id", "anonymous")})

        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"  # responses contain PII
        if not request.url.path.startswith(_DOCS_PATHS):
            response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        if settings.is_production:
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        request_id_ctx.reset(token)
        return response

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        logger.error("app.error", extra={"code": exc.code, "error": exc.message})
        return _error(exc.status_code, exc.code, exc.message, request.state.request_id)

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(request: Request, exc: StarletteHTTPException):
        code = _HTTP_ERROR_CODES.get(exc.status_code, "http_error")
        return _error(exc.status_code, code, str(exc.detail), request.state.request_id, getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        # Report field locations and messages only; never echo submitted values (may contain PII).
        problems = ["/".join(str(p) for p in err["loc"] if p != "body") + f": {err['msg']}" for err in exc.errors()[:10]]
        metrics.inc("validation_errors_total", help_text="Rejected invalid requests")
        return _error(422, "validation_error", "; ".join(problems), request.state.request_id)

    app.include_router(ops_router)
    app.include_router(api_router)
    return app


app = create_app()
