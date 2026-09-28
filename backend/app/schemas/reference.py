from datetime import datetime

from pydantic import BaseModel


class GeometryBasis(BaseModel):
    basis: str | None          # pincode | ward | zone | point_radius | None (outside service area)
    source: str | None         # datameet_2013 | voronoi_approx | gcc_2022 | point_radius
    approximate: bool | None
    label: str


class LocalityCandidate(BaseModel):
    id: int
    name: str
    kind: str                  # post_office | pincode | ward | zone
    pincode: str | None
    ward_no: int | None
    zone_no: int | None
    zone_name: str | None
    in_service_area: bool
    lat: float
    lon: float
    score: float
    geometry: GeometryBasis


class LocalitySearchResult(BaseModel):
    query: str
    snapshot_id: int
    candidates: list[LocalityCandidate]


class DataSourceOut(BaseModel):
    key: str
    path: str
    sha256: str
    bytes: int
    retrieved_at: datetime
    row_count: int | None


class SnapshotOut(BaseModel):
    id: int
    status: str
    config_version: str
    created_at: datetime
    finished_at: datetime | None
    stats: dict
    sources: list[DataSourceOut]
