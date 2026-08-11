"""Loki log query tool (READ, no approval required)."""
import json
import time

import httpx

from backend.config import settings


def query_logs(service: str, query: str = "", start_time: str | None = None,
               end_time: str | None = None, limit: int = 100) -> dict:
    """Query Loki for logs of a service.

    `query` is an optional LogQL filter suffix, e.g. '|= "ERROR"' or
    '| json | level="ERROR"'. Base selector is {service="<service>"}.
    """
    logql = f'{{service="{service}"}} {query}'.strip()
    now_ns = int(time.time() * 1e9)
    params = {
        "query": logql,
        "limit": str(min(limit, 200)),
        "start": start_time or str(now_ns - int(3600 * 1e9)),
        "end": end_time or str(now_ns),
        "direction": "backward",
    }
    with httpx.Client(timeout=15) as client:
        r = client.get(f"{settings.loki_url}/loki/api/v1/query_range", params=params)
    r.raise_for_status()
    data = r.json()
    lines = []
    for stream in data.get("data", {}).get("result", []):
        for ts, line in stream.get("values", []):
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                parsed = {"raw": line}
            lines.append(parsed)
    lines.sort(key=lambda x: x.get("ts", ""), reverse=True)
    return {"query": logql, "count": len(lines), "logs": lines[:limit]}
