"""Unit tests for agent tools against the live local stack."""
import pytest

from backend.tools.prometheus import query_prometheus
from backend.tools.loki import query_logs
from backend.tools.deployments import get_recent_deployments
from backend.tools.actions import restart_service, rollback_deployment


def test_query_prometheus_instant():
    out = query_prometheus('db_pool_max_connections{service="payments-api"}')
    assert out["resultType"] == "vector"
    assert out["result"], "expected at least one series"
    assert float(out["result"][0]["value"]) > 0


def test_query_prometheus_p95():
    out = query_prometheus(
        'histogram_quantile(0.95, sum(rate('
        'http_request_duration_seconds_bucket{service="payments-api"}[5m]'
        ')) by (le))')
    assert out["resultType"] == "vector"


def test_query_logs():
    out = query_logs("payments-api", limit=10)
    assert out["count"] >= 0
    if out["logs"]:
        assert "message" in out["logs"][0]


def test_get_recent_deployments():
    out = get_recent_deployments("payments-api", since="2026-08-01T00:00:00Z")
    assert out["service"] == "payments-api"
    assert any(d["version"] == "v1.7.3" for d in out["deployments"])


def test_actions_allow_list():
    assert "error" in restart_service("postgres")
    assert "error" in rollback_deployment("host", "v1")
