import logging

from incidentiq.main import create_app
from incidentiq.observability import Metrics
from tests.auth_support import authorized_client


def test_summary_and_prometheus_metrics_are_aggregated():
    metrics = Metrics()
    metrics.request(10, 200)
    metrics.request(30, 503)
    metrics.retrieval(4)
    metrics.retrieval(6, reranker_used=True)
    metrics.llm(input_tokens=12, output_tokens=5, cost=0.02, fallback=True)

    summary = metrics.summary(3600)
    assert summary["requests"] == {"total": 2, "success_rate": 0.5, "error_rate": 0.5}
    assert summary["latency_ms"] == {"p50": 10, "p95": 30, "p99": 30}
    assert summary["llm"]["input_tokens"] == 12
    assert summary["llm"]["fallback_count"] == 1
    assert summary["retrieval"]["average_candidates"] == 5
    assert summary["retrieval"]["reranker_usage_rate"] == 0.5

    exposition = metrics.prometheus()
    assert 'incidentiq_requests_total{status_class="2xx"} 1' in exposition
    assert 'incidentiq_request_duration_ms_bucket{le="+Inf"} 2' in exposition
    assert "12" in exposition
    assert "authorization" not in exposition.casefold()


def test_request_ids_health_and_access_log_omit_query_values(caplog):
    caplog.set_level(logging.INFO, logger="incidentiq.access")
    client = authorized_client(create_app(api_token="", readonly_api_token=""))
    response = client.get("/health/live?token=do-not-log-this")
    assert response.status_code == 200
    assert response.headers["x-request-id"].startswith("req_")
    assert client.get("/health/ready").status_code == 503
    assert "do-not-log-this" not in " ".join(
        record.getMessage() for record in caplog.records
    )
