"""Deployment history tool (READ, no approval required)."""
from datetime import datetime, timedelta, timezone

from backend.db.session import SessionLocal
from backend.db.models import Deployment


def get_recent_deployments(service: str, since: str | None = None) -> dict:
    """List recent deployments for a service, newest first.

    `since` is an ISO timestamp; defaults to the last 24 hours.
    """
    cutoff = (datetime.fromisoformat(since.replace("Z", "+00:00")) if since
              else datetime.now(timezone.utc) - timedelta(hours=24))
    with SessionLocal() as db:
        rows = (db.query(Deployment)
                .filter(Deployment.service == service,
                        Deployment.deployed_at >= cutoff)
                .order_by(Deployment.deployed_at.desc()).all())
        return {"service": service, "deployments": [{
            "version": d.version,
            "previous_version": d.previous_version,
            "deployed_at": d.deployed_at.isoformat(),
            "commit_sha": d.commit_sha,
            "config": d.config,
            "status": d.status,
        } for d in rows]}
