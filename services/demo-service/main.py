"""Demo service simulating an e-commerce payments-api.

Exposes /health, /payments/{id}, /metrics and an internal control API used
by the backend demo controller (allow-listed actions only, no shell access).

A background traffic simulator generates realistic request metrics and JSON
logs according to the active scenario profile.
"""
import asyncio
import json
import logging
import os
import random
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import yaml
from fastapi import FastAPI, HTTPException
from prometheus_client import (
    Counter, Gauge, Histogram, generate_latest, CONTENT_TYPE_LATEST,
)
from fastapi.responses import Response

SCENARIO_DIR = Path(os.environ.get(
    "SCENARIO_DIR", Path(__file__).resolve().parents[2] / "scenarios"))
LOG_FILE = Path(os.environ.get(
    "DEMO_LOG_FILE", Path(__file__).resolve().parents[2] / "run/logs/payments-api.log"))
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

SERVICE = "payments-api"

# ---------------------------------------------------------------- metrics
LABELS = {"service": SERVICE}
REQS = Counter("http_requests_total", "Total requests", ["service", "status"])
LATENCY = Histogram(
    "http_request_duration_seconds", "Request latency", ["service"],
    buckets=[.025, .05, .1, .2, .3, .5, .75, 1, 2, 3, 5, 8, 10])
ERRORS = Counter("http_request_errors_total", "5xx errors", ["service"])
DB_ACTIVE = Gauge("db_pool_active_connections", "Active DB conns", ["service"])
DB_MAX = Gauge("db_pool_max_connections", "Max DB conns", ["service"])
DB_WAITING = Gauge("db_pool_waiting_requests", "Waiting requests", ["service"])
DB_WAIT = Histogram(
    "db_pool_wait_seconds", "DB conn wait", ["service"],
    buckets=[.001, .005, .01, .05, .1, .5, 1, 2, 4, 8])
CACHE_HIT = Gauge("cache_hit_ratio", "Cache hit ratio", ["service"])
MEM = Gauge("demo_process_resident_memory_bytes", "Simulated RSS", ["service"])
RESTARTS = Counter("container_restart_count_total", "Restarts", ["service"])
DEPLOY_INFO = Gauge("deployment_info", "Deployment info", ["service", "version"])

logger = logging.getLogger("payments-api")


def log_json(level: str, message: str, **fields):
    rec = {
        "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "level": level, "service": SERVICE, "message": message, **fields,
    }
    with LOG_FILE.open("a") as f:
        f.write(json.dumps(rec) + "\n")


# ---------------------------------------------------------------- scenario state
class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.scenario = "normal"
        self.started_at = None
        self.version = "v1.7.3"
        self.profiles = self._load_profiles()
        self.mem_gb = 1.3
        self.set_version("v1.7.3")

    def _load_profiles(self):
        profiles = {}
        for p in SCENARIO_DIR.glob("*.yaml"):
            data = yaml.safe_load(p.read_text())
            profiles[data["name"]] = data
        return profiles

    def set_version(self, version):
        DEPLOY_INFO.clear()
        DEPLOY_INFO.labels(service=SERVICE, version=version).set(1)
        self.version = version

    def profile(self):
        with self.lock:
            name = self.scenario
        base = self.profiles.get(name) or self.profiles["normal"]
        return base["profile"]

    def start(self, name):
        if name not in self.profiles:
            raise KeyError(name)
        with self.lock:
            self.scenario = name
            self.started_at = time.time()
            self.mem_gb = 1.3
        prof = self.profiles[name]
        if v := prof.get("deploys_version"):
            self.set_version(v)
        log_json("INFO", f"scenario {name} activated")

    def reset(self):
        with self.lock:
            self.scenario = "normal"
            self.started_at = None
            self.mem_gb = 1.3
        self.set_version("v1.7.3")
        log_json("INFO", "environment reset to healthy state")


STATE = State()

ERROR_LOGS = {
    "db_pool_exhaustion": [
        ("ERROR", "payment failed", {"error": "timeout acquiring database connection after 2000ms"}),
        ("WARN", "db_pool saturated", {"active": 10, "max": 10, "waiting": 42}),
        ("ERROR", "payment failed", {"error": "database connection pool exhausted"}),
    ],
    "redis_failure": [
        ("WARN", "redis timeout", {"host": "redis", "port": 6379, "timeout": "500ms"}),
        ("ERROR", "cache lookup failed", {"key": "product:8821"}),
        ("WARN", "falling back to database", {}),
    ],
    "memory_leak": [
        ("WARN", "worker memory high", {"memory_usage": "6.8GB"}),
        ("WARN", "GC pause", {"duration": "820ms"}),
        ("ERROR", "worker terminated", {"reason": "OOM"}),
        ("INFO", "container restart", {"count": 3}),
    ],
}


def simulate_tick():
    prof = STATE.profile()
    scenario = STATE.scenario
    rps = prof["request_rate"]
    err_rate = prof["error_rate"]
    p50, p95 = prof["latency_p50"], prof["latency_p95"]

    # ~1s worth of traffic, sampled down for efficiency
    n = max(1, int(rps / 10))
    for _ in range(n):
        # lognormal-ish latency around p50, tail toward p95
        lat = random.choices(
            [random.gauss(p50, p50 * 0.3), random.gauss(p95, p95 * 0.2)],
            weights=[0.93, 0.07])[0]
        lat = max(0.005, lat)
        is_err = random.random() < err_rate
        status = "500" if is_err else "200"
        REQS.labels(service=SERVICE, status=status).inc(10)
        LATENCY.labels(service=SERVICE).observe(lat)
        if is_err:
            ERRORS.labels(service=SERVICE).inc(10)
        DB_WAIT.labels(service=SERVICE).observe(max(0.0005, prof["db_wait_p95"] * random.uniform(0.3, 1.1)))

    db = prof["db_pool"]
    DB_MAX.labels(service=SERVICE).set(db["max"])
    DB_ACTIVE.labels(service=SERVICE).set(
        random.randint(db["active_min"], db["active_max"]))
    DB_WAITING.labels(service=SERVICE).set(
        random.randint(db["waiting_min"], db["waiting_max"]))
    CACHE_HIT.labels(service=SERVICE).set(
        prof["cache_hit_ratio"] + random.uniform(-0.02, 0.02))

    if scenario == "memory_leak" and STATE.started_at:
        elapsed_min = (time.time() - STATE.started_at) / 60
        STATE.mem_gb = min(7.2, 1.3 + elapsed_min * 0.35)
        if STATE.mem_gb >= 7.0:
            RESTARTS.labels(service=SERVICE).inc()
            STATE.mem_gb = 1.5
    MEM.labels(service=SERVICE).set(STATE.mem_gb * 1e9)

    # error logs
    if scenario in ERROR_LOGS and random.random() < 0.7:
        level, msg, fields = random.choice(ERROR_LOGS[scenario])
        log_json(level, msg, request_id=f"{random.getrandbits(16):04x}", **fields)
    if random.random() < 0.2:
        log_json("INFO", "payment processed",
                 request_id=f"{random.getrandbits(16):04x}",
                 duration_ms=int(prof["latency_p50"] * 1000))


def simulator():
    while True:
        try:
            simulate_tick()
        except Exception as e:  # keep the loop alive
            logger.exception("simulate_tick failed: %s", e)
        time.sleep(1)


@asynccontextmanager
async def lifespan(app):
    t = threading.Thread(target=simulator, daemon=True)
    t.start()
    log_json("INFO", f"{SERVICE} started", version=STATE.version)
    yield


app = FastAPI(title="payments-api (demo)", lifespan=lifespan)


@app.get("/health")
def health():
    prof = STATE.profile()
    return {"status": "degraded" if STATE.scenario != "normal" else "ok",
            "service": SERVICE, "version": STATE.version,
            "scenario": STATE.scenario}


@app.get("/payments/{payment_id}")
async def get_payment(payment_id: str):
    prof = STATE.profile()
    await asyncio.sleep(min(2.0, prof["latency_p50"]))
    if random.random() < prof["error_rate"]:
        raise HTTPException(500, "payment lookup failed")
    return {"id": payment_id, "status": "captured", "amount_cents": 4200}


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


# ------------------------------------------------- internal control (allow-list)
@app.post("/internal/scenario/{name}/start")
def start_scenario(name: str):
    try:
        STATE.start(name)
    except KeyError:
        raise HTTPException(404, f"unknown scenario {name}")
    return {"ok": True, "scenario": name, "version": STATE.version}


@app.post("/internal/reset")
def reset():
    STATE.reset()
    return {"ok": True}


ALLOWED_ACTION_SERVICES = {"payments-api", "redis"}


@app.post("/internal/actions/restart")
def action_restart(body: dict):
    svc = body.get("service")
    if svc not in ALLOWED_ACTION_SERVICES:
        raise HTTPException(403, f"service {svc} not in allow-list")
    RESTARTS.labels(service=SERVICE).inc()
    # restart clears redis failure / memory leak symptoms
    if STATE.scenario in ("redis_failure", "memory_leak"):
        STATE.reset()
    log_json("INFO", f"service {svc} restarted by operator action")
    return {"ok": True, "action": "restart", "service": svc}


@app.post("/internal/actions/rollback")
def action_rollback(body: dict):
    svc, version = body.get("service"), body.get("target_version")
    if svc not in ALLOWED_ACTION_SERVICES:
        raise HTTPException(403, f"service {svc} not in allow-list")
    STATE.reset()
    STATE.set_version(version or "v1.7.3")
    log_json("INFO", f"rolled back {svc} to {version}")
    return {"ok": True, "action": "rollback", "service": svc, "version": version}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 9000)))
