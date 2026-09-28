"""Area Fitness Reports — immutable, versioned snapshots (Core rule 2). Re-running an area creates
the next version under the same `area_key`. A DB trigger (migration 0006) rejects every UPDATE,
and DELETE unless the transaction explicitly sets `sitescout.purge = on` (test cleanup only)."""
from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AreaReport(Base):
    __tablename__ = "area_reports"
    __table_args__ = (Index("uq_area_reports_key_version", "area_key", "version", unique=True),)

    id: Mapped[int] = mapped_column(primary_key=True)
    area_key: Mapped[str] = mapped_column(String(16), index=True)   # hash of the score-cell set
    version: Mapped[int] = mapped_column(Integer)                    # 1, 2, … per area_key
    label: Mapped[str] = mapped_column(Text)
    selection: Mapped[dict] = mapped_column(JSONB)                   # the user's input, as given
    resolved: Mapped[dict] = mapped_column(JSONB)                    # basis, warnings, cell lists
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("data_snapshots.id"))
    config_version: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(24))                  # scored | facts_only | insufficient_data
    score: Mapped[float | None] = mapped_column(Float)
    rating: Mapped[str | None] = mapped_column(String(24))
    confidence: Mapped[str | None] = mapped_column(String(8))
    result: Mapped[dict] = mapped_column(JSONB)                      # factors, hotspots, facts, fact sheet
    narrative: Mapped[dict] = mapped_column(JSONB)                   # {summary, why, where_to_scout, caveats}
    narrative_source: Mapped[str] = mapped_column(String(16))        # template | gemini | groq
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"))  # no ON DELETE action: rows are immutable
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    select_cells: Mapped[list[str]] = mapped_column(ARRAY(String(16)))
    geom = mapped_column(Geometry("MULTIPOLYGON", srid=4326), nullable=False)
