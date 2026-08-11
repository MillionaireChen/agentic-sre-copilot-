"""Runs the LangGraph agent with Postgres checkpointing.

start_run / resume_run execute the (synchronous) graph in a worker thread so
the FastAPI event loop stays responsive. Progress is persisted as AgentEvent
rows, which both the SSE stream and the REST events endpoint read.
"""
import asyncio
from datetime import datetime, timezone

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.types import Command
from psycopg import Connection

from backend.config import settings
from backend.db.session import SessionLocal
from backend.db.models import AgentRun, AgentEvent, Approval, ToolCall, Incident
from backend.agent import graph as graph_mod

_PG_DSN = settings.database_url.replace("postgresql+psycopg://", "postgresql://")


def _emit(run_id):
    def emit(node, event_type, payload):
        with SessionLocal() as db:
            db.add(AgentEvent(run_id=run_id, node=node,
                              event_type=event_type, payload=payload))
            db.commit()
    return emit


def _tool(run_id):
    def tool(name, args, result, ms, status):
        with SessionLocal() as db:
            db.add(ToolCall(run_id=run_id, tool_name=name, arguments=args,
                            result=result if isinstance(result, dict) else {"value": result},
                            duration_ms=ms, status=status))
            db.commit()
    return tool


def _open_graph():
    conn = Connection.connect(_PG_DSN, autocommit=True)
    saver = PostgresSaver(conn)
    saver.setup()
    return graph_mod.build_graph(checkpointer=saver), conn


def _finish(run_id, status, state=None):
    with SessionLocal() as db:
        run = db.get(AgentRun, run_id)
        run.status = status
        run.finished_at = datetime.now(timezone.utc)
        if state:
            inc = db.get(Incident, run.incident_id)
            inc.root_cause = state.get("root_cause")
            inc.confidence = state.get("confidence")
            inc.final_report = state.get("final_report")
            if state.get("verification_result", {}).get("recovered"):
                inc.status = "RESOLVED"
                inc.resolved_at = datetime.now(timezone.utc)
            elif status == "COMPLETED":
                inc.status = "MITIGATION_FAILED" if state.get(
                    "approval_status") == "approved" else "ACTION_REJECTED"
            else:
                inc.status = "INVESTIGATION_FAILED"
        db.commit()


def _run_sync(run_id, resume_decision=None):
    with SessionLocal() as db:
        run = db.get(AgentRun, run_id)
        inc = db.get(Incident, run.incident_id)
        thread_id = run.thread_id
        init_state = {
            "incident_id": inc.id, "run_id": run_id, "service": inc.service,
            "severity": inc.severity, "title": inc.title,
            "start_time": inc.started_at.isoformat(),
        }
    graph_mod.set_hooks(_emit(run_id), _tool(run_id))
    graph, conn = _open_graph()
    config = {"configurable": {"thread_id": thread_id}}
    try:
        if resume_decision is None:
            _emit(run_id)(None, "agent_started", {"incident_id": init_state["incident_id"]})
            payload = init_state
        else:
            payload = Command(resume=resume_decision)
        result = graph.invoke(payload, config)
        if "__interrupt__" in result:
            # paused at the risk gate: persist the pending approval
            intr = result["__interrupt__"][0].value
            with SessionLocal() as db:
                db.add(Approval(run_id=run_id, action=intr["action"],
                                parameters=intr["parameters"], risk=intr["risk"],
                                reason=intr.get("reason"),
                                confidence=intr.get("confidence")))
                run = db.get(AgentRun, run_id)
                run.status = "AWAITING_APPROVAL"
                db.commit()
        else:
            _finish(run_id, "COMPLETED", result)
    except Exception as e:
        _emit(run_id)(None, "error", {"error": str(e)[:500]})
        _finish(run_id, "FAILED")
        raise
    finally:
        conn.close()


async def start_run(run_id: str):
    await asyncio.to_thread(_run_sync, run_id)


async def resume_run(run_id: str, decision: str):
    with SessionLocal() as db:
        run = db.get(AgentRun, run_id)
        run.status = "RUNNING"
        db.commit()
    await asyncio.to_thread(_run_sync, run_id, decision)
