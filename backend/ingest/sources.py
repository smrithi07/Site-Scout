"""Registry of raw files an ingest reads, plus the provenance record written for each."""
import hashlib
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import Connection, text

RAW = Path("/data/raw")

FILES = {
    "zones_2022": RAW / "wards/zones_2022.kml",
    "wards_2022": RAW / "wards/wards_2022.kml",
    "pincode_polygons_datameet": RAW / "pincode/chennai_boundary_datameet.geojson",
    "pincode_directory_bharatpin": RAW / "pincode/pincode_directory_bharatpin.csv",
}


def latest_stores_file() -> Path:
    files = sorted((RAW / "stores").glob("stores_*.json"))
    if not files:
        raise FileNotFoundError("no data/raw/stores/stores_*.json — fetch the Stores API first")
    return files[-1]


def file_retrieved_at(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)


def record_source(conn: Connection, snapshot_id: int, key: str, path: Path, row_count: int) -> None:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    conn.execute(
        text("""INSERT INTO data_sources (snapshot_id, key, path, sha256, bytes, retrieved_at, row_count)
                VALUES (:s, :key, :path, :sha, :bytes, :at, :rows)"""),
        dict(s=snapshot_id, key=key, path=str(path.relative_to(RAW.parent)), sha=digest.hexdigest(),
             bytes=path.stat().st_size, at=file_retrieved_at(path), rows=row_count),
    )
