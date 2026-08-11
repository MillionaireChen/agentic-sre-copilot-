# High API Latency — General Triage

## First 5 minutes

1. Quantify the impact: p50/p95/p99 latency and 5xx rate for the service.
2. Establish the start time of the degradation from metrics.
3. Check whether a deployment happened shortly before the start time —
   deployments are the most common cause of sudden latency regressions.

## Common causes and their signatures

| Cause | Signature |
|---|---|
| DB pool exhaustion | pool at max, waiting requests > 0, acquisition timeouts |
| Cache failure | cache hit ratio collapse, DB query rate spike |
| Memory pressure | RSS growth, GC pauses, OOM restarts |
| Downstream dependency | timeouts to a specific upstream in logs |
| Traffic surge | request rate far above baseline |

## Escalation

If the root cause maps to a recent deployment and impact is SEV-1,
prefer rollback over forward-fix. Rollback requires human approval.
