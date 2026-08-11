# Production Rollback Procedure

## When to roll back

Roll back instead of forward-fixing when:

- the incident is SEV-1 or SEV-2 and started shortly after a deployment
- the offending change is identified in the deployment diff
- a forward fix would take longer than a rollback

## Procedure

1. Identify the current and target (last known good) versions from the
   deployment history.
2. Confirm the target version does not contain the same defect.
3. Request human approval — all production rollbacks are HIGH risk actions
   and must be approved by an operator.
4. Execute `rollback_deployment(service, target_version)`.
5. Verify recovery: p95 latency, error rate and the incident-specific
   metrics must return to baseline within 5 minutes.
6. If metrics do not recover, re-open the investigation.

## After the rollback

Write an incident report including root cause, evidence, action taken and
verification results.
