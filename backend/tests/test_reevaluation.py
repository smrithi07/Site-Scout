"""Phase 10c checkpoint — the M1→M3 loop closes: a completed study re-evaluates its property as a
NEW version (v1 untouched) in which observed signals replace the proxies and observed footfall
joins; the v1→v2 diff classifies every change (data change / config change / factor newly
included / renormalization) and its point changes add up to the score change; the narrative only
phrases the diff and is validated like every other narrative."""
import copy

import pytest

from app.llm import diff_narrative
from app.services import diff as diffs
from tests.conftest import purge_scouting_test_data
from tests.test_rollup import assign_all, capture_unit, drain
from tests.test_studies import BDM, SE
from tests.test_units import planned  # noqa: F401  (fixture)


def factor(key, norm, weight, eff, raw=1.0, prov="proxy", source="OSM", label=None):
    return {"factor": key, "label": label or key, "unit": "u", "source": source, "provenance": prov, "weight": weight,
            "raw": raw, "normalized": norm, "effective_weight": eff,
            "contribution": None if norm is None else round(eff * norm / 100, 1)}


def snap(version, factors, risks=(), score=None, outcome="Consider", config="1", snapshot=10):
    score = score if score is not None else round(sum(f["contribution"] or 0 for f in factors), 1)
    return {"version": version, "score": score, "outcome": outcome, "confidence": "Medium", "factors": factors,
            "risks": list(risks), "hard_flags": [], "snapshot_id": snapshot, "config_version": config}


V1 = snap(1, [factor("site_demand", 60, 50, 50.0), factor("rent", 80, 50, 50.0, prov="mock", source="band"),
              factor("footfall", None, 0, 0.0)],
          risks=[{"rule_id": "R-COMPETITION", "severity": "medium", "message": "7 shops (OSM lower bound)"}])
V2 = snap(2, [factor("site_demand", 30, 50, 40.0, raw=12.0, prov="observed", source="Catchment study #9 (summary v1)"),
              factor("rent", 80, 50, 40.0, prov="mock", source="band"),
              factor("footfall", 70, 25, 20.0, prov="observed", source="Catchment study #9 (summary v1)")],
          risks=[{"rule_id": "R-FOOTFALL-BAND", "severity": "low", "message": "single time band"}])


def test_every_change_is_classified_and_the_points_add_up():
    d = diffs.diff(V1, V2)
    by = {c["factor"]: c for c in d["factors"]}
    assert by["footfall"]["cause"] == "factor newly included" and by["footfall"]["points_change"] == 14.0
    assert by["site_demand"]["cause"] == "data change" and "Catchment study #9" in by["site_demand"]["explanation"]
    assert "scales differ" in by["site_demand"]["explanation"]           # proxy → observed is not like-for-like
    assert by["rent"]["cause"] == "renormalization"                       # same data, smaller share
    assert by["rent"]["points_change"] == pytest.approx(-8.0)
    assert d["score"]["change"] == pytest.approx(V2["score"] - V1["score"])
    assert d["score"]["rounding_gap"] == pytest.approx(0, abs=0.2)
    assert [r["rule_id"] for r in d["new_risks"]] == ["R-FOOTFALL-BAND"]
    assert [r["rule_id"] for r in d["resolved_risks"]] == ["R-COMPETITION"]
    assert d["causes"] == {"factor newly included": 1, "data change": 1, "renormalization": 1}


def test_config_changes_are_told_apart_from_data_changes():
    same_raw = copy.deepcopy(V1)
    same_raw["version"], same_raw["config_version"] = 2, "2"
    same_raw["factors"][0] = factor("site_demand", 75, 50, 50.0)          # same raw, new thresholds
    same_raw["factors"][1] = factor("rent", 80, 70, 50.0, prov="mock", source="band")   # weight changed
    by = {c["factor"]: c for c in diffs.diff(V1, same_raw)["factors"]}
    assert by["site_demand"]["cause"] == "config change" and by["rent"]["cause"] == "config change"
    new_snapshot = copy.deepcopy(same_raw)
    new_snapshot["config_version"], new_snapshot["snapshot_id"] = "1", 11   # same config, new data snapshot
    assert {c["factor"]: c for c in diffs.diff(V1, new_snapshot)["factors"]}["site_demand"]["cause"] == "data change"


def test_the_template_passes_its_own_validator_and_the_validator_catches_inventions():
    sheet = diffs.fact_sheet(diffs.diff(V1, V2), "TEST shop")
    t = diff_narrative.template(sheet)
    assert diff_narrative.validate({"summary": t["summary"], "changes": t["changes"]}, sheet) == []
    bad_number = {"summary": "Score rose by 12.5 points.", "changes": ["Footfall newly included."]}
    assert any("numbers not in the fact sheet" in e for e in diff_narrative.validate(bad_number, sheet))
    bad_cause = {"summary": "Up after the study.", "changes": ["Rent changed because of a config change."]}
    assert any("cause(s) not in the fact sheet" in e for e in diff_narrative.validate(bad_cause, sheet))
    bad_label = {"summary": "Now a Strong Fit.", "changes": ["Footfall is factor newly included, 14 points."]}
    assert any("rating label" in e for e in diff_narrative.validate(bad_label, sheet))
    signless = {"summary": "Score went down after the study.", "changes": ["Rent: renormalization, down 8 points."]}
    assert diff_narrative.validate(signless, sheet) == []                  # -8.0 stated as "down 8"


# --- end to end: study complete → v2 evaluation with a diff ---------------------------------

@pytest.fixture(autouse=True)
def cleanup():
    purge_scouting_test_data()
    yield
    purge_scouting_test_data()


def test_a_completed_study_creates_v2_with_observed_factors_and_an_explained_diff(client, planned):  # noqa: F811
    plan = assign_all(client, planned)
    pid = plan["study"]["property_id"]
    for u in plan["units"]:
        capture_unit(client, plan, u)
        assert client.post(f"/units/{u['id']}/submit", headers=SE).status_code == 200
    drain()                                   # v1 (onboarding) → roll-up → v2 (study complete)
    evs = client.get(f"/properties/{pid}/evaluations", headers=BDM).json()
    assert [e["version"] for e in evs] == [2, 1] and evs[0]["trigger"] == "study_complete" and evs[0]["has_diff"]
    v1 = client.get(f"/properties/{pid}/evaluations/1", headers=BDM).json()
    v2 = client.get(f"/properties/{pid}/evaluations/2", headers=BDM).json()
    f1, f2 = ({f["factor"]: f for f in v["factors"]} for v in (v1, v2))
    assert v1["diff"] is None and "footfall" not in f1                     # v1 untouched
    assert f2["footfall"]["normalized"] is not None and f2["footfall"]["source"].startswith("Catchment study")
    for key in ("site_demand", "competition", "accessibility"):
        assert f2[key]["source"].startswith("Catchment study") and f2[key]["provenance"] in ("observed", "mixed")
    d = v2["diff"]
    assert (d["from_version"], d["to_version"]) == (1, 2)
    causes = {c["factor"]: c["cause"] for c in d["factors"]}
    assert causes["footfall"] == "factor newly included"
    assert causes["site_demand"] == causes["competition"] == causes["accessibility"] == "data change"
    assert "renormalization" in causes.values()                           # e.g. rent's share shrank
    assert d["score"]["rounding_gap"] == pytest.approx(0, abs=0.5)
    assert any(f["fact"] == "footfall" for f in d["new_facts"])
    assert v2["narrative_source"] == "template" and v2["narrative"]["summary"]    # tests never call an LLM
    assert v2["narrative_meta"]["attempts"]
    review = client.get(f"/properties/{pid}", headers=BDM).json()
    assert review["evaluation"]["version"] == 2 and review["review"]["outcome"] == v2["outcome"]


def test_a_facts_only_study_keeps_the_estimates_and_says_so(client):
    from tests import test_studies as st
    from tests.test_studies import SM
    p = st.shortlisted(client)                                           # nothing captured nearby: 0% coverage
    s = st.request(client, p).json()
    s = client.post(f"/studies/{s['id']}/plan", json={"version": s["version"], "mode": "reuse_and_fill"}, headers=SM).json()
    r = client.post(f"/studies/{s['id']}/rollup", json={"version": s["version"], "reason": "rained off"}, headers=SM)
    assert r.status_code == 202
    drain()
    assert client.get(f"/studies/{s['id']}/summary", headers=SM).json()["facts_only"] is True
    v2 = client.get(f"/properties/{p['id']}/evaluations/2", headers=BDM).json()
    f2 = {f["factor"]: f for f in v2["factors"]}
    assert "footfall" not in f2 and not f2["site_demand"]["source"].startswith("Catchment study")
    assert "R-STUDY-THIN" in {r["rule_id"] for r in v2["risks"]}
    assert "R-STUDY-THIN" in {r["rule_id"] for r in v2["diff"]["new_risks"]}
