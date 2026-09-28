"""Per-role property responses (docs/DESIGN.md §4, §6). THE place field masking happens.

Each role gets its own response model listing exactly the fields it may see — an allow-list, so a
field added to the property record later is invisible to every role until someone deliberately
adds it to that role's model. Routers must return `property_response(record, role)`, never the
record itself.

- BD Manager / BD Executive: everything, including commercial fields (rent, deposit) and the
  owner/broker contact.
- Survey Manager: location, study scope and operational notes — never commercial or contact fields.
- Survey Executive: a label only; the property is just a name on their unit list.
"""
from datetime import datetime
from typing import Any, Literal

from pydantic import UUID4, BaseModel, ConfigDict, Field, model_validator

from app.core.auth import Role


class _Out(BaseModel):
    # from_attributes: builders accept ORM rows or dicts. extra="ignore": unknown input keys are
    # dropped, never echoed.
    model_config = ConfigDict(from_attributes=True, extra="ignore")


class PropertyLabel(_Out):
    """Survey Executive."""
    id: int
    label: str


class PropertySurveyView(PropertyLabel):
    """Survey Manager: where it is and how to get a team there — nothing commercial."""
    lat: float
    lon: float
    address: str | None = None
    landmark: str | None = None
    access_notes: str | None = None
    locality: str | None = None
    pincode: str | None = None
    ward_no: int | None = None
    stage: str | None = None


class PropertyBDView(PropertySurveyView):
    """BD Manager / BD Executive (executives additionally limited to their own properties by
    ownership checks in the service layer — masking is about fields, not rows)."""
    created_by: int | None = None
    created_at: datetime | None = None
    gps_accuracy_m: float | None = None
    nearby_road: str | None = None
    # commercial — BD only
    monthly_rent: float | None = None
    rent_unit: str | None = None
    area_sqft: float | None = None
    security_deposit: float | None = None
    availability: str | None = None
    # physical
    frontage_ft: float | None = None
    road_width_ft: float | None = None
    floor: str | None = None
    # executive assessment (provenance: observed, self-reported)
    visibility: str | None = None
    accessibility: str | None = None
    parking: str | None = None
    condition: str | None = None
    # contact — BD only
    owner_name: str | None = None
    owner_phone: str | None = None
    # workflow (BD only)
    task_id: int | None = None
    zone_no: int | None = None
    status: str | None = None
    duplicate_of: int | None = None
    duplicate_candidates: list = []
    warnings: list = []
    missing_fields: list = []
    evaluation_status: str | None = None
    updated_at: datetime | None = None
    version: int | None = None


PROPERTY_VIEW: dict[Role, type[PropertyLabel]] = {
    Role.BD_MANAGER: PropertyBDView,
    Role.BD_EXECUTIVE: PropertyBDView,
    Role.SURVEY_MANAGER: PropertySurveyView,
    Role.SURVEY_EXECUTIVE: PropertyLabel,
}

# Fields that must never reach a non-BD role. Checked by tests against the models above, so the
# allow-lists and this statement of intent can't drift apart silently.
BD_ONLY_FIELDS = frozenset({"monthly_rent", "rent_unit", "security_deposit", "area_sqft", "availability",
                            "owner_name", "owner_phone"})


Level = Literal["poor", "fair", "good"]


class PropertyFields(BaseModel):
    """Editable fields of the property form (docs/DESIGN.md §6). Everything but the pin is optional:
    a missing field is recorded as missing, never guessed (the recommendation becomes Needs Info)."""
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=2, max_length=120)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    gps_accuracy_m: float | None = Field(None, ge=0)
    device_lat: float | None = Field(None, ge=-90, le=90)
    device_lon: float | None = Field(None, ge=-180, le=180)
    address: str | None = Field(None, max_length=300)
    landmark: str | None = Field(None, max_length=200)
    access_notes: str | None = Field(None, max_length=500)
    nearby_road: str | None = Field(None, max_length=200)
    locality: str | None = Field(None, max_length=120)
    monthly_rent: float | None = Field(None, ge=0)          # negative → 422
    rent_unit: Literal["per_month", "per_sqft_month"] | None = None
    area_sqft: float | None = Field(None, gt=0, le=100_000)
    security_deposit: float | None = Field(None, ge=0)
    availability: str | None = Field(None, max_length=120)
    frontage_ft: float | None = Field(None, gt=0, le=500)
    road_width_ft: float | None = Field(None, gt=0, le=300)
    floor: Literal["basement", "ground", "first", "upper"] | None = None
    visibility: Level | None = None
    accessibility: Level | None = None
    parking: Literal["none", "limited", "good"] | None = None
    condition: Level | None = None
    owner_name: str | None = Field(None, max_length=120)
    owner_phone: str | None = Field(None, max_length=32)

    @model_validator(mode="after")
    def _rent_needs_unit(self):
        if self.monthly_rent is not None and self.rent_unit is None:
            raise ValueError("rent_unit is required when monthly_rent is given (per_month or per_sqft_month)")
        return self


class PropertyCreate(PropertyFields):
    client_id: UUID4                  # generated on the phone; a retried submit is a no-op
    task_id: int | None = None


class PropertyUpdate(BaseModel):
    """Partial edit. `version` is the one the client last saw (optimistic lock)."""
    model_config = ConfigDict(extra="forbid")

    version: int
    changes: dict  # validated against PropertyFields in the service (partial)


class DuplicateResolution(BaseModel):
    choice: Literal["same", "different"]
    target_id: int | None = None      # required for "same": the property this one duplicates


class NoteIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class StageMove(BaseModel):
    to: str
    reason: str = Field(min_length=3, max_length=500)   # every move needs a reason (audited)
    version: int                                        # optimistic lock


class FollowUpIn(BaseModel):
    kind: Literal["photos", "revisit", "rent_check", "other"]
    message: str = Field(min_length=3, max_length=1000)
    version: int


class FollowUpResponse(BaseModel):
    response: str = Field(min_length=3, max_length=2000)


def property_response(record: Any, role: Role | str) -> dict:
    """Serialise a property for `role`. Unknown roles get nothing rather than a default view."""
    view = PROPERTY_VIEW[Role(role)]
    return view.model_validate(record).model_dump()
