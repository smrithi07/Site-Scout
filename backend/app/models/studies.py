"""M3 — catchment studies (docs/DESIGN.md §7). The survey atom is the road segment (§3).

- `studies`: one request against a property; mutable workflow row (`version` for optimistic
  locking). Its reuse decision is recorded twice — what the BD Manager asked for and what the
  Survey Manager decided at planning (final say) — each with a reason when it overrides.
- `study_segments`: the catchment's segments with their reuse state at the last reuse check.
- `segment_captures`: raw lane observations, append-only (a DB trigger refuses UPDATE/DELETE). They
  outlive studies: freshness is per segment capture, so a later study reuses them.
"""
from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Study(Base):
    __tablename__ = "studies"
    # one open study per property (declared here so autogenerate keeps the hand-written index)
    __table_args__ = (Index("uq_studies_open_per_property", "property_id", unique=True,
                            postgresql_where=text("status NOT IN ('complete', 'cancelled')")),)

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), server_default="property")  # property (area studies: later)
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id"), index=True)
    requested_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    # requested → planned → in_progress → complete, or cancelled at any point before complete
    status: Mapped[str] = mapped_column(String(16), server_default="requested")
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("data_snapshots.id"))
    config_version: Mapped[str] = mapped_column(String(32))
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    radius_m: Mapped[float] = mapped_column(Float)
    catchment = mapped_column(Geometry("POLYGON", srid=4326), nullable=False)
    segment_count: Mapped[int] = mapped_column(Integer)
    total_length_m: Mapped[float] = mapped_column(Float)
    reuse: Mapped[dict] = mapped_column(JSONB)                   # coverage summary at the last check
    requested_mode: Mapped[str] = mapped_column(String(16))      # reuse_and_fill | reuse_only | full_survey
    request_reason: Mapped[str | None] = mapped_column(Text)
    planned_mode: Mapped[str | None] = mapped_column(String(16))  # the Survey Manager's final say
    plan_reason: Mapped[str | None] = mapped_column(Text)
    planned_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    planned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    rollup_job_id: Mapped[int | None] = mapped_column(BigInteger)    # the latest roll-up job (progress in the UI)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    version: Mapped[int] = mapped_column(Integer, server_default="1")


class StudySegment(Base):
    __tablename__ = "study_segments"

    study_id: Mapped[int] = mapped_column(ForeignKey("studies.id"), primary_key=True)
    segment_id: Mapped[str] = mapped_column(String(32), primary_key=True)  # road_segments id in study.snapshot_id
    length_m: Mapped[float] = mapped_column(Float)
    reuse_state: Mapped[str] = mapped_column(String(16))  # fresh | fresh_gap | stale | uncovered
    reused_capture_id: Mapped[int | None] = mapped_column(ForeignKey("segment_captures.id"))
    capture_age_days: Mapped[float | None] = mapped_column(Float)
    to_survey: Mapped[bool] = mapped_column(Boolean, server_default="false")
    # The one-segment-one-unit rule: a segment row holds at most one unit by construction; the
    # service re-validates after every edit that every to_survey segment has one and no other does.
    unit_id: Mapped[int | None] = mapped_column(ForeignKey("survey_units.id"), index=True)


class SurveyUnit(Base):
    """A contiguous, workload-balanced set of a study's to-survey segments, assignable to one survey
    executive. Estimates are recomputed after every edit (services/partition.estimate)."""
    __tablename__ = "survey_units"

    id: Mapped[int] = mapped_column(primary_key=True)
    study_id: Mapped[int] = mapped_column(ForeignKey("studies.id"), index=True)
    label: Mapped[str] = mapped_column(String(16))                       # U1, U2, …
    status: Mapped[str] = mapped_column(String(16), server_default="draft")  # draft | assigned | in_progress | submitted
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    segment_count: Mapped[int] = mapped_column(Integer, server_default="0")
    length_m: Mapped[float] = mapped_column(Float, server_default="0")
    minutes: Mapped[float] = mapped_column(Float, server_default="0")        # estimated workload
    walk_minutes: Mapped[float] = mapped_column(Float, server_default="0")   # of which walking between segments
    pieces: Mapped[int] = mapped_column(Integer, server_default="1")         # disconnected parts (1 = one walk)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SegmentCapture(Base):
    __tablename__ = "segment_captures"
    __table_args__ = (Index("ix_segment_captures_segment", "segment_id", "captured_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[str] = mapped_column(UUID(as_uuid=False), unique=True)   # idempotent submit
    study_id: Mapped[int | None] = mapped_column(ForeignKey("studies.id"), index=True)
    unit_id: Mapped[int | None] = mapped_column(Integer)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("data_snapshots.id"))
    segment_id: Mapped[str] = mapped_column(String(32))
    geom = mapped_column(Geometry("LINESTRING", srid=4326), nullable=False)    # copy: cross-snapshot matching
    captured_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    source: Mapped[str] = mapped_column(String(16), server_default="field")    # field | demo_seed (provenance: mock)
    status: Mapped[str] = mapped_column(String(20))                            # surveyed | could_not_survey
    reason: Mapped[str | None] = mapped_column(Text)                           # required for could_not_survey
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    time_band: Mapped[str | None] = mapped_column(String(16))
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    gps_accuracy_m: Mapped[float | None] = mapped_column(Float)
    gps_distance_m: Mapped[float | None] = mapped_column(Float)            # device fix → lane, checked server-side
    observations: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CatchmentSummary(Base):
    """The roll-up of a study's lane data (docs/DESIGN.md §7). Immutable, versioned per study (a
    re-run is v2, never an overwrite — DB trigger), stamped with snapshot + config version."""
    __tablename__ = "catchment_summaries"
    __table_args__ = (Index("uq_catchment_summaries_version", "study_id", "version", unique=True),)

    id: Mapped[int] = mapped_column(primary_key=True)
    study_id: Mapped[int] = mapped_column(ForeignKey("studies.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    trigger: Mapped[str] = mapped_column(String(24))          # all_units_submitted | closed_early | reuse_only | rerun
    coverage: Mapped[dict] = mapped_column(JSONB)             # lengths/shares: surveyed, gaps, not surveyed; sources
    signals: Mapped[dict] = mapped_column(JSONB)              # per signal: value, unit, normalized, provenance, notes
    anchors: Mapped[list] = mapped_column(JSONB)
    confidence: Mapped[str] = mapped_column(String(8))        # high | medium | low
    confidence_reasons: Mapped[list] = mapped_column(JSONB)
    facts_only: Mapped[bool] = mapped_column(Boolean)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("data_snapshots.id"))
    config_version: Mapped[str] = mapped_column(String(32))
    job_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
