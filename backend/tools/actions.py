"""WRITE action tools — every function here requires human approval.

Actions are executed via the demo controller's allow-listed HTTP API.
The agent never gets shell access or a docker socket.
"""
from datetime import datetime, timezone

import httpx

from backend.config import settings
from backend.db.session import SessionLocal
from backend.db.models import Deployment

ALLOWED_SERVICES = {"payments-api", "redis"}


def restart_service(service: str) -> dict:
    if service not in ALLOWED_SERVICES:
        return {"error": f"service {service} not in allow-list"}
    with httpx.Client(timeout=15) as client:
        r = client.post(f"{settings.demo_service_url}/internal/actions/restart",
                        json={"service": service})
    return r.json()


def rollback_deployment(service: str, target_version: str) -> dict:
    if service not in ALLOWED_SERVICES:
        return {"error": f"service {service} not in allow-list"}
    with httpx.Client(timeout=15) as client:
        r = client.post(f"{settings.demo_service_url}/internal/actions/rollback",
                        json={"service": service, "target_version": target_version})
    result = r.json()
    if result.get("ok"):
        with SessionLocal() as db:
            latest = (db.query(Deployment).filter_by(service=service)
                      .order_by(Deployment.deployed_at.desc()).first())
            db.add(Deployment(
                service=service, version=target_version,
                previous_version=latest.version if latest else None,
                deployed_at=datetime.now(timezone.utc),
                commit_sha="rollback", status="active",
                config={"rollback_of": latest.version if latest else None}))
            db.commit()
    return result


WRITE_TOOLS = {"restart_service", "rollback_deployment", "change_configuration"}
