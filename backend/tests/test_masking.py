"""Phase 3a checkpoint: a masked field never appears in a disallowed role's response."""
import json

import pytest

from app.core.auth import Role
from app.schemas.properties import BD_ONLY_FIELDS, PROPERTY_VIEW, property_response

# A property record carrying every field, plus one the schemas have never heard of. Sensitive
# values are distinctive strings/numbers so a leak is caught even under a different key.
FULL_RECORD = {
    "id": 7, "label": "Corner shop, 4th Main Rd", "lat": 13.0418, "lon": 80.2341,
    "address": "12 4th Main Rd", "landmark": "near temple", "access_notes": "gate closes 9pm",
    "locality": "T Nagar", "pincode": "600017", "ward_no": 133, "stage": "Shortlisted",
    "created_by": 2, "gps_accuracy_m": 8.0, "nearby_road": "Usman Rd",
    "monthly_rent": 87654.0, "rent_unit": "per_month", "area_sqft": 1234.0, "security_deposit": 543210.0,
    "availability": "immediate", "frontage_ft": 18.0, "road_width_ft": 30.0, "floor": "ground",
    "visibility": "good", "accessibility": "fair", "parking": "limited", "condition": "good",
    "owner_name": "OWNER-NAME-SENTINEL", "owner_phone": "+91-99999-00000", "version": 3,
    "future_secret_field": "NEW-FIELD-SENTINEL",
}
SENSITIVE_VALUES = ["87654", "543210", "OWNER-NAME-SENTINEL", "99999-00000", "per_month", "immediate"]


@pytest.mark.parametrize("role", [Role.SURVEY_MANAGER, Role.SURVEY_EXECUTIVE])
def test_non_bd_roles_never_see_commercial_or_contact_fields(role):
    out = property_response(FULL_RECORD, role)
    assert not BD_ONLY_FIELDS & out.keys()
    blob = json.dumps(out)
    for value in SENSITIVE_VALUES:
        assert value not in blob, (role, value)


def test_survey_executive_sees_label_only():
    assert property_response(FULL_RECORD, Role.SURVEY_EXECUTIVE) == {"id": 7, "label": "Corner shop, 4th Main Rd"}


def test_survey_manager_sees_operational_fields():
    out = property_response(FULL_RECORD, Role.SURVEY_MANAGER)
    assert out["address"] == "12 4th Main Rd" and out["access_notes"] == "gate closes 9pm"


@pytest.mark.parametrize("role", [Role.BD_MANAGER, Role.BD_EXECUTIVE])
def test_bd_roles_see_commercial_fields(role):
    out = property_response(FULL_RECORD, role)
    assert out["monthly_rent"] == 87654.0 and out["owner_name"] == "OWNER-NAME-SENTINEL"


@pytest.mark.parametrize("role", list(Role))
def test_unknown_fields_are_never_echoed(role):
    # Allow-list: a field added to the record later is invisible until a view opts in.
    assert "NEW-FIELD-SENTINEL" not in json.dumps(property_response(FULL_RECORD, role))


def test_bd_only_fields_are_exactly_the_fields_survey_views_lack():
    # Keeps the stated policy (BD_ONLY_FIELDS) and the per-role models from drifting apart.
    bd = set(PROPERTY_VIEW[Role.BD_MANAGER].model_fields)
    survey = set(PROPERTY_VIEW[Role.SURVEY_MANAGER].model_fields)
    assert BD_ONLY_FIELDS <= bd and not BD_ONLY_FIELDS & survey


def test_every_role_has_a_view_and_bad_roles_get_nothing():
    assert set(PROPERTY_VIEW) == set(Role)
    with pytest.raises(ValueError):
        property_response(FULL_RECORD, "admin")
