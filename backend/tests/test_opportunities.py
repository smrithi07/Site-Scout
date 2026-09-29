"""Phase 11a checkpoint — the city-wide opportunity map: high-scoring, un-scouted pockets from the
M1 engine; a pocket's score is exactly what an area report on its cells computes; anything scouted
(property, live scout task, Savomart store) drops out; BD Manager only (see test_auth)."""
import h3
import pytest

from app.core.auth import Role
from app.core.db import SessionLocal
from app.services import opportunities, scoring, selection, snapshots
from tests.conftest import USER_IDS, headers, purge_scouting_test_data

BDM = headers(Role.BD_MANAGER)
SEED = h3.latlng_to_cell(13.0418, 80.2341, 8)


def ring(cell, k=1):
    return sorted(h3.grid_ring(cell, k))


def test_pockets_grow_contiguous_capped_separate_and_skip_scouted():
    n = ring(SEED)
    far = h3.grid_ring(SEED, 4)[0]
    rated = {SEED: 90, n[0]: 80, n[1]: 70, n[2]: 75, n[3]: 40, far: 85, h3.grid_ring(far, 1)[0]: 60}
    pockets = opportunities.grow_pockets(rated, threshold=65, skip=set(), max_cells=3)
    assert pockets[0] == [SEED, n[0], n[2]]                   # best adjacent first, capped at 3
    assert pockets[1] == [far]                                # its neighbour is below the threshold
    assert n[1] not in sum(pockets, [])                       # 70 but next to a closed pocket: not a new seed

    skipped = opportunities.grow_pockets(rated, threshold=65, skip={SEED}, max_cells=3)
    assert SEED not in sum(skipped, []) and skipped[0][0] == far   # scouted cells never seed or join


def test_percentile_is_the_citywide_cut():
    assert opportunities.percentile(list(range(100)), 80) == 80
    assert opportunities.percentile([5.0], 80) == 5.0


@pytest.fixture
def cleanup():
    purge_scouting_test_data()
    yield
    purge_scouting_test_data()


def test_the_map_ranks_rated_pockets_and_each_score_matches_an_area_report(client):
    d = client.get("/opportunities", headers=BDM).json()
    assert d["basis"].startswith("desk estimate") and d["caveats"]
    ps = d["pockets"]
    assert ps and [p["rank"] for p in ps] == list(range(1, len(ps) + 1))
    assert [p["score"] for p in ps] == sorted((p["score"] for p in ps), reverse=True)
    assert all(p["rating"] and 1 <= len(p["cells"]) <= 3 for p in ps)
    assert all(min(p["cell_scores"].values()) >= d["method"]["threshold"] for p in ps)
    scouted = {c["h3"] for c in d["scouted"]}
    assert not scouted & {c for p in ps for c in p["cells"]}
    with SessionLocal() as db:               # "start analysis" goes through selection → score_area
        model = scoring.city_model(db, snapshots.active_snapshot(db).id)
        for p in ps[:3]:
            r = selection.resolve(db, selection.Selection(**p["selection"]))
            assert scoring.score_area(model, r["score_cells"])["score"] == p["score"]


def test_a_scout_task_on_a_pocket_takes_it_off_the_map(client, cleanup):
    top = client.get("/opportunities", headers=BDM).json()["pockets"][0]
    task = client.post("/tasks", headers=BDM, json={"title": "TEST scout the top pocket",
                                                    "assignee_id": USER_IDS[Role.BD_EXECUTIVE],
                                                    "target_cells": top["cells"]})
    assert task.status_code == 201, task.text
    after = client.get("/opportunities", headers=BDM).json()
    assert set(top["cells"]) <= {c["h3"] for c in after["scouted"]}
    assert not set(top["cells"]) & {c for p in after["pockets"] for c in p["cells"]}
    why = {c["h3"]: c["why"] for c in after["scouted"]}
    assert f"scout task #{task.json()['id']}" in why[top["cells"][0]]
