"""
Authentication layer.

Two supported schemes:
  1. X-API-Key header — for service-to-service calls.
  2. Bearer JWT       — short-lived token obtained from POST /api/v1/auth/token,
                        so long-lived API keys are not sent on every request.

Keys are compared in constant time and only a hashed fingerprint of the key is
ever logged or used as the client identifier.
"""

import hashlib
import hmac
import logging
import time
from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import Settings, get_settings
from app.core.metrics import metrics

logger = logging.getLogger("security.auth")

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
bearer_scheme = HTTPBearer(auto_error=False)

REQUIRED_SCOPE = "resume:generate"


@dataclass(frozen=True)
class AuthContext:
    client_id: str
    method: str  # "api_key" | "jwt"


def _fingerprint(key: str) -> str:
    return "client_" + hashlib.sha256(key.encode()).hexdigest()[:12]


def verify_api_key(candidate: str, settings: Settings) -> str | None:
    """Return the client id for a valid key, else None. Constant-time comparison."""
    match: str | None = None
    for valid in settings.api_key_list:
        if hmac.compare_digest(candidate.encode(), valid.encode()):
            match = valid
    return _fingerprint(match) if match else None


def create_access_token(client_id: str, settings: Settings) -> tuple[str, int]:
    now = int(time.time())
    ttl = settings.jwt_expiry_minutes * 60
    claims = {"sub": client_id, "iat": now, "exp": now + ttl, "iss": settings.app_name, "scope": REQUIRED_SCOPE}
    return jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm), ttl


def decode_access_token(token: str, settings: Settings) -> str:
    payload = jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],  # pin algorithm: blocks "alg=none" attacks
        issuer=settings.app_name,
        options={"require": ["exp", "iat", "sub", "iss"]},
    )
    if REQUIRED_SCOPE not in str(payload.get("scope", "")).split():
        raise jwt.InvalidTokenError("Missing required scope")
    return str(payload["sub"])


def _unauthorized(detail: str, reason: str) -> HTTPException:
    metrics.inc("auth_failures_total", {"reason": reason}, help_text="Failed authentication attempts")
    logger.warning("auth.failed", extra={"reason": reason})
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def authenticate(
    request: Request,
    api_key: str | None = Security(api_key_header),
    bearer: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
    settings: Settings = Depends(get_settings),
) -> AuthContext:
    if bearer and bearer.credentials:
        try:
            ctx = AuthContext(client_id=decode_access_token(bearer.credentials, settings), method="jwt")
        except jwt.ExpiredSignatureError:
            raise _unauthorized("Token has expired", "token_expired")
        except jwt.InvalidTokenError:
            raise _unauthorized("Invalid token", "token_invalid")
    elif api_key:
        client_id = verify_api_key(api_key, settings)
        if client_id is None:
            raise _unauthorized("Invalid API key", "api_key_invalid")
        ctx = AuthContext(client_id=client_id, method="api_key")
    else:
        raise _unauthorized("Missing credentials: provide X-API-Key or Bearer token", "missing_credentials")

    request.state.client_id = ctx.client_id
    return ctx


async def rate_limited_client(request: Request, auth: AuthContext = Depends(authenticate)) -> AuthContext:
    allowed, retry_after = request.app.state.rate_limiter.check(auth.client_id)
    if not allowed:
        metrics.inc("rate_limited_total", help_text="Requests rejected by rate limiter")
        logger.warning("rate_limit.exceeded", extra={"client_id": auth.client_id})
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded",
            headers={"Retry-After": str(retry_after)},
        )
    return auth
