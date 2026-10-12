"""Centralised, typed configuration loaded from environment variables / .env."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_INSECURE_DEFAULT_SECRET = "dev-only-insecure-secret-change-me-0123456789"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Application
    app_name: str = "Enterprise AI Resume Generator"
    app_version: str = "1.0.0"
    environment: Literal["development", "test", "staging", "production"] = "development"
    log_level: str = "INFO"

    # Security
    api_keys: str = Field("", description="Comma-separated list of valid API keys")
    jwt_secret: str = _INSECURE_DEFAULT_SECRET
    jwt_algorithm: str = "HS256"
    jwt_expiry_minutes: int = Field(30, ge=1, le=1440)
    rate_limit_per_minute: int = Field(20, ge=1)
    max_request_bytes: int = Field(100_000, ge=1_000)
    cors_origins: str = Field("", description="Comma-separated allowed origins; empty = CORS disabled")

    # LLM
    llm_provider: Literal["mock", "anthropic", "openai"] = "mock"
    llm_model: str = "claude-sonnet-5-5"
    llm_api_key: str = ""
    llm_timeout_seconds: float = Field(30.0, gt=0)
    llm_max_retries: int = Field(2, ge=0, le=5)
    llm_temperature: float = Field(0.3, ge=0, le=1)
    llm_max_tokens: int = Field(2000, ge=256)

    # Pipeline
    pipeline_timeout_seconds: float = Field(120.0, gt=0)
    max_review_revisions: int = Field(1, ge=0, le=3)

    @property
    def api_key_list(self) -> list[str]:
        return [k.strip() for k in self.api_keys.split(",") if k.strip()]

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @model_validator(mode="after")
    def _validate_security(self) -> "Settings":
        # Fail fast: never let an insecure configuration reach production.
        if self.environment in ("staging", "production"):
            if self.jwt_secret == _INSECURE_DEFAULT_SECRET or len(self.jwt_secret) < 32:
                raise ValueError("JWT_SECRET must be set to a strong value (>= 32 chars) outside development")
            if not self.api_key_list:
                raise ValueError("API_KEYS must be configured outside development")
        if self.llm_provider != "mock" and not self.llm_api_key:
            raise ValueError(f"LLM_API_KEY is required when LLM_PROVIDER={self.llm_provider}")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
