"""M2 — scout tasks and scouted properties (docs/DESIGN.md §6). Mutable rows carry `version` for
optimistic locking; every change is audited by the services that make it."""
from datetime import date, datetime

from geoalchemy2 import Geometry
from sqlalchemy import BigInteger, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ScoutTask(Base):
    __tablename__ = "scout_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    assignee_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(16), server_default="open")  # open | in_progress | done | cancelled
    due_date: Mapped[date | None] = mapped_column(Date)
    source_report_id: Mapped[int | None] = mapped_column(ForeignKey("area_reports.id"))
    target_cells: Mapped[list[str]] = mapped_column(ARRAY(String(16)))    # res-8 selection cells
    hotspot_cells: Mapped[list[str]] = mapped_column(ARRAY(String(16)), server_default="{}")  # res-9 from the report
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    version: Mapped[int] = mapped_column(Integer, server_default="1")


class Property(Base):
    __tablename__ = "properties"
    __table_args__ = (Index("ix_properties_label_trgm", "label", postgresql_using="gin",
                            postgresql_ops={"label": "gin_trgm_ops"}),)

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[str] = mapped_column(UUID(as_uuid=False), unique=True)  # idempotent create
    label: Mapped[str] = mapped_column(Text)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("scout_tasks.id"), index=True)
    # location
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    gps_accuracy_m: Mapped[float | None] = mapped_column(Float)
    device_lat: Mapped[float | None] = mapped_column(Float)   # where the executive was when saving
    device_lon: Mapped[float | None] = mapped_column(Float)
    address: Mapped[str | None] = mapped_column(Text)
    landmark: Mapped[str | None] = mapped_column(Text)
    access_notes: Mapped[str | None] = mapped_column(Text)
    nearby_road: Mapped[str | None] = mapped_column(Text)
    locality: Mapped[str | None] = mapped_column(Text)
    pincode: Mapped[str | None] = mapped_column(String(6))
    ward_no: Mapped[int | None] = mapped_column(Integer)
    zone_no: Mapped[int | None] = mapped_column(Integer)
    # commercial (BD only)
    monthly_rent: Mapped[float | None] = mapped_column(Float)
    rent_unit: Mapped[str | None] = mapped_column(String(16))  # per_month | per_sqft_month
    area_sqft: Mapped[float | None] = mapped_column(Float)
    security_deposit: Mapped[float | None] = mapped_column(Float)
    availability: Mapped[str | None] = mapped_column(Text)
    # physical
    frontage_ft: Mapped[float | None] = mapped_column(Float)
    road_width_ft: Mapped[float | None] = mapped_column(Float)
    floor: Mapped[str | None] = mapped_column(String(16))
    # executive assessment (observed, self-reported)
    visibility: Mapped[str | None] = mapped_column(String(8))     # poor | fair | good
    accessibility: Mapped[str | None] = mapped_column(String(8))  # poor | fair | good
    parking: Mapped[str | None] = mapped_column(String(8))        # none | limited | good
    condition: Mapped[str | None] = mapped_column(String(8))      # poor | fair | good
    # contact (BD only)
    owner_name: Mapped[str | None] = mapped_column(Text)
    owner_phone: Mapped[str | None] = mapped_column(String(32))
    # workflow
    stage: Mapped[str] = mapped_column(String(24), server_default="scouted")
    status: Mapped[str] = mapped_column(String(24), server_default="active")  # active | possible_duplicate | merged
    duplicate_of: Mapped[int | None] = mapped_column(ForeignKey("properties.id"))
    duplicate_candidates: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    warnings: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    missing_fields: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    evaluation_status: Mapped[str] = mapped_column(String(16), server_default="not_started")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    version: Mapped[int] = mapped_column(Integer, server_default="1")
    geom = mapped_column(Geometry("POINT", srid=4326), nullable=False)


class PropertyNote(Base):
    __tablename__ = "property_notes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id"), index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(24), server_default="note")  # note | duplicate_merge | follow_up
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PropertyPhoto(Base):
    __tablename__ = "property_photos"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id"), index=True)
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    filename: Mapped[str] = mapped_column(Text)
    content_type: Mapped[str] = mapped_column(String(32))
    bytes: Mapped[int] = mapped_column(Integer)
    path: Mapped[str] = mapped_column(Text)   # relative to settings.upload_dir
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
