from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=3, max_length=120)
    assignee_id: int
    note: str | None = Field(None, max_length=1000)
    due_date: date | None = None
    source_report_id: int | None = None
    target_cells: list[str] = []          # res-8 cells; optional when hotspots are given
    hotspot_cells: list[str] = []         # res-9 hotspot cells from the source report


class TaskUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int
    status: Literal["open", "in_progress", "done", "cancelled"] | None = None
    assignee_id: int | None = None
    reason: str = Field(min_length=3, max_length=500)


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    note: str | None
    assignee_id: int
    created_by: int
    status: str
    due_date: date | None
    source_report_id: int | None
    target_cells: list[str]
    hotspot_cells: list[str]
    created_at: datetime
    updated_at: datetime
    version: int
