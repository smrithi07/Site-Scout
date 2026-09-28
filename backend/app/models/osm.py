"""OSM-derived layers, one set per data snapshot (loaded offline by `ingest/osm.py`).
Every value here is `observed` OSM data; OSM under-tags small shops, so competitor counts are a
lower bound (docs/DESIGN.md §12)."""
from geoalchemy2 import Geometry
from sqlalchemy import BigInteger, Boolean, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.reference import snapshot_fk


class OsmPoi(Base):
    __tablename__ = "osm_pois"
    __table_args__ = (Index("ix_osm_pois_snapshot_category", "snapshot_id", "category"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(snapshot_fk(), index=True)
    osm_ref: Mapped[str] = mapped_column(String(24))          # n123 / w456 / r789
    category: Mapped[str] = mapped_column(String(24))         # competitor | transit | school | ...
    subtype: Mapped[str] = mapped_column(Text)                # the matching tag, e.g. shop=supermarket
    name: Mapped[str | None] = mapped_column(Text)
    brand: Mapped[str | None] = mapped_column(Text)
    geom = mapped_column(Geometry("POINT", srid=4326), nullable=False)


class OsmBuilding(Base):
    """Building footprints reduced to a point + area — enough for cell and site-radius density."""
    __tablename__ = "osm_buildings"

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(snapshot_fk(), index=True)
    osm_ref: Mapped[str] = mapped_column(String(24))
    btype: Mapped[str] = mapped_column(Text)                  # building=* value
    levels: Mapped[int | None] = mapped_column(Integer)
    footprint_m2: Mapped[float] = mapped_column(Float)
    geom = mapped_column(Geometry("POINT", srid=4326), nullable=False)


class MlBuilding(Base):
    """ML-derived building footprints (Microsoft Global ML Building Footprints), kept apart from
    OSM: many OSM buildings in India were imported from such datasets, so merging would double
    count. Provenance `observed (ML-derived)`."""
    __tablename__ = "ml_buildings"

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(snapshot_fk(), index=True)
    source: Mapped[str] = mapped_column(String(32))            # e.g. ms_global_ml_2026_02
    confidence: Mapped[float | None] = mapped_column(Float)    # NULL where the source says -1 (unknown)
    height_m: Mapped[float | None] = mapped_column(Float)
    footprint_m2: Mapped[float] = mapped_column(Float)
    geom = mapped_column(Geometry("POINT", srid=4326), nullable=False)


class OsmLanduse(Base):
    __tablename__ = "osm_landuse"

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(snapshot_fk(), index=True)
    osm_ref: Mapped[str] = mapped_column(String(24))          # 'coastline' for the derived sea polygon
    lclass: Mapped[str] = mapped_column(String(24))           # residential | industrial | water | sea | ...
    tag: Mapped[str] = mapped_column(Text)
    name: Mapped[str | None] = mapped_column(Text)
    geom = mapped_column(Geometry("MULTIPOLYGON", srid=4326), nullable=False)


class RoadSegment(Base):
    """OSM road split at junctions — the survey atom (docs/DESIGN.md §3). `segment_id` is unique
    within a snapshot: '<way_id>:<piece index along the way>'."""
    __tablename__ = "road_segments"
    __table_args__ = (Index("ix_road_segments_nodes", "snapshot_id", "from_node", "to_node"),)

    snapshot_id: Mapped[int] = mapped_column(snapshot_fk(), primary_key=True)
    segment_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    way_id: Mapped[int] = mapped_column(BigInteger)
    from_node: Mapped[int] = mapped_column(BigInteger)
    to_node: Mapped[int] = mapped_column(BigInteger)
    highway: Mapped[str] = mapped_column(String(24))
    name: Mapped[str | None] = mapped_column(Text)
    length_m: Mapped[float] = mapped_column(Float)
    geom = mapped_column(Geometry("LINESTRING", srid=4326), nullable=False)


class CellFeature(Base):
    """Raw per-cell facts for the score grid (res 9). Normalisation/scoring happens in Phase 4."""
    __tablename__ = "cell_features"

    snapshot_id: Mapped[int] = mapped_column(snapshot_fk(), primary_key=True)
    h3: Mapped[str] = mapped_column(String(16), primary_key=True)
    building_count: Mapped[int] = mapped_column(Integer)
    building_footprint_m2: Mapped[float] = mapped_column(Float)
    ml_building_count: Mapped[int] = mapped_column(Integer)
    ml_building_footprint_m2: Mapped[float] = mapped_column(Float)
    residential_share: Mapped[float] = mapped_column(Float)
    commercial_share: Mapped[float] = mapped_column(Float)
    blocking_share: Mapped[float] = mapped_column(Float)      # sea/water/beach/airport/industrial/...
    blocking_class: Mapped[str | None] = mapped_column(String(24))
    competitor_count: Mapped[int] = mapped_column(Integer)
    transit_count: Mapped[int] = mapped_column(Integer)
    school_count: Mapped[int] = mapped_column(Integer)
    hospital_count: Mapped[int] = mapped_column(Integer)
    office_count: Mapped[int] = mapped_column(Integer)
    market_count: Mapped[int] = mapped_column(Integer)
    road_length_m: Mapped[float] = mapped_column(Float)
    main_road_length_m: Mapped[float] = mapped_column(Float)
    residential_road_length_m: Mapped[float] = mapped_column(Float)
    junction_count: Mapped[int] = mapped_column(Integer)
    scoreable: Mapped[bool] = mapped_column(Boolean)
    mask_reason: Mapped[str | None] = mapped_column(String(24))
