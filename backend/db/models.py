import uuid
from datetime import datetime, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON, DateTime, Float, ForeignKey, Integer, String, Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now():
    return datetime.now(timezone.utc)


def gen_id(prefix):
    return lambda: f"{prefix}-{uuid.uuid4().hex[:12]}"


class Base(DeclarativeBase):
    pass


class Incident(Base):
    __tablename__ = "incidents"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_id("INC"))
    title: Mapped[str] = mapped_column(String)
    service: Mapped[str] = mapped_column(String)
    severity: Mapped[str] = mapped_column(String, default="SEV-1")
    status: Mapped[str] = mapped_column(String, default="OPEN")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    root_cause: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    scenario: Mapped[str | None] = mapped_column(String, nullable=True)
    final_report: Mapped[str | None] = mapped_column(Text, nullable=True)


class AgentRun(Base):
    __tablename__ = "agent_runs"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_id("RUN"))
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"))
    thread_id: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="RUNNING")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentEvent(Base):
    __tablename__ = "agent_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id"))
    node: Mapped[str | None] = mapped_column(String, nullable=True)
    event_type: Mapped[str] = mapped_column(String)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ToolCall(Base):
    __tablename__ = "tool_calls"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id"))
    tool_name: Mapped[str] = mapped_column(String)
    arguments: Mapped[dict] = mapped_column(JSONB, default=dict)
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String, default="ok")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Approval(Base):
    __tablename__ = "approvals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id"))
    action: Mapped[str] = mapped_column(String)
    parameters: Mapped[dict] = mapped_column(JSONB, default=dict)
    risk: Mapped[str] = mapped_column(String)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    decision: Mapped[str | None] = mapped_column(String, nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Action(Base):
    __tablename__ = "actions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id"))
    action: Mapped[str] = mapped_column(String)
    parameters: Mapped[dict] = mapped_column(JSONB, default=dict)
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String, default="pending")
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Deployment(Base):
    __tablename__ = "deployments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    service: Mapped[str] = mapped_column(String)
    version: Mapped[str] = mapped_column(String)
    previous_version: Mapped[str | None] = mapped_column(String, nullable=True)
    deployed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    commit_sha: Mapped[str | None] = mapped_column(String, nullable=True)
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String, default="active")


class RunbookChunk(Base):
    __tablename__ = "runbook_chunks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_name: Mapped[str] = mapped_column(String)
    section: Mapped[str | None] = mapped_column(String, nullable=True)
    content: Mapped[str] = mapped_column(Text)
    embedding = mapped_column(Vector(1024))
    meta: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
