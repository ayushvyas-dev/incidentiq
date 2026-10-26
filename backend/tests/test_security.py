from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from incidentiq.main import create_app
from incidentiq.models import Base
from incidentiq.security import SlidingWindowLimiter

ADMIN = "a" * 40
READONLY = "r" * 40


def test_bearer_auth_and_read_only_authorization():
    app = create_app(api_token=ADMIN, readonly_api_token=READONLY)
    with TestClient(app, backend_options={"use_uvloop": True}) as client:
        assert client.get("/api/v1/routing/policies").status_code == 401
        read = client.get(
            "/api/v1/routing/policies", headers={"Authorization": f"Bearer {READONLY}"}
        )
        assert read.status_code == 200
        write = client.post(
            "/api/v1/routing/simulate",
            json={},
            headers={"Authorization": f"Bearer {READONLY}"},
        )
        assert write.status_code == 403
        admin_write = client.post(
            "/api/v1/routing/simulate",
            json={},
            headers={"Authorization": f"Bearer {ADMIN}"},
        )
        assert admin_write.status_code == 422
        assert client.get("/health/live").status_code == 200

    disabled = TestClient(
        create_app(api_token="", readonly_api_token=""),
        backend_options={"use_uvloop": True},
    )
    assert disabled.get("/api/v1/routing/policies").status_code == 503


def test_rate_limiter_sliding_window_and_retry_after():
    limiter = SlidingWindowLimiter(2, window_seconds=60)
    assert limiter.allow("client", now=0) == (True, 0)
    assert limiter.allow("client", now=1) == (True, 0)
    allowed, retry_after = limiter.allow("client", now=2)
    assert allowed is False and retry_after == 58
    assert limiter.allow("client", now=60) == (True, 0)


def test_api_rate_limit_returns_retry_after(monkeypatch):
    monkeypatch.setenv("API_RATE_LIMIT_PER_MINUTE", "1")
    with TestClient(
        create_app(api_token=ADMIN), backend_options={"use_uvloop": True}
    ) as client:
        headers = {"Authorization": f"Bearer {ADMIN}"}
        assert (
            client.get("/api/v1/routing/policies", headers=headers).status_code == 200
        )
        limited = client.get("/api/v1/routing/policies", headers=headers)
        assert limited.status_code == 429
        assert limited.headers["retry-after"]


def test_authentication_is_consistent_across_protected_route_groups():
    client = TestClient(
        create_app(api_token=ADMIN), backend_options={"use_uvloop": True}
    )
    for path in (
        "/api/v1/documents",
        "/api/v1/search",
        "/api/v1/incidents",
        "/api/v1/routing/policies",
        "/api/v1/jobs/00000000-0000-0000-0000-000000000000",
        "/api/v1/evaluations",
        "/api/v1/metrics/summary",
        "/metrics",
    ):
        assert client.get(path).status_code == 401, path
        assert (
            client.get(path, headers={"Authorization": "Bearer invalid"}).status_code
            == 401
        ), path
    client.close()


def test_health_readiness_and_metrics_endpoints(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)

    class Queue:
        def ping(self):
            return True

    app = create_app(session_factory=factory, job_queue=Queue(), api_token=ADMIN)
    client = TestClient(app, backend_options={"use_uvloop": True})
    assert client.get("/health/live").json() == {"status": "alive"}
    ready = client.get("/health/ready")
    assert ready.status_code == 200
    assert ready.json() == {
        "status": "ready",
        "dependencies": {"api_auth": "ok", "postgres": "ok", "redis": "ok"},
    }

    headers = {"Authorization": f"Bearer {ADMIN}"}
    for window in ("1h", "24h", "7d"):
        summary = client.get(
            f"/api/v1/metrics/summary?window={window}", headers=headers
        )
        assert summary.status_code == 200
        assert summary.json()["window"] == window
        assert summary.json()["requests"]["total"] >= 0
    assert (
        client.get("/api/v1/metrics/summary?window=5m", headers=headers).status_code
        == 422
    )
    metrics = client.get("/metrics", headers=headers)
    assert metrics.status_code == 200
    assert "incidentiq_requests_total" in metrics.text
    assert client.get("/metrics").status_code == 401
    client.close()
    engine.dispose()
