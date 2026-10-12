from app.security.rate_limit import SlidingWindowRateLimiter
from tests.conftest import API_HEADERS

GENERATE = "/api/v1/resume/generate"


# --- operations ---------------------------------------------------------------- #
def test_health_and_readiness(client):
    assert client.get("/health").json() == {"status": "ok"}
    ready = client.get("/ready").json()
    assert ready["status"] == "ready" and ready["llm_provider"] == "mock"


def test_metrics_endpoint_exposes_prometheus_format(client):
    client.get("/health")
    body = client.get("/metrics").text
    assert "# TYPE http_requests_total counter" in body


# --- authentication ------------------------------------------------------------ #
def test_missing_credentials_rejected(client, sample_payload):
    response = client.post(GENERATE, json=sample_payload)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_invalid_api_key_rejected(client, sample_payload):
    response = client.post(GENERATE, json=sample_payload, headers={"X-API-Key": "wrong-key-000000"})
    assert response.status_code == 401


def test_jwt_token_flow(client, sample_payload):
    token_response = client.post("/api/v1/auth/token", json={"api_key": "test-key-123456"})
    assert token_response.status_code == 200
    token = token_response.json()["access_token"]
    response = client.post(GENERATE, json=sample_payload, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200


def test_tampered_jwt_rejected(client, sample_payload):
    token = client.post("/api/v1/auth/token", json={"api_key": "test-key-123456"}).json()["access_token"]
    response = client.post(GENERATE, json=sample_payload, headers={"Authorization": f"Bearer {token[:-4]}abcd"})
    assert response.status_code == 401


# --- resume generation --------------------------------------------------------- #
def test_generate_resume_returns_structured_response(client, sample_payload):
    response = client.post(GENERATE, json=sample_payload, headers=API_HEADERS)
    assert response.status_code == 200
    data = response.json()
    assert set(data) >= {"request_id", "profile_analysis", "ats_analysis", "resume", "review", "metadata"}
    assert data["profile_analysis"]["primary_domain"] == "Data Analytics"
    assert data["ats_analysis"]["missing_keywords"] == ["Power BI", "SQL"]
    assert data["resume"]["professional_summary"]
    assert len(data["metadata"]["agent_trace"]) >= 4
    assert response.headers["X-Request-ID"] == data["request_id"]


def test_client_request_id_is_propagated(client, sample_payload):
    headers = {**API_HEADERS, "X-Request-ID": "trace-abc-12345"}
    response = client.post(GENERATE, json=sample_payload, headers=headers)
    assert response.json()["request_id"] == "trace-abc-12345"


def test_malicious_request_id_is_replaced(client):
    response = client.get("/health", headers={"X-Request-ID": "bad id\nINJECTED"})
    assert response.headers["X-Request-ID"] != "bad id\nINJECTED"


# --- validation & security ---------------------------------------------------- #
def test_invalid_dates_rejected(client, sample_payload):
    sample_payload["experience"][1]["end_date"] = "2019-01"  # before start date
    response = client.post(GENERATE, json=sample_payload, headers=API_HEADERS)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_unknown_fields_rejected(client, sample_payload):
    sample_payload["is_admin"] = True
    assert client.post(GENERATE, json=sample_payload, headers=API_HEADERS).status_code == 422


def test_validation_errors_do_not_echo_pii(client, sample_payload):
    sample_payload["contact"]["email"] = "not-an-email-but-secret-value"
    response = client.post(GENERATE, json=sample_payload, headers=API_HEADERS)
    assert response.status_code == 422
    assert "secret-value" not in response.text


def test_oversized_payload_rejected(client, sample_payload):
    sample_payload["target_job_description"] = "x" * 200_000
    response = client.post(GENERATE, json=sample_payload, headers=API_HEADERS)
    assert response.status_code == 413


def test_security_headers_present(client):
    headers = client.get("/health").headers
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["Cache-Control"] == "no-store"


def test_rate_limit_enforced(client, sample_payload):
    client.app.state.rate_limiter = SlidingWindowRateLimiter(limit=1)
    assert client.post(GENERATE, json=sample_payload, headers=API_HEADERS).status_code == 200
    response = client.post(GENERATE, json=sample_payload, headers=API_HEADERS)
    assert response.status_code == 429
    assert "Retry-After" in response.headers
