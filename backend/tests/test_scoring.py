"""Scoring rules on a synthetic city (no database): Core rule 1 in code."""
import pytest

from app.services.scoring import FACTORS, CityModel, score_area


def _city(n: int = 20, missing: dict[str, set[int]] | None = None, scoreable: set[int] | None = None,
          raw: dict[str, list[float]] | None = None) -> tuple[CityModel, list[str]]:
    """n cells named c0..c{n-1}; factor f's raw value for cell i is i unless overridden or missing."""
    missing, cells = missing or {}, [f"c{i}" for i in range(n)]
    scoreable_ids = set(range(n)) if scoreable is None else scoreable
    values = {f: {c: (None if i in missing.get(f, set()) else float((raw or {}).get(f, list(range(n)))[i]))
                  for i, c in enumerate(cells)} for f in FACTORS}
    model = CityModel(1, "test", {c: {} for c in cells}, {cells[i] for i in scoreable_ids}, values)
    for f in FACTORS:
        model.sorted_values[f] = sorted(v for c, v in values[f].items() if c in model.scoreable and v is not None)
    return model, cells


def test_percentile_is_midrank_and_competition_is_inverted():
    model, cells = _city(raw={"competition": [0] * 10 + list(range(1, 11))})
    # 10 cells tied at 0 share one percentile; for competition, fewer shops = better.
    assert model.normalized("competition", cells[0]) == model.normalized("competition", cells[9]) == 75.0
    assert model.normalized("demand", cells[19]) > model.normalized("demand", cells[0])
    assert model.normalized("competition", cells[19]) < model.normalized("competition", cells[0])


def test_missing_factor_is_excluded_and_weights_renormalised_not_scored_as_zero():
    model, cells = _city(missing={"cannibalisation": set(range(20))})  # 15% of weight missing everywhere
    area = score_area(model, cells)
    assert area["status"] == "scored"
    can = next(f for f in area["factors"] if f["factor"] == "cannibalisation")
    assert can["provenance"] == "missing" and can["normalized"] is None and can["contribution"] is None
    assert sum(f["effective_weight"] for f in area["factors"]) == pytest.approx(100, abs=0.2)
    # Every remaining factor sits at the middle of its distribution, so the score is ~50 — had
    # the missing factor counted as 0, it would be ~42.5.
    assert area["score"] == pytest.approx(50, abs=1)


def test_too_much_missing_weight_gives_facts_only():
    model, cells = _city(missing={"demand": set(range(20)), "competition": set(range(20))})  # 50% > 40%
    area = score_area(model, cells)
    assert area["status"] == "facts_only" and area["score"] is None and area["rating"] is None
    assert "50%" in area["reason"]


def test_mostly_unscoreable_selection_is_insufficient_data():
    model, cells = _city(scoreable={0, 1, 2})
    area = score_area(model, cells)
    assert area["status"] == "insufficient_data" and area["score"] is None and area["factors"] == []


def test_partially_missing_factor_counts_only_above_coverage_threshold():
    model, cells = _city(missing={"demand": set(range(12))})  # 8 of 20 cells have demand (40% < 50%)
    demand = next(f for f in score_area(model, cells)["factors"] if f["factor"] == "demand")
    assert demand["provenance"] == "missing" and demand["coverage"] == 0.4


def test_contributions_add_up_to_the_score():
    model, cells = _city()
    area = score_area(model, cells[10:])
    assert area["score"] == pytest.approx(sum(f["contribution"] for f in area["factors"]), abs=0.2)
    assert area["confidence"] == "High"  # proxy demand + lower-bound competition still ≥ 0.75
