import json
import os
import pathlib

# Configure the environment BEFORE the app (and its cached settings) is imported.
os.environ.update(
    {
        "ENVIRONMENT": "test",
        "API_KEYS": "test-key-123456,second-key-654321",
        "JWT_SECRET": "test-secret-that-is-long-enough-0123456789",
        "LLM_PROVIDER": "mock",
        "LLM_API_KEY": "",
        "RATE_LIMIT_PER_MINUTE": "1000",
        "LOG_LEVEL": "WARNING",
    }
)

import pytest  # noqa: E402

from app.core.config import get_settings  # noqa: E402

get_settings.cache_clear()

ROOT = pathlib.Path(__file__).resolve().parent.parent
API_HEADERS = {"X-API-Key": "test-key-123456"}


@pytest.fixture
def sample_payload() -> dict:
    return json.loads((ROOT / "samples" / "sample_request.json").read_text())


@pytest.fixture
def fixed_payload(sample_payload) -> dict:
    """Sample with a fixed end date so years-of-experience assertions are date-independent."""
    sample_payload["experience"][0]["end_date"] = "2026-05"  # 2021-06 → 2026-05 = 5.0 years
    return sample_payload


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client
