import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import httpx
import yaml
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
from sse_starlette.sse import EventSourceResponse

from backend.config import settings
from backend.db.session import SessionLocal, init_db
from backend.db.models import (
    Incident, AgentRun, AgentEvent, Approval, Deployment,
)

SCENARIO_DIR = Path(__file__).resolve().parents[2] / "scenarios"

SCENARIO_ROUTES = {
    "db-pool": "db_pool_exhaustion",
    "redis": "redis_failure",
    "memory-leak": "memory_leak",
}

SCENARIO_INCIDENTS = {
    "db_pool_exhaustion": ("payments-api latency degraded", "SEV-1"),
    "redis_failure": ("payments-api cache hit ratio collapsed", "SEV-2"),
    "memory_leak": ("payments-api memory growth / OOM restarts", "SEV-2"),
}


@asynccontextmanager
async def lifespan(app):
    init_db()
    _seed_baseline_deployment()
    yield


def _seed_baseline_deployment():
    with SessionLocal() as db:
        if not db.query(Deployment).filter_by(service="payments-api").count():
            db.add(Deployment(
                service="payments-api", version="v1.7.3",
                previous_version="v1.6.9", commit_sha="1b02c44",
                deployed_at=datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc),
                config={"DB_POOL_SIZE": 50}))
            db.commit()


app = FastAPI(title="Agentic SRE Copilot API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def _incident_dict(i: Incident):
    return {
        "id": i.id, "title": i.title, "service": i.service,
        "severity": i.severity, "status": i.status,
        "started_at": i.started_at.isoformat() if i.started_at else None,
        "resolved_at": i.resolved_at.isoformat() if i.resolved_at else None,
        "root_cause": i.root_cause, "confidence": i.confidence,
        "scenario": i.scenario, "final_report": i.final_report,
    }


# --------------------------------------------------------------- incidents
@app.get("/api/incidents")
def list_incidents():
    with SessionLocal() as db:
        rows = db.query(Incident).order_by(Incident.started_at.desc()).all()
        return [_incident_dict(i) for i in rows]


@app.get("/api/incidents/{incident_id}")
def get_incident(incident_id: str):
    with SessionLocal() as db:
        i = db.get(Incident, incident_id)
        if not i:
            raise HTTPException(404)
        runs = db.query(AgentRun).filter_by(incident_id=incident_id).order_by(
            AgentRun.started_at.desc()).all()
        d = _incident_dict(i)
        d["runs"] = [{"id": r.id, "status": r.status,
                      "started_at": r.started_at.isoformat()} for r in runs]
        return d


@app.post("/api/incidents/{incident_id}/investigate")
async def investigate(incident_id: str):
    from backend.agent.runner import start_run
    with SessionLocal() as db:
        i = db.get(Incident, incident_id)
        if not i:
            raise HTTPException(404)
        run = AgentRun(incident_id=incident_id, thread_id=uuid.uuid4().hex)
        i.status = "INVESTIGATING"
        db.add(run)
        db.commit()
        run_id = run.id
    asyncio.create_task(start_run(run_id))
    return {"run_id": run_id}


# --------------------------------------------------------------- runs / SSE
@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    with SessionLocal() as db:
        r = db.get(AgentRun, run_id)
        if not r:
            raise HTTPException(404)
        return {"id": r.id, "incident_id": r.incident_id, "status": r.status,
                "started_at": r.started_at.isoformat(),
                "finished_at": r.finished_at.isoformat() if r.finished_at else None}


@app.get("/api/runs/{run_id}/events")
def get_events(run_id: str, after: int = 0):
    with SessionLocal() as db:
        rows = db.query(AgentEvent).filter(
            AgentEvent.run_id == run_id, AgentEvent.id > after
        ).order_by(AgentEvent.id).all()
        return [{"id": e.id, "node": e.node, "type": e.event_type,
                 "payload": e.payload, "created_at": e.created_at.isoformat()}
                for e in rows]


@app.get("/api/runs/{run_id}/stream")
async def stream_run(run_id: str):
    async def gen():
        last_id = 0
        while True:
            with SessionLocal() as db:
                rows = db.query(AgentEvent).filter(
                    AgentEvent.run_id == run_id, AgentEvent.id > last_id
                ).order_by(AgentEvent.id).all()
                run = db.get(AgentRun, run_id)
            for e in rows:
                last_id = e.id
                yield {"event": e.event_type,
                       "data": json.dumps({"id": e.id, "node": e.node,
                                           "type": e.event_type,
                                           "payload": e.payload,
                                           "created_at": e.created_at.isoformat()})}
            if run and run.status in ("COMPLETED", "FAILED") and not rows:
                yield {"event": "stream_end", "data": "{}"}
                return
            await asyncio.sleep(0.5)
    return EventSourceResponse(gen())


# --------------------------------------------------------------- approval
@app.post("/api/runs/{run_id}/approval")
async def decide_approval(run_id: str, body: dict):
    decision = body.get("decision")
    if decision not in ("approve", "reject"):
        raise HTTPException(400, "decision must be approve|reject")
    from backend.agent.runner import resume_run
    with SessionLocal() as db:
        appr = db.query(Approval).filter_by(run_id=run_id, decision=None).order_by(
            Approval.id.desc()).first()
        if not appr:
            raise HTTPException(404, "no pending approval")
        appr.decision = decision
        appr.decided_by = body.get("decided_by", "operator")
        appr.decided_at = datetime.now(timezone.utc)
        db.commit()
    asyncio.create_task(resume_run(run_id, decision))
    return {"ok": True, "decision": decision}


# --------------------------------------------------------------- demo control
@app.post("/api/demo/scenarios/{key}/start")
async def start_scenario(key: str):
    name = SCENARIO_ROUTES.get(key)
    if not name:
        raise HTTPException(404, f"unknown scenario {key}")
    async with httpx.AsyncClient() as client:
        r = await client.post(f"{settings.demo_service_url}/internal/scenario/{name}/start")
        r.raise_for_status()

    spec = yaml.safe_load((SCENARIO_DIR / f"{name}.yaml").read_text())
    with SessionLocal() as db:
        if dep := spec.get("deployment"):
            db.add(Deployment(
                service=dep["service"], version=dep["current_version"],
                previous_version=dep["previous_version"],
                commit_sha=dep.get("commit_sha"),
                deployed_at=datetime.now(timezone.utc),
                config={k: v["after"] for k, v in dep.get("changes", {}).items()},
            ))
        title, sev = SCENARIO_INCIDENTS[name]
        inc = Incident(title=title, service="payments-api",
                       severity=sev, scenario=name)
        db.add(inc)
        db.commit()
        return {"ok": True, "incident_id": inc.id, "scenario": name}


@app.post("/api/demo/reset")
async def demo_reset():
    async with httpx.AsyncClient() as client:
        r = await client.post(f"{settings.demo_service_url}/internal/reset")
        r.raise_for_status()
    with SessionLocal() as db:
        for i in db.query(Incident).filter(Incident.status != "RESOLVED"):
            i.status = "CLOSED"
        db.commit()
    return {"ok": True}


@app.get("/api/metrics/timeseries")
def metrics_timeseries(kind: str = "p95", minutes: int = 30):
    """Small proxy for the dashboard charts."""
    import time as _t
    from backend.tools.prometheus import query_prometheus
    svc = "payments-api"
    queries = {
        "p95": 'histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{service="%s"}[2m])) by (le))' % svc,
        "error_rate": 'sum(rate(http_request_errors_total{service="%s"}[2m])) / sum(rate(http_requests_total{service="%s"}[2m]))' % (svc, svc),
        "db_waiting": 'db_pool_waiting_requests{service="%s"}' % svc,
    }
    q = queries.get(kind)
    if not q:
        raise HTTPException(400, f"kind must be one of {list(queries)}")
    end = int(_t.time())
    out = query_prometheus(q, start_time=str(end - minutes * 60),
                           end_time=str(end), step="15s")
    series = out.get("result", [])
    points = series[0].get("values", []) if series else []
    return {"kind": kind,
            "points": [{"t": int(float(t)), "v": float(v)} for t, v in points]}


@app.get("/health")
def health():
    return {"status": "ok"}
