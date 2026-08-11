# Redis Outage / Cache Degradation

## Symptoms

- `cache_hit_ratio` drops sharply (healthy baseline is above 90%)
- database query rate increases several-fold as requests fall back to the DB
- API latency increases while error rate may stay moderate
- logs contain redis timeout or connection refused errors

## Investigation

1. Check `cache_hit_ratio` trend over the incident window.
2. Check database query rate and DB pool utilization for fallback pressure.
3. Search logs for `redis timeout`, `cache lookup failed`,
   `falling back to database`.
4. Verify whether redis itself restarted, was redeployed, or is network
   partitioned.

## Remediation

- If redis is unresponsive, restart the redis service (requires approval).
- If a config change broke connectivity, revert the change.
- Consider enabling request shedding if the database saturates before
  cache recovery.
