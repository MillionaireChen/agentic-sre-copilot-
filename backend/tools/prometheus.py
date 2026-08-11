"""Prometheus query tool (READ, no approval required)."""
import httpx

from backend.config import settings


def query_prometheus(query: str, start_time: str | None = None,
                     end_time: str | None = None, step: str | None = None) -> dict:
    """Run an instant or range PromQL query. Times are RFC3339 or unix ts."""
    with httpx.Client(timeout=15) as client:
        if start_time and end_time:
            r = client.get(f"{settings.prometheus_url}/api/v1/query_range", params={
                "query": query, "start": start_time, "end": end_time,
                "step": step or "30s"})
        else:
            r = client.get(f"{settings.prometheus_url}/api/v1/query",
                           params={"query": query})
    r.raise_for_status()
    data = r.json()
    if data.get("status") != "success":
        return {"error": data}
    result = data["data"]["result"]
    # compact the result for LLM consumption
    out = []
    for series in result[:20]:
        entry = {"metric": series["metric"]}
        if "value" in series:
            entry["value"] = series["value"][1]
        else:
            vals = series.get("values", [])
            # subsample long ranges
            if len(vals) > 30:
                stride = len(vals) // 30
                vals = vals[::stride]
            entry["values"] = [[v[0], v[1]] for v in vals]
        out.append(entry)
    return {"resultType": data["data"]["resultType"], "result": out}
