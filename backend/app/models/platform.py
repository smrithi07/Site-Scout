"""Platform tables: demo users, config-version registry, audit log, jobs."""
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class User(Base):
    """Four seeded demo users (migration 0004). Tokens are HMAC-derived, never stored."""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(24))  # bd_manager | bd_executive | survey_manager | survey_executive


class ConfigVersion(Base):
    """Every config version ever loaded, with a hash of its content. A version string can never
    point at two different contents — so a snapshot's `config_version` is reproducible."""
    __tablename__ = "config_versions"

    version: Mapped[str] = mapped_column(String(32), primary_key=True)
    sha256: Mapped[str] = mapped_column(String(64))
    content: Mapped[dict] = mapped_column(JSONB)
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditEvent(Base):
    """Append-only (a DB trigger rejects UPDATE/DELETE/TRUNCATE — migration 0005). Written in the
    same transaction as the change it records, so the log can't disagree with the data."""
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_entity", "entity_type", "entity_id", "id"),
                      CheckConstraint("length(btrim(reason)) > 0", name="ck_audit_reason_required"))

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))  # NULL = system (worker)
    actor_role: Mapped[str] = mapped_column(String(24))                 # role at the time, or 'system'
    entity_type: Mapped[str] = mapped_column(String(32))
    entity_id: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(48))
    from_state: Mapped[str | None] = mapped_column(Text)
    to_state: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))


class Job(Base):
    """A unit of async work, run step by step by the worker (app/jobs). Steps persist their
    outputs, so a retry resumes from the failed step instead of starting over."""
    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_claim", "queue", "status", "run_after"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    kind: Mapped[str] = mapped_column(String(48))
    queue: Mapped[str] = mapped_column(String(24), server_default="default")
    status: Mapped[str] = mapped_column(String(16), server_default="queued")  # queued|running|succeeded|failed
    payload: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[str | None] = mapped_column(String(64))
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")  # claims since last manual retry
    current_step: Mapped[str | None] = mapped_column(String(48))
    error: Mapped[str | None] = mapped_column(Text)                     # "<step>: <message>"
    version: Mapped[int] = mapped_column(Integer, server_default="1")   # optimistic lock


class LlmCall(Base):
    """Every LLM request, successful or not: the cache (a validated response for the same fact
    sheet + provider + model + prompt version is reused), and the record of how often each model
    fails or gets rejected by the validator (docs/DESIGN.md §9)."""
    __tablename__ = "llm_calls"
    __table_args__ = (Index("ix_llm_calls_cache", "purpose", "sheet_sha256", "provider", "model", "prompt_version"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    purpose: Mapped[str] = mapped_column(String(32))            # area_narrative, …
    provider: Mapped[str] = mapped_column(String(16))
    model: Mapped[str] = mapped_column(String(64))
    prompt_version: Mapped[str] = mapped_column(String(32))
    sheet_sha256: Mapped[str] = mapped_column(String(64))
    attempt: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))             # ok | invalid | error | cached
    http_status: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    response: Mapped[dict | None] = mapped_column(JSONB)       # parsed output (ok/invalid)
    validation_errors: Mapped[list | None] = mapped_column(JSONB)
    job_id: Mapped[int | None] = mapped_column(BigInteger)      # no FK: the log outlives jobs


class JobStep(Base):
    __tablename__ = "job_steps"

    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True)
    idx: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(48))
    status: Mapped[str] = mapped_column(String(16), server_default="pending")  # pending|running|done|failed
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    output: Mapped[dict | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
