"""LangGraph incident investigation graph.

triage -> planner -> collect_metrics -> collect_logs -> check_deployment
-> retrieve_runbook -> diagnose -> confidence_gate
   (confidence < 0.65: back to planner, max 2 extra rounds)
-> propose_remediation -> risk_gate (interrupt for human approval)
-> execute_action -> verify -> report
"""
import json
from datetime import datetime, timezone

from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt

from backend.agent.state import IncidentState
from backend.agent.llm import llm_json, llm_text
from backend.tools.prometheus import query_prometheus
from backend.tools.loki import query_logs
from backend.tools.deployments import get_recent_deployments
from backend.tools.rag import search_runbooks
from backend.tools import actions as action_tools

CONFIDENCE_THRESHOLD = 0.65
MAX_ROUNDS = 3

# set by runner: callables emit(node, type, payload) / record_tool(...)
_HOOKS = {"emit": lambda *a, **k: None, "tool": lambda *a, **k: None}


def set_hooks(emit, tool):
    _HOOKS["emit"] = emit
    _HOOKS["tool"] = tool


def _call_tool(node, name, fn, **kwargs):
    _HOOKS["emit"](node, "tool_call", {"tool": name, "arguments": kwargs})
    t0 = datetime.now(timezone.utc)
    try:
        result = fn(**kwargs)
        status = "ok"
    except Exception as e:
        result = {"error": str(e)}
        status = "error"
    ms = int((datetime.now(timezone.utc) - t0).total_seconds() * 1000)
    _HOOKS["tool"](name, kwargs, result, ms, status)
    _HOOKS["emit"](node, "tool_result",
                   {"tool": name, "status": status,
                    "summary": json.dumps(result)[:1500]})
    return result


# ------------------------------------------------------------------ nodes
def triage(state: IncidentState):
    _HOOKS["emit"]("triage", "node_started", {})
    p95 = _call_tool("triage", "query_prometheus", query_prometheus,
                     query='histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{service="%s"}[5m])) by (le))' % state["service"])
    err = _call_tool("triage", "query_prometheus", query_prometheus,
                     query='sum(rate(http_request_errors_total{service="%s"}[5m])) / sum(rate(http_requests_total{service="%s"}[5m]))' % (state["service"], state["service"]))
    summary = {"p95_latency": p95.get("result"), "error_rate": err.get("result")}
    _HOOKS["emit"]("triage", "evidence_found",
                   {"kind": "triage", "summary": summary})
    return {"metrics_evidence": {"triage": summary},
            "investigation_round": state.get("investigation_round", 0),
            "current_time": datetime.now(timezone.utc).isoformat()}


def planner(state: IncidentState):
    _HOOKS["emit"]("planner", "node_started",
                   {"round": state.get("investigation_round", 0)})
    plan = llm_json(
        "You are an SRE incident investigation planner. Produce a short plan.",
        f"Incident: {state['title']} on {state['service']} ({state['severity']}).\n"
        f"Evidence so far: {json.dumps(state.get('metrics_evidence', {}))[:2000]}\n"
        f"Previous hypotheses: {json.dumps(state.get('hypotheses', []))[:1000]}\n"
        'Return {"plan": ["step1", ...]} with 3-5 concrete investigation steps.',
        mock_fn=lambda: {"plan": [
            "Query p95 latency and error rate trends",
            "Check DB pool utilization metrics",
            "Search error logs for the incident window",
            "List recent deployments",
            "Retrieve matching runbooks"]})
    _HOOKS["emit"]("planner", "hypothesis", {"plan": plan.get("plan", [])})
    return {"plan": plan.get("plan", []),
            "investigation_round": state.get("investigation_round", 0) + 1}


def collect_metrics(state: IncidentState):
    _HOOKS["emit"]("collect_metrics", "node_started", {})
    svc = state["service"]
    queries = {
        "p95_latency_5m": 'histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{service="%s"}[5m])) by (le))' % svc,
        "error_rate_5m": 'sum(rate(http_request_errors_total{service="%s"}[5m])) / sum(rate(http_requests_total{service="%s"}[5m]))' % (svc, svc),
        "db_pool_active": 'db_pool_active_connections{service="%s"}' % svc,
        "db_pool_max": 'db_pool_max_connections{service="%s"}' % svc,
        "db_pool_waiting": 'db_pool_waiting_requests{service="%s"}' % svc,
        "db_wait_p95": 'histogram_quantile(0.95, sum(rate(db_pool_wait_seconds_bucket{service="%s"}[5m])) by (le))' % svc,
        "cache_hit_ratio": 'cache_hit_ratio{service="%s"}' % svc,
        "memory_bytes": 'demo_process_resident_memory_bytes{service="%s"}' % svc,
        "restarts_15m": 'increase(container_restart_count_total{service="%s"}[15m])' % svc,
    }
    evidence = dict(state.get("metrics_evidence", {}))
    for key, q in queries.items():
        out = _call_tool("collect_metrics", "query_prometheus",
                         query_prometheus, query=q)
        vals = out.get("result", [])
        evidence[key] = vals[0]["value"] if vals and "value" in vals[0] else None
    _HOOKS["emit"]("collect_metrics", "evidence_found",
                   {"kind": "metrics", "summary": {k: evidence.get(k) for k in queries}})
    return {"metrics_evidence": evidence}


def collect_logs(state: IncidentState):
    _HOOKS["emit"]("collect_logs", "node_started", {})
    errors = _call_tool("collect_logs", "query_logs", query_logs,
                        service=state["service"], query='| json | level="ERROR"',
                        limit=40)
    warns = _call_tool("collect_logs", "query_logs", query_logs,
                       service=state["service"], query='| json | level="WARN"',
                       limit=20)
    # compact: message + fields, deduplicated by message
    def compact(logs):
        seen, out = {}, []
        for rec in logs.get("logs", []):
            msg = rec.get("message", rec.get("raw", ""))
            seen[msg] = seen.get(msg, 0) + 1
        for msg, n in sorted(seen.items(), key=lambda x: -x[1])[:10]:
            out.append({"message": msg, "count": n})
        return out
    evidence = {"error_summary": compact(errors), "error_count": errors.get("count"),
                "warn_summary": compact(warns),
                "samples": errors.get("logs", [])[:5]}
    _HOOKS["emit"]("collect_logs", "evidence_found",
                   {"kind": "logs", "summary": {"errors": evidence["error_summary"],
                                                "warnings": evidence["warn_summary"]}})
    return {"log_evidence": evidence}


def check_deployment(state: IncidentState):
    _HOOKS["emit"]("check_deployment", "node_started", {})
    deps = _call_tool("check_deployment", "get_recent_deployments",
                      get_recent_deployments, service=state["service"])
    _HOOKS["emit"]("check_deployment", "evidence_found",
                   {"kind": "deployments", "summary": deps})
    return {"deployment_evidence": deps}


def retrieve_runbook(state: IncidentState):
    _HOOKS["emit"]("retrieve_runbook", "node_started", {})
    logs = state.get("log_evidence", {}).get("error_summary", [])
    metrics = state.get("metrics_evidence", {})
    query = (f"{state['title']}. errors: "
             + "; ".join(e["message"] for e in logs[:3])
             + f". db pool waiting={metrics.get('db_pool_waiting')}"
               f" cache_hit={metrics.get('cache_hit_ratio')}")
    rb = _call_tool("retrieve_runbook", "search_runbooks", search_runbooks,
                    query=query, top_k=5)
    _HOOKS["emit"]("retrieve_runbook", "evidence_found",
                   {"kind": "runbooks",
                    "summary": [{"document": r["document"], "section": r["section"],
                                 "similarity": r["similarity"]}
                                for r in rb.get("results", [])]})
    return {"runbook_evidence": rb}


def _mock_diagnose(state):
    """Deterministic diagnosis from evidence (used when the LLM is offline)."""
    m = state.get("metrics_evidence", {})
    deps = state.get("deployment_evidence", {}).get("deployments", [])
    recent = deps[0] if deps else {}
    def f(x):
        try:
            return float(x)
        except (TypeError, ValueError):
            return None
    waiting, active, mx = f(m.get("db_pool_waiting")), f(m.get("db_pool_active")), f(m.get("db_pool_max"))
    cache = f(m.get("cache_hit_ratio"))
    mem = f(m.get("memory_bytes"))
    if waiting and waiting > 0 and active and mx and active >= mx:
        return {"root_cause": (
            f"{state['service']} {recent.get('version', 'latest deployment')} introduced an "
            f"incorrect DB pool configuration ({recent.get('config')}); the pool is saturated "
            f"({int(active)}/{int(mx)} with {int(waiting)} waiting requests), causing "
            "connection acquisition timeouts and the latency/error spike."),
            "confidence": 0.94,
            "hypotheses": [{"cause": "db_pool_configuration_regression", "confidence": 0.94}]}
    if cache is not None and cache < 0.5:
        return {"root_cause": "Redis connectivity degradation collapsed the cache hit ratio, pushing traffic to the database.",
                "confidence": 0.88,
                "hypotheses": [{"cause": "redis_connectivity_degradation", "confidence": 0.88}]}
    if mem and mem > 4e9:
        return {"root_cause": f"Memory leak introduced by the latest deployment {recent.get('version')}; RSS growth leads to OOM restarts.",
                "confidence": 0.85,
                "hypotheses": [{"cause": "memory_leak_from_deployment", "confidence": 0.85}]}
    return {"root_cause": "insufficient evidence", "confidence": 0.3,
            "hypotheses": [{"cause": "unknown", "confidence": 0.3}]}


def diagnose(state: IncidentState):
    _HOOKS["emit"]("diagnose", "node_started", {})
    evidence = {
        "metrics": state.get("metrics_evidence", {}),
        "logs": {k: v for k, v in state.get("log_evidence", {}).items() if k != "samples"},
        "deployments": state.get("deployment_evidence", {}),
        "runbooks": [{"document": r["document"], "section": r["section"],
                      "similarity": r["similarity"], "content": r["content"][:600]}
                     for r in state.get("runbook_evidence", {}).get("results", [])],
    }
    out = llm_json(
        "You are an SRE diagnosis expert. Given the evidence, identify the most "
        "likely root cause of the incident and your confidence (0-1). Base your "
        "conclusion strictly on the evidence.",
        f"Incident: {state['title']} on {state['service']}.\n"
        f"Evidence:\n{json.dumps(evidence, default=str)[:6000]}\n"
        'Return {"root_cause": "...", "confidence": 0.x, '
        '"hypotheses": [{"cause": "...", "confidence": 0.x}]}',
        mock_fn=lambda: _mock_diagnose(state))
    _HOOKS["emit"]("diagnose", "hypothesis",
                   {"root_cause": out.get("root_cause"),
                    "confidence": out.get("confidence"),
                    "mock": out.get("_mock", False)})
    return {"root_cause": out.get("root_cause", ""),
            "confidence": float(out.get("confidence", 0)),
            "hypotheses": out.get("hypotheses", [])}


def confidence_gate(state: IncidentState) -> str:
    if state.get("confidence", 0) >= CONFIDENCE_THRESHOLD:
        return "propose_remediation"
    if state.get("investigation_round", 0) >= MAX_ROUNDS:
        # never act on a low-confidence diagnosis: report and hand to a human
        _HOOKS["emit"]("confidence_gate", "node_started",
                       {"decision": "give_up_to_report",
                        "confidence": state.get("confidence")})
        return "report"
    _HOOKS["emit"]("confidence_gate", "node_started",
                   {"decision": "re-investigate",
                    "confidence": state.get("confidence")})
    return "planner"


def _mock_propose(state):
    m = state.get("metrics_evidence", {})
    # ignore rollbacks we performed ourselves when picking the culprit deploy
    deps = [d for d in state.get("deployment_evidence", {}).get("deployments", [])
            if d.get("commit_sha") != "rollback"]
    recent = deps[0] if deps else {}
    cause = (state.get("hypotheses") or [{}])[0].get("cause", "")
    if "redis" in cause:
        return {"action": "restart_service",
                "parameters": {"service": "redis"}, "risk": "MEDIUM",
                "reason": "Restart redis to restore cache connectivity."}
    target = recent.get("previous_version") or "v1.7.3"
    return {"action": "rollback_deployment",
            "parameters": {"service": state["service"], "target_version": target},
            "risk": "HIGH",
            "reason": f"Deployment {recent.get('version')} caused the regression; "
                      f"roll back to {target}."}


def propose_remediation(state: IncidentState):
    _HOOKS["emit"]("propose_remediation", "node_started", {})
    out = llm_json(
        "You are an SRE remediation planner. Choose ONE action from: "
        "rollback_deployment(service, target_version), restart_service(service), "
        "change_configuration(service, key, value). Assign risk HIGH/MEDIUM/LOW.",
        f"Root cause: {state.get('root_cause')}\n"
        f"Confidence: {state.get('confidence')}\n"
        f"Deployments: {json.dumps(state.get('deployment_evidence', {}))[:1500]}\n"
        f"Runbook guidance: {json.dumps([r['content'][:400] for r in state.get('runbook_evidence', {}).get('results', [])[:2]])}\n"
        'Return {"action": "...", "parameters": {...}, "risk": "HIGH|MEDIUM|LOW", "reason": "..."}',
        mock_fn=lambda: _mock_propose(state))
    proposal = {"action": out.get("action"), "parameters": out.get("parameters", {}),
                "risk": out.get("risk", "HIGH"), "reason": out.get("reason", "")}
    _HOOKS["emit"]("propose_remediation", "hypothesis", {"proposal": proposal})
    return {"proposed_action": proposal, "action_risk": proposal["risk"]}


def risk_gate(state: IncidentState):
    """All WRITE actions require human approval (interrupt)."""
    payload = {
        "incident_id": state["incident_id"],
        "action": state["proposed_action"]["action"],
        "parameters": state["proposed_action"]["parameters"],
        "risk": state.get("action_risk", "HIGH"),
        "reason": state["proposed_action"].get("reason", ""),
        "confidence": state.get("confidence"),
    }
    _HOOKS["emit"]("risk_gate", "approval_required", payload)
    decision = interrupt(payload)
    _HOOKS["emit"]("risk_gate", "approval_decided", {"decision": decision})
    return {"approval_status": "approved" if decision == "approve" else "rejected"}


def approval_branch(state: IncidentState) -> str:
    return "execute_action" if state.get("approval_status") == "approved" else "report"


def _snapshot_key_metrics(service):
    # 1m windows so post-action snapshots aren't polluted by incident samples
    keys = {
        "p95_latency": 'histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{service="%s"}[1m])) by (le))' % service,
        "error_rate": 'sum(rate(http_request_errors_total{service="%s"}[1m])) / sum(rate(http_requests_total{service="%s"}[1m]))' % (service, service),
        "db_pool_waiting": 'db_pool_waiting_requests{service="%s"}' % service,
    }
    snap = {}
    for k, q in keys.items():
        out = query_prometheus(q)
        vals = out.get("result", [])
        snap[k] = vals[0]["value"] if vals and "value" in vals[0] else None
    return snap


def execute_action(state: IncidentState):
    _HOOKS["emit"]("execute_action", "action_started",
                   state["proposed_action"])
    before = _snapshot_key_metrics(state["service"])
    act = state["proposed_action"]
    fn = {"rollback_deployment": action_tools.rollback_deployment,
          "restart_service": action_tools.restart_service}.get(act["action"])
    if fn is None:
        result = {"error": f"unknown action {act['action']}"}
    else:
        result = _call_tool("execute_action", act["action"], fn, **act["parameters"])
    _HOOKS["emit"]("execute_action", "action_finished", {"result": result})
    return {"action_result": result, "baseline_before": before}


def verify(state: IncidentState):
    """Re-query Prometheus and compare against the pre-action baseline."""
    import time
    _HOOKS["emit"]("verify", "node_started",
                   {"waiting_seconds": 75, "note": "letting the 1m rate window clear incident samples"})
    time.sleep(75)
    after = _snapshot_key_metrics(state["service"])
    before = state.get("baseline_before", {})
    def f(x):
        try:
            return float(x)
        except (TypeError, ValueError):
            return None
    p95_after, err_after = f(after.get("p95_latency")), f(after.get("error_rate"))
    waiting_after = f(after.get("db_pool_waiting"))
    recovered = ((p95_after is None or p95_after < 1.0)
                 and (err_after is None or err_after < 0.02)
                 and (waiting_after is None or waiting_after < 5))
    result = {"recovered": recovered, "before": before, "after": after}
    _HOOKS["emit"]("verify", "verification", result)
    return {"verification_result": result,
            "verification_attempts": state.get("verification_attempts", 0) + 1}


def verification_branch(state: IncidentState) -> str:
    if state.get("verification_result", {}).get("recovered"):
        return "report"
    if state.get("verification_attempts", 0) >= 2:
        return "report"
    return "planner"  # recovery failed: re-open investigation


def report(state: IncidentState):
    _HOOKS["emit"]("report", "node_started", {})
    ctx = {
        "incident_id": state["incident_id"], "service": state["service"],
        "severity": state["severity"], "title": state["title"],
        "root_cause": state.get("root_cause"), "confidence": state.get("confidence"),
        "action": state.get("proposed_action"),
        "approval": state.get("approval_status"),
        "verification": state.get("verification_result"),
        "key_metrics": {k: state.get("metrics_evidence", {}).get(k)
                        for k in ("p95_latency_5m", "error_rate_5m",
                                  "db_pool_active", "db_pool_max", "db_pool_waiting")},
        "top_errors": state.get("log_evidence", {}).get("error_summary", [])[:5],
        "deployments": state.get("deployment_evidence", {}),
    }
    def mock_report():
        v = state.get("verification_result", {})
        status = "RESOLVED" if v.get("recovered") else (
            "MITIGATION REJECTED" if state.get("approval_status") == "rejected"
            else "UNRESOLVED")
        act = state.get("proposed_action", {})
        return (
            f"# Incident Report {state['incident_id']}\n\n"
            f"**Service**: {state['service']}  \n**Severity**: {state['severity']}  \n"
            f"**Status**: {status}\n\n"
            f"## Root Cause\n{state.get('root_cause')}\n(confidence {state.get('confidence')})\n\n"
            f"## Evidence\n"
            f"- key metrics: {json.dumps(ctx['key_metrics'])}\n"
            f"- top errors: {json.dumps(ctx['top_errors'])}\n"
            f"- deployments: {json.dumps(ctx['deployments'], default=str)[:800]}\n\n"
            f"## Action\n{act.get('action')} {json.dumps(act.get('parameters', {}))} "
            f"({state.get('approval_status')})\n\n"
            f"## Verification\nbefore: {json.dumps(v.get('before'))}\n"
            f"after: {json.dumps(v.get('after'))}\nrecovered: {v.get('recovered')}\n")
    text = llm_text(
        "You are an SRE writing a concise post-incident report in Markdown with "
        "sections: Summary, Root Cause, Evidence, Action, Verification, Status.",
        json.dumps(ctx, default=str)[:6000],
        mock_fn=mock_report)
    _HOOKS["emit"]("report", "completed", {"report": text})
    return {"final_report": text}


# ------------------------------------------------------------------ graph
def build_graph(checkpointer=None):
    g = StateGraph(IncidentState)
    for name, fn in [("triage", triage), ("planner", planner),
                     ("collect_metrics", collect_metrics),
                     ("collect_logs", collect_logs),
                     ("check_deployment", check_deployment),
                     ("retrieve_runbook", retrieve_runbook),
                     ("diagnose", diagnose),
                     ("propose_remediation", propose_remediation),
                     ("risk_gate", risk_gate),
                     ("execute_action", execute_action),
                     ("verify", verify), ("report", report)]:
        g.add_node(name, fn)
    g.add_edge(START, "triage")
    g.add_edge("triage", "planner")
    g.add_edge("planner", "collect_metrics")
    g.add_edge("collect_metrics", "collect_logs")
    g.add_edge("collect_logs", "check_deployment")
    g.add_edge("check_deployment", "retrieve_runbook")
    g.add_edge("retrieve_runbook", "diagnose")
    g.add_conditional_edges("diagnose", confidence_gate,
                            ["planner", "propose_remediation"])
    g.add_edge("propose_remediation", "risk_gate")
    g.add_conditional_edges("risk_gate", approval_branch,
                            ["execute_action", "report"])
    g.add_edge("execute_action", "verify")
    g.add_conditional_edges("verify", verification_branch,
                            ["planner", "report"])
    g.add_edge("report", END)
    return g.compile(checkpointer=checkpointer)
