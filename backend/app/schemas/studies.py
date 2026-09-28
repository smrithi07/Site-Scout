"""Catchment study requests/decisions and the per-role study response.

The study itself holds no commercial fields; the linked property goes through
`property_response`, so the Survey Manager gets the masked survey view (no rent/deposit/owner)."""
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.auth import Role
from app.schemas.properties import property_response

Mode = Literal["reuse_and_fill", "reuse_only", "full_survey"]
Level = Literal["poor", "fair", "good"]


class Anchor(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["school", "hospital", "transit", "office", "market", "temple", "other"]
    name: str | None = Field(None, max_length=120)


class LaneObservations(BaseModel):
    """Raw observations for one segment (docs/DESIGN.md §7 Lane capture). No normalisation or
    scoring on the phone — the roll-up does that. Bounds reject typos, not unusual lanes."""
    model_config = ConfigDict(extra="forbid")
    pedestrians_counted: int = Field(ge=0, le=5000)
    count_minutes: float = Field(gt=0, le=30)        # the fixed observation period actually used
    residential_units: int = Field(ge=0, le=2000)
    businesses: int = Field(ge=0, le=500)
    grocery_food_stores: int = Field(ge=0, le=100)
    anchors: list[Anchor] = []
    road_width_band: Literal["narrow", "medium", "wide"]
    pedestrian_access: Level
    vehicle_access: Level
    parking: Literal["none", "limited", "good"]


class StudyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    property_id: int
    version: int                                   # the property version the manager saw
    mode: Mode = "reuse_and_fill"
    reason: str | None = Field(None, max_length=500)   # required when mode is an override


class PlanDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int                                   # the study version the Survey Manager saw
    mode: Mode
    reason: str | None = Field(None, max_length=500)


class CancelStudy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int
    reason: str = Field(min_length=3, max_length=500)


_FIELDS = ("id", "kind", "status", "property_id", "lat", "lon", "radius_m", "segment_count", "total_length_m",
           "reuse", "requested_mode", "request_reason", "planned_mode", "plan_reason", "planned_at",
           "cancel_reason", "snapshot_id", "config_version", "created_at", "updated_at", "version")


def study_response(study: Any, prop: Any, role: Role | str, survey: dict | None = None) -> dict:
    out = {k: getattr(study, k) for k in _FIELDS}
    out["property"] = property_response(prop, role)
    out["effective_mode"] = study.planned_mode or study.requested_mode
    if survey is not None:
        out["survey"] = survey          # segments / length to survey under the effective mode
    return out
