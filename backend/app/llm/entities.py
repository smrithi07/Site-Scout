"""Names the validator knows are real places/stores. If a narrative mentions one that isn't in
its fact sheet, the model has wandered off the facts (e.g. describing Adyar in a T Nagar report)."""
from sqlalchemy import text
from sqlalchemy.orm import Session

# Single words that are also ordinary English — too risky to treat as place names.
_GENERIC = {"central", "market", "colony", "garden", "gardens", "nagar", "street", "road", "puram", "north",
            "south", "east", "west", "new", "old", "main", "church", "temple", "station", "beach", "lake"}

_cache: dict[int, list[str]] = {}


def known_entities(db: Session, snapshot_id: int) -> list[str]:
    if snapshot_id not in _cache:
        rows = db.execute(text("""
            SELECT name FROM zones WHERE snapshot_id = :s
            UNION SELECT name FROM stores WHERE snapshot_id = :s
            UNION SELECT name FROM localities WHERE snapshot_id = :s AND kind IN ('post_office', 'osm_place', 'pincode')
                                            AND ward_no IS NOT NULL"""), dict(s=snapshot_id)).scalars()
        names = {n.strip() for n in rows if n}
        _cache.clear()
        _cache[snapshot_id] = sorted(n for n in names
                                     if len(n) >= 6 and n.lower() not in _GENERIC and not n[0].isdigit()
                                     and (" " in n or len(n) >= 8))
    return _cache[snapshot_id]
