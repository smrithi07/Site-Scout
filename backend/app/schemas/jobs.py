from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class JobStepOut(_Out):
    idx: int
    name: str
    status: str
    attempts: int
    output: dict | None
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None


class JobOut(_Out):
    id: int
    kind: str
    status: str
    current_step: str | None
    error: str | None           # "<failed step>: <message>" — the UI names the failed step
    attempts: int
    created_by: int | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    heartbeat_at: datetime | None
    version: int
    steps: list[JobStepOut]


class RetryIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)
    version: int | None = None  # optimistic lock: the job version the client last saw


class SelftestIn(BaseModel):
    fail_at: str | None = Field(None, pattern="^(prepare|compute|save)$")
    fail_times: int = Field(1, ge=0, le=5)


class AuditEventOut(_Out):
    id: int
    at: datetime
    actor_id: int | None
    actor_role: str
    entity_type: str
    entity_id: str
    action: str
    from_state: str | None
    to_state: str | None
    reason: str
    details: dict
