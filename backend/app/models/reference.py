"""Reference data loaded offline by `backend/ingest`. Every row belongs to one data snapshot;
analysis reads only the active (latest `ready`) snapshot. Rows are never updated in place —
a re-ingest creates a new snapshot."""
from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

def snapshot_fk() -> ForeignKey:
    return ForeignKey("data_snapshots.id", ondelete="CASCADE")


class DataSnapshot(Base):
    __tablename__ = "data_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(String(16), default="building")  # building | ready | failed
    config_version: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    stats: Mapped[dict] = mapped_column(JSONB, default=dict)


class DataSource(Base):
    """One raw file that went into a snapshot — the citation/provenance record."""
    __tablename__ = "data_sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(snapshot_fk(), index=True)
    key: Mapped[str] = mapped_column(String(64))
    path: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    bytes: Mapped[int] = mapped_column(BigInteger)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    row_count: Mapped[int | None] = mapped_column(Integer)


class ServiceArea(Base):
    __tablename__ = "service_areas"

    snapshot_id: Mapped[int] = mapped_column(snapshot_fk(), primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    geom = mapped_column(Geometry("MULTIPOLYGON", srid=4326), nullable=False)


class Zone(Base):
    __tablename__ = "zones"
    __table_args__ = (Index("uq_zones_snapshot_zone", "snapshot_id", "zone_no", unique=True),)

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(snapshot_fk(), index=True)
    zone_no: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(Text)
    region: Mapped[str | None] = mapped_column(Text)
    geom = mapped_column(Geometry("MULTIPOLYGON", srid=4326), nullable=False)


class Ward(Base):
    __tablename__ = "wards"
    __table_args__ = (Index("uq_wards_snapshot_ward", "snapshot_id", "ward_no", unique=True),)

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(snapshot_fk(), index=True)
    ward_no: Mapped[int] = mapped_column(Integer)
    zone_no: Mapped[int | None] = mapped_column(Integer)
    geom = mapped_column(Geometry("MULTIPOLYGON", srid=4326), nullable=False)


class PostOffice(Base):
    __tablename__ = "post_offices"

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(snapshot_fk(), index=True)
    pincode: Mapped[str] = mapped_column(String(6), index=True)
    office_name: Mapped[str] = mapped_column(Text)
    area: Mapped[str] = mapped_column(Text)
    office_type: Mapped[str | None] = mapped_column(String(4))
    district: Mapped[str | None] = mapped_column(Text)
    coord_decimals: Mapped[int] = mapped_column(Integer)  # precision of the source coordinate
    in_service_area: Mapped[bool] = mapped_column(Boolean)
    ward_no: Mapped[int | None] = mapped_column(Integer)
    zone_no: Mapped[int | None] = mapped_column(Integer)
    geom = mapped_column(Geometry("POINT", srid=4326), nullable=False)


class Pincode(Base):
    """One row per (pincode, source) part: a datameet 2013 polygon and/or a Voronoi part
    (whole shape where datameet lacks the pincode, or an extension where its 2013 shape stops short)."""
    __tablename__ = "pincodes"
    __table_args__ = (Index("uq_pincodes_snapshot_pin_source", "snapshot_id", "pincode", "geom_source", unique=True),)

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(snapshot_fk(), index=True)
    pincode: Mapped[str] = mapped_column(String(6))
    name: Mapped[str | None] = mapped_column(Text)
    geom_source: Mapped[str] = mapped_column(String(32))  # datameet_2013 | voronoi_approx
    clipped: Mapped[bool] = mapped_column(Boolean)  # true if the source shape spilled outside the service area
    geom = mapped_column(Geometry("MULTIPOLYGON", srid=4326), nullable=False)


class Store(Base):
    """Every row the Stores API returned (all zones) — filtering is by geometry at query time."""
    __tablename__ = "stores"
    __table_args__ = (Index("uq_stores_snapshot_code", "snapshot_id", "store_code", unique=True),)

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(snapshot_fk(), index=True)
    store_code: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(Text)
    address: Mapped[str | None] = mapped_column(Text)
    zone: Mapped[str | None] = mapped_column(String(16))
    is_operational: Mapped[bool] = mapped_column(Boolean)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    raw: Mapped[dict] = mapped_column(JSONB)
    geom = mapped_column(Geometry("POINT", srid=4326), nullable=False)


class H3Cell(Base):
    """Res 9 = scoring grid, res 8 = selection grid (see docs/DESIGN.md §3)."""
    __tablename__ = "h3_cells"
    __table_args__ = (Index("ix_h3_cells_snapshot_res", "snapshot_id", "res"),
                      Index("ix_h3_cells_parent", "snapshot_id", "parent_h3"))

    snapshot_id: Mapped[int] = mapped_column(snapshot_fk(), primary_key=True)
    h3: Mapped[str] = mapped_column(String(16), primary_key=True)
    res: Mapped[int] = mapped_column(Integer)
    parent_h3: Mapped[str | None] = mapped_column(String(16))
    ward_no: Mapped[int | None] = mapped_column(Integer)
    zone_no: Mapped[int | None] = mapped_column(Integer)
    area_km2: Mapped[float] = mapped_column(Float)
    geom = mapped_column(Geometry("POLYGON", srid=4326), nullable=False)


class Locality(Base):
    """Local search index (replaces live geocoding)."""
    __tablename__ = "localities"
    __table_args__ = (Index("ix_localities_name_trgm", "name_norm", postgresql_using="gin",
                            postgresql_ops={"name_norm": "gin_trgm_ops"}),)

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(snapshot_fk(), index=True)
    name: Mapped[str] = mapped_column(Text)
    name_norm: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(16))  # post_office | pincode | ward | zone | osm_place
    pincode: Mapped[str | None] = mapped_column(String(6))
    ward_no: Mapped[int | None] = mapped_column(Integer)
    zone_no: Mapped[int | None] = mapped_column(Integer)
    geom = mapped_column(Geometry("POINT", srid=4326), nullable=False)
