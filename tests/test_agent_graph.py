"""Agent graph unit tests with all external tools stubbed (no stack needed).

Exercises the full graph: investigation -> diagnosis -> approval interrupt
-> action -> verification -> report, using the deterministic mock LLM path.
"""
import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from backend.agent import graph as g

INCIDENT = {
    "incident_id": "INC-test", "run_id": "RUN-test",
    "service": "payments-api", "severity": "SEV-1",
    "title": "payments-api latency degraded",
    "start_time": "2026-08-11T14:05:00Z",
}

DEGRADED = {
    "p95_latency_5m": "4.3", "error_rate_5m": "0.087",
    "db_pool_active": "10", "db_pool_max": "10", "db_pool_waiting": "64",
    "db_wait_p95": "3.7", "cache_hit_ratio": "0.94",
    "memory_bytes": "1.3e9", "restarts_15m": None,
}


@pytest.fixture
def stubbed(monkeypatch):
    monkeypatch.setattr(g, "query_prometheus",
                        lambda **kw: {"resultType": "vector",
                                      "result": [{"metric": {}, "value": "1"}]})
    monkeypatch.setattr(g, "query_logs", lambda **kw: {"count": 3, "logs": [
        {"message": "payment failed",
         "error": "timeout acquiring database connection after 2000ms",
         "level": "ERROR", "ts": "t"}]})
    monkeypatch.setattr(g, "get_recent_deployments", lambda **kw: {
        "service": "payments-api", "deployments": [{
            "version": "v1.8.0", "previous_version": "v1.7.3",
            "deployed_at": "2026-08-11T14:00:00Z", "commit_sha": "af38d91",
            "config": {"DB_POOL_SIZE": 10}, "status": "active"}]})
    monkeypatch.setattr(g, "search_runbooks", lambda **kw: {"results": [{
        "document": "database-pool-exhaustion.md", "section": "Symptoms",
        "content": "pool saturation ...", "similarity": 0.91}]})
    monkeypatch.setattr(g.action_tools, "rollback_deployment",
                        lambda service, target_version: {"ok": True, "version": target_version})
    # metrics evidence: force the degraded snapshot into collect_metrics
    monkeypatch.setattr(g, "collect_metrics",
                        lambda state: {"metrics_evidence": dict(DEGRADED)})
    monkeypatch.setattr(g, "_snapshot_key_metrics",
                        lambda svc: {"p95_latency": "0.2", "error_rate": "0.002",
                                     "db_pool_waiting": "0"})
    # force the mock path even when a local vLLM is running
    from backend.config import settings
    monkeypatch.setattr(settings, "llm_base_url", "http://localhost:1/v1")
    import time
    monkeypatch.setattr(time, "sleep", lambda s: None)
    # rebuild graph so the patched collect_metrics is bound as the node fn
    return g


def _build(stubbed):
    graph = stubbed.build_graph(checkpointer=MemorySaver())
    return graph, {"configurable": {"thread_id": "t1"}}


def test_pauses_for_approval_with_high_confidence(stubbed):
    graph, cfg = _build(stubbed)
    result = graph.invoke(INCIDENT, cfg)
    assert "__interrupt__" in result
    payload = result["__interrupt__"][0].value
    assert payload["action"] == "rollback_deployment"
    assert payload["parameters"]["target_version"] == "v1.7.3"
    assert payload["risk"] == "HIGH"
    assert payload["confidence"] >= 0.65


def test_approve_executes_and_verifies(stubbed):
    graph, cfg = _build(stubbed)
    graph.invoke(INCIDENT, cfg)
    result = graph.invoke(Command(resume="approve"), cfg)
    assert result["approval_status"] == "approved"
    assert result["action_result"]["ok"] is True
    assert result["verification_result"]["recovered"] is True
    assert "Root Cause" in result["final_report"]


def test_reject_skips_action(stubbed):
    graph, cfg = _build(stubbed)
    graph.invoke(INCIDENT, cfg)
    result = graph.invoke(Command(resume="reject"), cfg)
    assert result["approval_status"] == "rejected"
    assert "action_result" not in result
    assert result["final_report"]


def test_low_confidence_never_acts(stubbed, monkeypatch):
    monkeypatch.setattr(g, "collect_metrics", lambda state: {
        "metrics_evidence": {**DEGRADED, "db_pool_waiting": "0",
                             "db_pool_active": "15", "db_pool_max": "50"}})
    graph, cfg = _build(stubbed)
    result = graph.invoke(INCIDENT, cfg)
    assert "__interrupt__" not in result
    assert result["confidence"] < 0.65
    assert "proposed_action" not in result
    assert result["final_report"]
