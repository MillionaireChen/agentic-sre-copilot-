from typing import Any, TypedDict


class IncidentState(TypedDict, total=False):
    incident_id: str
    run_id: str
    service: str
    severity: str
    title: str

    start_time: str
    current_time: str

    plan: list[str]
    investigation_round: int

    metrics_evidence: dict[str, Any]
    log_evidence: dict[str, Any]
    deployment_evidence: dict[str, Any]
    runbook_evidence: dict[str, Any]

    hypotheses: list[dict]

    root_cause: str
    confidence: float

    proposed_action: dict[str, Any]
    action_risk: str

    approval_status: str  # pending | approved | rejected

    action_result: dict[str, Any]
    baseline_before: dict[str, Any]
    verification_result: dict[str, Any]
    verification_attempts: int

    final_report: str
