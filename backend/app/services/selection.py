"""Selection → geometry → H3 cells (docs/DESIGN.md §3, §5). Pincode, locality and hand-picked
cells all converge on the same representation: a set of score cells (res 9) and the selection
cells (res 8) they belong to. Ambiguity is never guessed away: outside-area localities, unknown
cells and too-small/too-large selections are rejected with an explanation."""
import hashlib
from collections import deque
from typing import Literal

import h3
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import load_config
from app.core.errors import SelectionError
from app.services.localities import GEOMETRY_LABELS, geometry_basis
from app.services.snapshots import active_snapshot


class Selection(BaseModel):
    mode: Literal["pincode", "locality", "cells"]
    pincode: str | None = Field(None, pattern=r"^\d{6}$")
    locality_id: int | None = None
    cells: list[str] = []                      # res-8 selection cells (mode = cells)
    add_cells: list[str] = []                  # res-8 cells to add after resolving
    remove_cells: list[str] = []               # res-8 cells to remove after resolving

    @model_validator(mode="after")
    def _one_input(self):
        needed = {"pincode": self.pincode, "locality": self.locality_id, "cells": self.cells}[self.mode]
        if not needed:
            raise ValueError(f"mode '{self.mode}' needs its input ({'pincode' if self.mode == 'pincode' else 'locality_id' if self.mode == 'locality' else 'cells'})")
        return self


def _cells_in_geometry(db: Session, s: int, geom_sql: str, params: dict) -> list[str]:
    res = load_config()["grid"]["score_res"]
    return list(db.execute(text(f"""
        SELECT c.h3 FROM h3_cells c, ({geom_sql}) g
        WHERE c.snapshot_id = :s AND c.res = :res AND ST_Intersects(g.geom, ST_Centroid(c.geom))
        ORDER BY c.h3"""), dict(s=s, res=res, **params)).scalars())


def _children(db: Session, s: int, parents: list[str]) -> list[str]:
    return list(db.execute(text("SELECT h3 FROM h3_cells WHERE snapshot_id = :s AND parent_h3 = ANY(:p) ORDER BY h3"),
                           dict(s=s, p=parents)).scalars())


def _check_parents_exist(db: Session, s: int, cells: list[str]) -> None:
    known = set(db.execute(text("SELECT h3 FROM h3_cells WHERE snapshot_id = :s AND res = :r AND h3 = ANY(:c)"),
                           dict(s=s, r=load_config()["grid"]["select_res"], c=cells)).scalars())
    unknown = sorted(set(cells) - known)
    if unknown:
        raise SelectionError(f"{len(unknown)} cell(s) are not selection cells inside the service area: "
                             f"{', '.join(unknown[:5])}{'…' if len(unknown) > 5 else ''}")


def nearby_name(db: Session, s: int, cells: list[str]) -> str:
    """' near <locality> (<zone> zone)' for hand-picked cells, so a report list says where they are."""
    if not cells:
        return ""
    row = db.execute(text("""
        WITH c AS (SELECT ST_Centroid(ST_Collect(ST_Centroid(geom))) AS pt FROM h3_cells
                   WHERE snapshot_id = :s AND h3 = ANY(:cells))
        SELECT (SELECT l.name FROM localities l WHERE l.snapshot_id = :s AND l.ward_no IS NOT NULL
                  AND l.kind IN ('osm_place', 'post_office') ORDER BY l.geom <-> c.pt LIMIT 1) AS place,
               (SELECT z.name FROM zones z WHERE z.snapshot_id = :s ORDER BY z.geom <-> c.pt LIMIT 1) AS zone
        FROM c"""), dict(s=s, cells=cells)).one()
    return f" near {row.place} ({row.zone} zone)" if row.place else ""


def _contiguous(cells: set[str]) -> bool:
    if not cells:
        return True
    start = next(iter(cells))
    seen, todo = {start}, deque([start])
    while todo:
        for n in h3.grid_disk(todo.popleft(), 1):
            if n in cells and n not in seen:
                seen.add(n)
                todo.append(n)
    return len(seen) == len(cells)


def resolve(db: Session, sel: Selection) -> dict:
    snap = active_snapshot(db)
    s, cfg = snap.id, load_config()
    warnings: list[str] = []

    if sel.mode == "pincode":
        parts = db.execute(text("SELECT name, geom_source FROM pincodes WHERE snapshot_id = :s AND pincode = :p "
                                "ORDER BY geom_source"), dict(s=s, p=sel.pincode)).all()
        if not parts:
            raise SelectionError(f"No boundary for pincode {sel.pincode} in the service area. "
                                 "Search it as a locality, or pick cells on the map.")
        source = "+".join(p.geom_source for p in parts)
        basis = {"basis": "pincode", "source": source, "approximate": True, "label": GEOMETRY_LABELS[source]}
        label = f"Pincode {sel.pincode} · {parts[0].name}"
        cells = _cells_in_geometry(db, s, "SELECT ST_Union(geom) AS geom FROM pincodes WHERE snapshot_id = :s AND pincode = :p",
                                   dict(p=sel.pincode))

    elif sel.mode == "locality":
        loc = db.execute(text("""
            SELECT l.name, l.kind, l.pincode, l.ward_no, l.zone_no, z.name AS zone_name,
                   (l.ward_no IS NOT NULL OR l.kind = 'zone') AS in_area,
                   (SELECT string_agg(geom_source, '+' ORDER BY geom_source) FROM pincodes
                    WHERE snapshot_id = :s AND pincode = l.pincode) AS pin_source
            FROM localities l LEFT JOIN zones z ON z.snapshot_id = l.snapshot_id AND z.zone_no = l.zone_no
            WHERE l.snapshot_id = :s AND l.id = :id"""), dict(s=s, id=sel.locality_id)).one_or_none()
        if loc is None:
            raise SelectionError(f"Locality {sel.locality_id} not found in the current data snapshot; search again.")
        basis = geometry_basis(loc.kind, loc.in_area, loc.pin_source)
        if basis["basis"] is None:
            raise SelectionError(f"{loc.name} is outside the service area (Greater Chennai Corporation).")
        where = {"pincode": ("SELECT ST_Union(geom) AS geom FROM pincodes WHERE snapshot_id = :s AND pincode = :v", loc.pincode),
                 "ward": ("SELECT geom FROM wards WHERE snapshot_id = :s AND ward_no = :v", loc.ward_no),
                 "zone": ("SELECT geom FROM zones WHERE snapshot_id = :s AND zone_no = :v", loc.zone_no),
                 "point_radius": ("SELECT ST_Buffer(geom::geography, :r)::geometry AS geom FROM localities "
                                  "WHERE snapshot_id = :s AND id = :v", sel.locality_id)}[basis["basis"]]
        cells = _cells_in_geometry(db, s, where[0], dict(v=where[1], r=cfg["selection"]["point_radius_m"]))
        if loc.kind == "zone":
            label = f"{loc.name} zone"
        else:
            context = ", ".join(x for x in (loc.pincode, f"ward {loc.ward_no}" if loc.ward_no else None,
                                             loc.zone_name) if x)
            label = f"{loc.name} ({context})" if context else loc.name
        if basis["basis"] == "ward" and loc.kind != "ward":
            warnings.append(f"{loc.name} has no pincode boundary; using ward {loc.ward_no} instead.")

    else:
        _check_parents_exist(db, s, sel.cells)
        basis = {"basis": "cells", "source": "h3", "approximate": False, "label": "cells picked on the map"}
        cells = _children(db, s, sel.cells)
        label = f"{len(set(sel.cells))} cells{nearby_name(db, s, cells)}"

    # Manual edits happen on selection cells (what the user sees and clicks).
    if sel.add_cells:
        _check_parents_exist(db, s, sel.add_cells)
        cells = sorted(set(cells) | set(_children(db, s, sel.add_cells)))
    if sel.remove_cells:
        drop = set(_children(db, s, sel.remove_cells))
        cells = sorted(set(cells) - drop)
    if sel.add_cells or sel.remove_cells:
        label += f" (edited: +{len(sel.add_cells)}/−{len(sel.remove_cells)} cells)"

    lo, hi = cfg["selection"]["min_score_cells"], cfg["selection"]["max_score_cells"]
    if len(cells) < lo:
        raise SelectionError(f"Selection covers {len(cells)} score cell(s); the minimum is {lo} (about one map "
                             "cell). Add neighbouring cells or pick a larger area.")
    if len(cells) > hi:
        raise SelectionError(f"Selection covers {len(cells)} score cells (~{len(cells) * 0.105:.0f} km²); the maximum "
                             f"is {hi} (~{hi * 0.105:.0f} km²). Pick a pincode or ward instead of a whole zone, or "
                             "remove cells.")

    parents = sorted({h3.cell_to_parent(c, cfg["grid"]["select_res"]) for c in cells})
    non_contiguous = not _contiguous(set(parents))
    if non_contiguous:
        warnings.append("The selection is not one contiguous area; it will be analysed as a whole.")
    return {
        "snapshot_id": s, "label": label, "mode": sel.mode, "input": sel.model_dump(exclude_defaults=True),
        "basis": basis, "select_cells": parents, "score_cells": cells, "non_contiguous": non_contiguous,
        "area_km2": round(sum(h3.cell_area(c, "km^2") for c in cells), 2),
        "area_key": hashlib.sha256(",".join(cells).encode()).hexdigest()[:16],
        "warnings": warnings,
    }
