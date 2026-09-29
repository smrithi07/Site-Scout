"""Unit fragmentation guard (docs/DECISIONS.md, 9b fix): on connected stretches of lanes the
partitioner must produce contiguous, balanced units — not interleaved stubs."""
import pytest

from app.core.config import load_config
from app.services import partition as P

CFG = load_config()["studies"]["units"]


def street_grid(nx: int, ny: int, block_m: float = 80.0) -> list[dict]:
    """A Manhattan grid of nx × ny junctions; every block edge is one lane."""
    segs = []
    node = lambda i, j: i * 1000 + j  # noqa: E731
    for i in range(nx):
        for j in range(ny):
            for di, dj in ((1, 0), (0, 1)):
                if i + di < nx and j + dj < ny:
                    segs.append({"segment_id": f"{i},{j}->{i + di},{j + dj}", "from_node": node(i, j),
                                 "to_node": node(i + di, j + dj), "length_m": block_m,
                                 "x": (i + di / 2) * block_m, "y": (j + dj / 2) * block_m})
    return segs


def check(units, survey_ids):
    got = [i for u in units for i in u["segment_ids"]]
    assert sorted(got) == sorted(survey_ids)                       # every lane exactly once
    return [u["pieces"] for u in units], [u["minutes"] for u in units]


def test_one_long_street_splits_into_contiguous_units():
    segs = [{"segment_id": f"s{i}", "from_node": i, "to_node": i + 1, "length_m": 80.0, "x": i * 80.0, "y": 0.0}
            for i in range(60)]
    pieces, mins = check(P.partition(segs, {s["segment_id"] for s in segs}, CFG), [s["segment_id"] for s in segs])
    assert len(pieces) > 1 and all(p == 1 for p in pieces)        # no interleaving along a stretch


@pytest.mark.parametrize("n", [8, 12])
def test_full_grid_units_are_nearly_contiguous_and_balanced(n):
    segs = street_grid(n, n)
    pieces, mins = check(P.partition(segs, {s["segment_id"] for s in segs}, CFG), [s["segment_id"] for s in segs])
    assert max(pieces) <= 2 and sum(pieces) / len(pieces) <= 1.3
    assert max(mins) <= CFG["max_unit_minutes"] and min(mins) >= 0.6 * CFG["target_unit_minutes"]


def test_block_of_gaps_inside_reused_lanes_stays_whole():
    segs = street_grid(12, 12)
    block = {s["segment_id"] for s in segs if s["x"] <= 4 * 80 and s["y"] <= 4 * 80}   # one stale block
    pieces, _ = check(P.partition(segs, block, CFG), sorted(block))
    assert all(p == 1 for p in pieces)
