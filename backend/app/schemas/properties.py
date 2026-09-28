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
from typing import Any

from pydantic import BaseModel, ConfigDict

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


def property_response(record: Any, role: Role | str) -> dict:
    """Serialise a property for `role`. Unknown roles get nothing rather than a default view."""
    view = PROPERTY_VIEW[Role(role)]
    return view.model_validate(record).model_dump()
