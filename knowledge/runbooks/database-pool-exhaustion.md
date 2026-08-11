# Database Connection Pool Exhaustion

## Symptoms

API latency increases rapidly while application CPU remains within the
normal range. Common indicators include:

- `db_pool_active_connections` approaching `db_pool_max_connections`
- `db_pool_waiting_requests` > 0
- database connection acquisition timeout errors in application logs
- p95/p99 latency growth dominated by time spent waiting for a connection

## Investigation

1. Check active and maximum connection counts
   (`db_pool_active_connections` vs `db_pool_max_connections`).
2. Check connection wait time (`db_pool_wait_seconds` p95).
3. Inspect recent deployments for the affected service.
4. Compare connection pool configuration between the current and previous
   release (e.g. `DB_POOL_SIZE`).
5. Check database server health to rule out a slow database.

## Remediation

If a recent deployment changed connection pool configuration, restore the
previous configuration or roll back the deployment.

Any production rollback requires human approval.
