"""Scouted properties (docs/DESIGN.md §6): save first, validate, detect duplicates, never merge or
block silently. Rejections (outside GCC, (0,0), in water, negative money) stop the save; everything
else is saved with warnings and a list of missing fields."""
import math
import uuid
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from app.core import audit
from app.core.auth import Role
from app.core.config import load_config
from app.core.errors import Conflict, Forbidden, NotFound, Unprocessable
from app.core.locking import update_versioned
from app.core.settings import get_settings
from app.models import Property, PropertyNote, PropertyPhoto, ScoutTask, User
from app.schemas.properties import PropertyCreate, PropertyFields
from app.services.locate import point_context


def _metres(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dlat, dlon = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return 6_371_000 * 2 * math.asin(math.sqrt(a))


def rent_per_sqft(p) -> float | None:
    if p.monthly_rent is None or not p.monthly_rent:
        return None
    if p.rent_unit == "per_sqft_month":
        return p.monthly_rent
    return p.monthly_rent / p.area_sqft if p.area_sqft else None


def assess(db: Session, fields) -> tuple[dict, list[dict], list[str]]:
    """(location context, warnings, missing fields). Raises Unprocessable for bad pins."""
    cfg = load_config()["properties"]
    if abs(fields.lat) < 1e-6 and abs(fields.lon) < 1e-6:
        raise Unprocessable("The pin is at (0, 0) — the phone didn't get a location. Drop the pin on the map.")
    ctx = point_context(db, fields.lat, fields.lon)
    if not ctx["in_service_area"]:
        raise Unprocessable("The pin is outside the service area (Greater Chennai Corporation).")
    if ctx["in_landuse"]:
        raise Unprocessable(f"The pin is in {ctx['in_landuse']} — move it onto the property.")

    warnings: list[dict] = []
    if fields.gps_accuracy_m is not None and fields.gps_accuracy_m > cfg["max_gps_accuracy_m"]:
        warnings.append({"code": "gps_poor", "message": f"GPS accuracy is {fields.gps_accuracy_m:.0f} m "
                         f"(limit {cfg['max_gps_accuracy_m']} m) — check the pin on the map."})
    if fields.device_lat is not None and fields.device_lon is not None:
        d = _metres(fields.lat, fields.lon, fields.device_lat, fields.device_lon)
        if d > cfg["max_distance_from_executive_m"]:
            warnings.append({"code": "far_from_executive", "message": f"The pin is {d / 1000:.1f} km from where you "
                             "were when saving — was it placed from memory?"})
    if fields.monthly_rent == 0:
        warnings.append({"code": "rent_zero", "message": "Rent recorded as 0 — treated as unknown until confirmed."})
    per_sqft, band = rent_per_sqft(fields), ctx["rent_band"]
    if per_sqft is not None:
        lo, hi = band["min"] * cfg["rent_outlier_factor"]["low"], band["max"] * cfg["rent_outlier_factor"]["high"]
        if not lo <= per_sqft <= hi:
            warnings.append({"code": "rent_outlier", "message": f"Rent works out to ₹{per_sqft:.0f}/sq ft/month, far "
                             f"outside the {band['label']} band for this zone (₹{band['min']}–{band['max']}). "
                             "Check the amount and unit."})
    missing = [f for f in cfg["critical_fields"] if getattr(fields, f) in (None, 0)]
    return ctx, warnings, missing


def _duplicates(db: Session, p: Property) -> list[dict]:
    cfg = load_config()["properties"]
    rows = db.execute(text("""
        SELECT id, label, created_by, round(ST_Distance(geom::geography, CAST(:g AS geography))::numeric, 1) AS distance_m,
               round(similarity(lower(label), lower(:label))::numeric, 2) AS similarity
        FROM properties
        WHERE id <> :id AND status <> 'merged'
          AND ST_DWithin(geom::geography, CAST(:g AS geography), :r)
          AND similarity(lower(label), lower(:label)) >= :sim
        ORDER BY distance_m LIMIT 5"""),
        dict(id=p.id, g=f"SRID=4326;POINT({p.lon} {p.lat})", label=p.label, r=cfg["duplicate_radius_m"],
             sim=cfg["duplicate_name_similarity"])).mappings().all()
    return [{k: (float(v) if k in ("distance_m", "similarity") else v) for k, v in r.items()} for r in rows]


def visible(db: Session, user: User, property_id: int) -> Property:
    """Row-level access: BD Manager sees all; BD Executive sees their own. Survey roles reach
    properties only through studies (M3), with their own masked views."""
    p = db.get(Property, property_id)
    if p is None:
        raise NotFound(f"property {property_id} not found")
    if user.role == Role.BD_MANAGER or (user.role == Role.BD_EXECUTIVE and p.created_by == user.id):
        return p
    raise Forbidden("You can only see properties you onboarded")


def list_for(db: Session, user: User, task_id: int | None = None, stage: str | None = None) -> list[Property]:
    q = select(Property).where(Property.status != "merged").order_by(Property.id.desc())
    if user.role == Role.BD_EXECUTIVE:
        q = q.where(Property.created_by == user.id)
    elif user.role != Role.BD_MANAGER:
        return []
    if task_id:
        q = q.where(Property.task_id == task_id)
    if stage:
        q = q.where(Property.stage == stage)
    return list(db.scalars(q))


def create(db: Session, actor: User, data: PropertyCreate) -> tuple[Property, bool]:
    """Returns (property, created). A repeated client_id returns the existing row (idempotent)."""
    existing = db.scalar(select(Property).where(Property.client_id == str(data.client_id)))
    if existing:
        if existing.created_by != actor.id:
            raise Conflict("That client_id belongs to another user's submission")
        return existing, False
    if data.task_id:
        task = db.get(ScoutTask, data.task_id)
        if task is None or (actor.role == Role.BD_EXECUTIVE and task.assignee_id != actor.id):
            raise Forbidden("That scout task isn't assigned to you")
    ctx, warnings, missing = assess(db, data)
    fields = data.model_dump(exclude={"client_id", "locality"})
    p = Property(client_id=str(data.client_id), created_by=actor.id, **fields,
                 locality=data.locality or ctx["locality"], pincode=ctx["pincode"], ward_no=ctx["ward_no"],
                 zone_no=ctx["zone_no"], warnings=warnings, missing_fields=[*missing, "photos"],
                 geom=f"SRID=4326;POINT({data.lon} {data.lat})")
    db.add(p)
    db.flush()
    dups = _duplicates(db, p)
    if dups:
        p.status, p.duplicate_candidates = "possible_duplicate", dups
        p.warnings = [*warnings, {"code": "possible_duplicate", "message": f"{len(dups)} existing propert"
                                  f"{'y' if len(dups) == 1 else 'ies'} within {load_config()['properties']['duplicate_radius_m']} m "
                                  "with a similar name. Choose: same property (add your notes) or different property."}]
    audit.record(db, actor=actor, entity_type="property", entity_id=p.id, action="created", to_state=p.status,
                 reason="onboarded" + (f" under task {data.task_id}" if data.task_id else ""),
                 details={"warnings": [w["code"] for w in p.warnings], "missing": p.missing_fields,
                          "duplicate_candidates": [d["id"] for d in dups]})
    if data.task_id:
        task = db.get(ScoutTask, data.task_id)
        if task.status == "open":
            update_versioned(db, ScoutTask, task.id, task.version, status="in_progress", updated_at=text("now()"))
            audit.record(db, actor=actor, entity_type="scout_task", entity_id=task.id, action="status_changed",
                         from_state="open", to_state="in_progress", reason=f"first property onboarded (#{p.id})")
    db.flush()
    return p, True


def update_fields(db: Session, actor: User, property_id: int, version: int, changes: dict) -> Property:
    p = visible(db, actor, property_id)
    if p.status == "merged":
        raise Conflict("This entry was merged into another property; edit that one instead")
    current = {k: getattr(p, k) for k in PropertyFields.model_fields}
    try:
        merged = PropertyFields(**{**current, **changes})
    except ValidationError as exc:
        raise Unprocessable("; ".join(e["msg"] for e in exc.errors())) from exc
    ctx, warnings, missing = assess(db, merged)
    changed = {k: v for k, v in merged.model_dump().items() if v != current[k]}
    if not changed:
        return p
    extra = dict(locality=merged.locality or ctx["locality"], pincode=ctx["pincode"], ward_no=ctx["ward_no"],
                 zone_no=ctx["zone_no"], warnings=[w for w in warnings] +
                 [w for w in p.warnings if w["code"] == "possible_duplicate" and p.status == "possible_duplicate"],
                 missing_fields=[*missing] + (["photos"] if "photos" in p.missing_fields else []),
                 updated_at=text("now()"))
    if "lat" in changed or "lon" in changed:
        extra["geom"] = text(f"ST_SetSRID(ST_MakePoint({merged.lon}, {merged.lat}), 4326)")
    update_versioned(db, Property, p.id, version, **changed, **extra)
    audit.record(db, actor=actor, entity_type="property", entity_id=p.id, action="edited", reason="fields edited",
                 details={"fields": sorted(changed)})
    db.flush()
    db.refresh(p)
    return p


def resolve_duplicate(db: Session, actor: User, property_id: int, choice: str, target_id: int | None) -> Property:
    """The executive's explicit choice — never a silent merge or block."""
    p = visible(db, actor, property_id)
    if p.status != "possible_duplicate":
        raise Conflict(f"property {p.id} has no open duplicate question")
    if choice == "same":
        if target_id not in {c["id"] for c in p.duplicate_candidates}:
            raise Unprocessable("target_id must be one of the listed duplicate candidates")
        details = "; ".join(f"{k}: {v}" for k, v in (("address", p.address), ("landmark", p.landmark),
                                                    ("access", p.access_notes)) if v)
        db.add(PropertyNote(property_id=target_id, author_id=actor.id, kind="duplicate_merge",
                            text=f"Also scouted as #{p.id} “{p.label}”" + (f" — {details}" if details else "")))
        update_versioned(db, Property, p.id, p.version, status="merged", duplicate_of=target_id, updated_at=text("now()"))
        audit.record(db, actor=actor, entity_type="property", entity_id=p.id, action="merged",
                     from_state="possible_duplicate", to_state="merged", reason=f"same property as #{target_id}",
                     details={"target_id": target_id})
    else:
        update_versioned(db, Property, p.id, p.version, status="active", duplicate_candidates=[],
                         warnings=[w for w in p.warnings if w["code"] != "possible_duplicate"], updated_at=text("now()"))
        audit.record(db, actor=actor, entity_type="property", entity_id=p.id, action="duplicate_dismissed",
                     from_state="possible_duplicate", to_state="active", reason="confirmed a different property",
                     details={"candidates": [c["id"] for c in p.duplicate_candidates]})
    db.flush()
    db.refresh(p)
    return p


def add_note(db: Session, actor: User, property_id: int, text_: str, kind: str = "note") -> PropertyNote:
    visible(db, actor, property_id)
    note = PropertyNote(property_id=property_id, author_id=actor.id, kind=kind, text=text_)
    db.add(note)
    db.flush()
    return note


def add_photo(db: Session, actor: User, property_id: int, filename: str, content_type: str, data: bytes) -> PropertyPhoto:
    """Photos upload separately from the form (docs/DESIGN.md §6): the property is already saved,
    so a failed upload never loses it — it just stays flagged 'photos' missing."""
    cfg = load_config()["properties"]["photos"]
    p = visible(db, actor, property_id)
    if content_type not in cfg["types"]:
        raise Unprocessable(f"Photos must be one of {', '.join(cfg['types'])} (got {content_type})")
    if len(data) > cfg["max_bytes"]:
        raise Unprocessable(f"Photo is {len(data) / 1e6:.1f} MB; the limit is {cfg['max_bytes'] / 1e6:.0f} MB")
    rel = Path("properties") / str(p.id) / f"{uuid.uuid4().hex}{Path(filename).suffix.lower()[:6]}"
    dest = Path(get_settings().upload_dir) / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    photo = PropertyPhoto(property_id=p.id, uploaded_by=actor.id, filename=filename[:200], content_type=content_type,
                          bytes=len(data), path=str(rel))
    db.add(photo)
    if "photos" in p.missing_fields:
        db.execute(update(Property).where(Property.id == p.id)
                   .values(missing_fields=[f for f in p.missing_fields if f != "photos"]))
    audit.record(db, actor=actor, entity_type="property", entity_id=p.id, action="photo_added",
                 reason="photo uploaded", details={"bytes": len(data), "content_type": content_type})
    db.flush()
    return photo
