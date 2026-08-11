# Agentic SRE Incident Copilot

An autonomous SRE agent that investigates production incidents using
metrics, logs and runbooks, proposes remediation, requests human approval,
executes actions, and verifies recovery.

> **Demo problem**: *"Production payments API suddenly became very slow.
> Investigate the incident and fix it."*
>
> The agent doesn't guess — it queries Prometheus, searches Loki, inspects
> deployment history, retrieves runbooks via RAG, diagnoses the root cause
> with a confidence gate, waits for human approval on any write action,
> rolls back the bad deployment, and re-queries metrics to prove recovery.

## Architecture

```
                        Browser
                           │
                    Next.js Frontend  ── Incident Dashboard / Agent Timeline / Approval UI
                           │  REST + polling
                        FastAPI
          ┌────────────────┴────────────────┐
      LangGraph                         PostgreSQL + pgvector
          │                              (state, events, checkpoints, runbook chunks)
   ┌──────┼──────────┬─────────────┬──────────────┐
   ▼      ▼          ▼             ▼              ▼
 vLLM   Prometheus  Loki      Deployment      Runbook RAG
Qwen3    Metrics    Logs        History      (Qwen3-Embedding)
   └──────┴──────────┴──── demo payments-api (scenario-driven fault injection)
```

## Agent workflow

```
triage → planner → collect_metrics → collect_logs → check_deployment
      → retrieve_runbook → diagnose → confidence_gate
         ├─ confidence < 0.65 → re-investigate (max 2 extra rounds,
         │                      then report to a human — never act on low confidence)
         └─ confidence ≥ 0.65 → propose_remediation → risk_gate
                                   → HUMAN APPROVAL (LangGraph interrupt)
                                   → execute (allow-listed API, no shell/docker)
                                   → verify recovery from Prometheus
                                   → incident report
```

Key safety properties:

- **Read/write separation** — metrics/logs/runbook/deployment queries run
  freely; `rollback_deployment` / `restart_service` always stop at a human
  approval gate (LangGraph `interrupt` + Postgres checkpointing, resumable
  across process restarts).
- **Allow-list execution** — the agent calls a narrow internal API that only
  accepts specific services; it never gets a shell or a docker socket.
- **Verification, not declaration** — after acting, the agent re-queries
  Prometheus and compares against the pre-action baseline before declaring
  recovery; failure re-opens the investigation.

## Scenarios

| Scenario | Root cause | Expected action |
|---|---|---|
| DB pool exhaustion | v1.8.0 deploy set `DB_POOL_SIZE` 50 → 10 | rollback to v1.7.3 (HIGH risk) |
| Redis cache failure | cache hit 94% → 11%, DB overload | restart redis (MEDIUM risk) |
| Memory leak | unbounded cache in v1.8.1, OOM restarts | rollback (HIGH risk) |

Trigger any of them from the **Demo** menu in the dashboard, then click
**Investigate**.

## Real E2E result (db pool exhaustion)

```
verification: p95 4.03s → 0.20s, 5xx 8.3% → 0.25%, DB waiting 54 → 0
status: RESOLVED  (root-cause confidence 0.94)
```

## Stack

Next.js + Tailwind + Recharts · FastAPI + SQLAlchemy · LangGraph + LangChain
· vLLM (Qwen3) · Qwen3-Embedding-0.6B + pgvector · Prometheus + Loki +
Grafana Alloy · MinerU for PDF/Office knowledge extraction

## Running (docker-free deployment)

This repo is deployed on a shared GPU server **without docker or sudo** —
every service runs as a user-space process. See
[docs/DEPLOYMENT_NOTES.md](docs/DEPLOYMENT_NOTES.md) for the full setup and
the pitfalls encountered (NFS vs local disk, PromQL rate-window pollution in
verification, Qwen3 `<think>` stripping, Blackwell cu128 wheels, ...).

```bash
make up        # start postgres, prometheus, loki, alloy, demo-service, api, frontend
make ingest    # embed runbooks into pgvector
make vllm      # start Qwen3 on GPU0 (LLM_MODEL env var switches 8B/32B)
make test      # unit tests (mock LLM, 9 tests)
make eval      # end-to-end scenario evaluation
```

- Dashboard: http://localhost:3000
- API: http://localhost:8000
- Prometheus: http://localhost:9090

## Evaluation

`eval/run_eval.py` injects each scenario, lets the agent investigate,
auto-approves only allowed actions, and scores:
Root Cause Accuracy · Evidence Recall · Correct Tool Selection ·
Unsafe Action Rate · Recovery Success Rate.
