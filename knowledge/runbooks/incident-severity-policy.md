# Incident Severity Policy

## Levels

- **SEV-1** — customer-facing outage or severe degradation:
  error rate > 5%, or p95 latency > 10x baseline on a critical path
  (payments, checkout, auth). Immediate response, rollbacks pre-authorized
  pending single operator approval.
- **SEV-2** — significant degradation with partial impact:
  error rate 1–5% or p95 latency 3–10x baseline, or a non-critical path.
- **SEV-3** — minor degradation, no immediate customer impact.

## Response expectations

| Severity | Acknowledge | Mitigate |
|---|---|---|
| SEV-1 | 5 min | 30 min |
| SEV-2 | 15 min | 2 h |
| SEV-3 | next business day | best effort |

## Action risk classes

- HIGH: rollback_deployment, change_configuration on production
- MEDIUM: restart_service
- LOW: read-only queries (no approval needed)

All HIGH and MEDIUM actions require human approval before execution.
