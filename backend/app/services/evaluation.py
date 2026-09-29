"""Deterministic property evaluation (docs/DESIGN.md §6). Same explainability as M1 — raw →
normalised → weight → points, with provenance — but at site level around the pin.

- Completeness is a gate, never a weight: missing rent or area → Needs Info (the score is still
  shown, labelled provisional). Too much missing weight → Needs Info.
- A hard flag (an operational Savomart within 400 m) caps the outcome one level.
- Risks are rule-based: rule id, severity, evidence. No LLM involved.
- After a catchment study, its summary's observed signals REPLACE the proxies for demand,
  competition and accessibility, and observed footfall joins as a new factor (config
  `evaluation.study`). A facts-only summary replaces nothing (and says so).
"""
from bisect import bisect_left, bisect_right
from statistics import mean

import h3
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import load_config
from app.services import scoring
from app.services.locate import rent_band
from app.services.properties import rent_per_sqft

FACTOR_META = {
    "site_demand": ("Site demand", "m² building footprint within ~600 m", "proxy", "Microsoft ML building footprints",
                    "Building footprint around the site, as a proxy for households nearby."),
    "competition": ("Competition", "grocery/convenience shops within ~650 m", "observed_lower_bound", "OpenStreetMap",
                    "Lower bound: OSM under-tags small kirana shops. Fewer is better."),
    "cannibalisation": ("Distance from Savomart", "m from the pin to the nearest operational store", "observed",
                        "Savomart Stores API (cached)", "Farther from an existing store is better."),
    "rent_affordability": ("Rent affordability", "₹ per sq ft per month", "mock", "entered rent vs illustrative zone band",
                           "Position of the rent within an ILLUSTRATIVE (mock) band for the zone; cheaper is better."),
    "accessibility": ("Accessibility", "road metres within ~350 m (main roads weighted)", "observed", "OpenStreetMap",
                      "Street density around the site."),
    "visibility": ("Visibility / frontage", "executive's rating and frontage", "observed_self_reported",
                   "executive assessment", "Self-reported on site."),
    "area_opportunity": ("Area opportunity", "M1 score of the pin's cell", "derived", "M1 scoring engine",
                         "The area score, used only as a low-weight context prior."),
}
LEVEL_ORDER = ["Strong Fit", "Consider", "Weak Fit"]
SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def _pct(sorted_values: list[float], v: float) -> float:
    lo, hi = bisect_left(sorted_values, v), bisect_right(sorted_values, v)
    return (lo + 0.5 * (hi - lo)) / len(sorted_values) * 100


def _cell_for(model: scoring.CityModel, lat: float, lon: float) -> str | None:
    """The pin's score cell; for pins on the GCC edge whose own cell isn't in the grid, the nearest one."""
    cell = h3.latlng_to_cell(lat, lon, load_config()["grid"]["score_res"])
    for k in range(3):
        ring = [c for c in h3.grid_ring(cell, k) if c in model.cells]
        if ring:
            return ring[0]
    return None


def _site_demand_table(model: scoring.CityModel, k: int) -> tuple[dict, list]:
    """Footprint within k rings for every cell, plus the sorted distribution over scoreable cells.
    Cached on the city model (one per snapshot + config)."""
    key = f"site_demand_k{k}"
    if key not in model.extras:
        cells = model.cells
        ring = {c: sum(cells[n]["ml_building_footprint_m2"] for n in h3.grid_disk(c, k) if n in cells) for c in cells}
        model.extras[key] = (ring, sorted(v for c, v in ring.items() if c in model.scoreable))
    return model.extras[key]


def evaluate(db: Session, inputs: dict, snapshot_id: int, study: dict | None = None) -> dict:
    """`study`: the latest Catchment Summary of the property's latest complete study, as stored
    (study_id, summary_id, summary_version, signals, facts_only, confidence, coverage) — or None."""
    cfg, sc = load_config()["evaluation"], load_config()["scoring"]
    model = scoring.city_model(db, snapshot_id)
    lat, lon = inputs["lat"], inputs["lon"]
    cell = _cell_for(model, lat, lon)
    band = rent_band(inputs.get("zone_no"))
    values: dict[str, tuple] = {}  # factor → (raw, normalised | None, note override | None)

    # Site demand (ring around the pin's cell vs the same measure citywide)
    ring, dist = _site_demand_table(model, cfg["site_ring_k"])
    if cell is not None and ring.get(cell):
        values["site_demand"] = (round(ring[cell]), round(_pct(dist, ring[cell]), 1), None)
    else:
        values["site_demand"] = (None, None, "No building footprints mapped around the pin.")

    # Competition + accessibility: the city model's neighbourhood measures for the pin's cell
    for f in ("competition", "accessibility"):
        n = model.normalized(f, cell) if cell else None
        values[f] = (round(model.raw[f].get(cell) or 0, 1) if n is not None else None, n, None)

    # Cannibalisation: exact distance from the pin
    store = db.execute(text("""
        SELECT store_code, name, ST_Distance(geom::geography, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography) AS d
        FROM stores WHERE snapshot_id = :s AND is_operational
        ORDER BY geom <-> ST_SetSRID(ST_MakePoint(:lon, :lat), 4326) LIMIT 1"""),
        dict(s=snapshot_id, lat=lat, lon=lon)).mappings().one_or_none()
    can_dist = model.sorted_values["cannibalisation"]
    if store and can_dist:
        capped = min(store["d"], sc["cannibalisation"]["max_distance_m"])
        values["cannibalisation"] = (round(store["d"]), round(_pct(can_dist, capped), 1), None)
    else:
        values["cannibalisation"] = (None, None, model.factor_notes.get("cannibalisation", "No Stores data."))

    # Rent affordability vs the illustrative band (cheaper → higher)
    per_sqft = rent_per_sqft(_Fields(inputs))
    if per_sqft:
        norm = max(0.0, min(100.0, 100 * (band["max"] - per_sqft) / (band["max"] - band["min"])))
        values["rent_affordability"] = (round(per_sqft, 1), round(norm, 1), None)
    else:
        values["rent_affordability"] = (None, None, "Rent or area not recorded (or rent 0).")

    # Visibility / frontage (executive's own assessment)
    parts = []
    if inputs.get("visibility"):
        parts.append(cfg["visibility_scores"][inputs["visibility"]])
    if inputs.get("frontage_ft"):
        lo, hi = cfg["frontage_ft"]["low"], cfg["frontage_ft"]["high"]
        parts.append(max(0.0, min(100.0, 100 * (inputs["frontage_ft"] - lo) / (hi - lo))))
    raw_vis = ", ".join(x for x in (inputs.get("visibility"), f"{inputs['frontage_ft']:g} ft frontage"
                                    if inputs.get("frontage_ft") else None) if x)
    values["visibility"] = (raw_vis or None, round(mean(parts), 1) if parts else None,
                            None if parts else "Visibility and frontage not recorded.")

    # Area opportunity (M1 cell score, low weight)
    cs = scoring.cell_score(model, cell, sc["weights"], sc["max_missing_weight_fraction"])[0] if cell else None
    values["area_opportunity"] = (cs, cs, None if cs is not None else "The pin's cell isn't scoreable land.")

    # Observed catchment signals replace proxies; footfall joins (docs/DESIGN.md §7 re-evaluation)
    weights = dict(cfg["weights"])
    meta = dict(FACTOR_META)
    replaced: list[str] = []
    if study and not study["facts_only"]:
        src = f"Catchment study #{study['study_id']} (summary v{study['summary_version']})"
        sig = study["signals"]
        for factor, key in cfg["study"]["replaces"].items():
            x = sig[key]
            if x["normalized"] is None:
                continue
            values[factor] = (x["value"], x["normalized"], None)
            meta[factor] = (FACTOR_META[factor][0], x["unit"], x["provenance"], src,
                            f"Observed on {x['lanes']} surveyed lanes; replaces the {FACTOR_META[factor][2].replace('_', ' ')} "
                            f"estimate ({FACTOR_META[factor][3]}).")
            replaced.append(factor)
        f = sig["footfall"]
        if f["normalized"] is not None:
            weights["footfall"] = cfg["study"]["footfall_weight"]
            values["footfall"] = (f["value"], f["normalized"], None)
            meta["footfall"] = ("Observed footfall", f["unit"], f["provenance"], src,
                                "Timed pedestrian counts on surveyed lanes — a factor only a study can supply."
                                + (" Counted in a single time band." if f.get("single_band") else ""))

    # Assemble: renormalise over available factors
    avail_w = sum(w for f, w in weights.items() if values[f][1] is not None)
    factors = []
    for f, w in weights.items():
        label, unit, prov, source, note = meta[f]
        raw, norm, override = values[f]
        eff = round(100 * w / avail_w, 1) if norm is not None and avail_w else 0.0
        factors.append({"factor": f, "label": label, "unit": unit, "source": source, "note": override or note,
                        "provenance": prov if norm is not None else "missing", "weight": w, "raw": raw,
                        "normalized": norm, "effective_weight": eff,
                        "contribution": round(eff * norm / 100, 1) if norm is not None else None})
    missing_fraction = 1 - avail_w / sum(weights.values())
    score = round(sum(f["contribution"] for f in factors if f["contribution"] is not None), 1) if avail_w else None
    q = sc["confidence"]["quality"]
    conf_value = sum(f["weight"] * q[f["provenance"]] for f in factors) / sum(weights.values())
    confidence = "High" if conf_value >= sc["confidence"]["high"] else "Medium" if conf_value >= sc["confidence"]["medium"] else "Low"

    # Completeness gate
    props_cfg = load_config()["properties"]
    critical_missing = [f for f in props_cfg["critical_fields"] if not inputs.get(f)]
    optional = ["frontage_ft", "road_width_ft", "visibility", "accessibility", "parking", "condition"]
    optional_missing = [f for f in optional if not inputs.get(f)] + (["photos"] if "photos" in inputs.get("missing_fields", []) else [])
    completeness = {"critical_missing": critical_missing, "optional_missing": optional_missing,
                    "complete_pct": round(100 * (1 - (len(critical_missing) + len(optional_missing)) /
                                                 (len(props_cfg["critical_fields"]) + len(optional) + 1)))}

    # Hard flags + risks
    hard_flags, risks = [], []
    if store and store["d"] < cfg["cannibalisation_hard_flag_m"]:
        hard_flags.append({"code": "store_too_close", "message": f"Savomart {store['name']} is {store['d']:.0f} m away "
                           f"(limit {cfg['cannibalisation_hard_flag_m']} m) — likely to cannibalise it."})
        risks.append({"rule_id": "R-CANNIBAL", "severity": "high", "message": hard_flags[-1]["message"],
                      "evidence": {"store_code": store["store_code"], "distance_m": round(store["d"])}})
    if critical_missing:
        risks.append({"rule_id": "R-DATA", "severity": "high", "message": f"Missing {', '.join(critical_missing)} — "
                      "can't judge affordability.", "evidence": {"missing": critical_missing}})
    if per_sqft and per_sqft > band["max"]:
        risks.append({"rule_id": "R-RENT-HIGH", "severity": "medium", "message": f"Rent ₹{per_sqft:.0f}/sq ft is above the "
                      f"illustrative band (₹{band['min']}–{band['max']}).", "evidence": {"per_sqft": round(per_sqft, 1), "band": band}})
    if any(w["code"] in ("rent_outlier", "rent_zero") for w in inputs.get("warnings", [])):
        risks.append({"rule_id": "R-RENT-UNVERIFIED", "severity": "medium", "message": "Rent looks wrong or unconfirmed "
                      "(outlier or zero) — verify amount and unit.", "evidence": {}})
    comp_raw = values["competition"][0]
    if "competition" in replaced:
        est = study["signals"]["competition"].get("estimated_catchment_count")
        if est is not None and est >= cfg["study"]["risks"]["competitors_many_observed"]:
            risks.append({"rule_id": "R-COMPETITION-OBSERVED", "severity": "medium", "message":
                          f"≈{est:.0f} grocery/food stores across the catchment (survey estimate; OSM lists "
                          f"{study['signals']['competition'].get('osm_count')}).", "evidence": {"estimate": est}})
    elif comp_raw is not None and comp_raw >= cfg["risks"]["competitors_many"]:
        risks.append({"rule_id": "R-COMPETITION", "severity": "medium", "message": f"{comp_raw:.0f} grocery/convenience "
                      "shops mapped within ~650 m (a lower bound).", "evidence": {"count": comp_raw}})
    if study:
        sr, sig = cfg["study"]["risks"], study["signals"]
        if study["facts_only"]:
            risks.append({"rule_id": "R-STUDY-THIN", "severity": "low", "message": "The catchment study covered too little "
                          "to score — the estimates were kept.", "evidence": {"coverage": study["coverage"].get("surveyed_share")}})
        else:
            if sig["footfall"]["normalized"] is not None and sig["footfall"]["normalized"] < sr["footfall_low_score"]:
                risks.append({"rule_id": "R-FOOTFALL-LOW", "severity": "medium", "message": f"Low observed footfall "
                              f"({sig['footfall']['value']:.0f} pedestrians per hour).", "evidence": {"per_hour": sig["footfall"]["value"]}})
            if sig["footfall"].get("single_band"):
                risks.append({"rule_id": "R-FOOTFALL-BAND", "severity": "low", "message": "Footfall was counted in a single "
                              "time band — other times of day are unobserved.", "evidence": {"bands": sig["footfall"].get("time_bands")}})
            poor = sig["accessibility"].get("share_poor")
            if poor is not None and poor >= sr["poor_access_share"]:
                risks.append({"rule_id": "R-ACCESS-OBSERVED", "severity": "medium", "message": f"{poor:.0%} of surveyed "
                              "lanes have poor pedestrian or vehicle access.", "evidence": {"share_poor": poor}})
    if inputs.get("status") == "possible_duplicate":
        risks.append({"rule_id": "R-DUPLICATE", "severity": "medium", "message": "Possible duplicate not yet resolved.",
                      "evidence": {"candidates": [c["id"] for c in inputs.get("duplicate_candidates", [])]}})
    if cell is not None and cell not in model.scoreable:
        risks.append({"rule_id": "R-LANDUSE", "severity": "medium", "message": "The pin's cell is mostly "
                      f"{model.cells[cell]['mask_reason']} land.", "evidence": {"cell": cell}})
    if inputs.get("visibility") == "poor":
        risks.append({"rule_id": "R-VISIBILITY", "severity": "medium", "message": "Visibility rated poor on site.", "evidence": {}})
    if inputs.get("road_width_ft") and inputs["road_width_ft"] < cfg["risks"]["road_width_narrow_ft"]:
        risks.append({"rule_id": "R-ROAD-NARROW", "severity": "low", "message": f"Road only {inputs['road_width_ft']:g} ft wide.",
                      "evidence": {"road_width_ft": inputs["road_width_ft"]}})
    if inputs.get("accessibility") == "poor":
        risks.append({"rule_id": "R-ACCESS", "severity": "low", "message": "Access rated poor on site.", "evidence": {}})
    if inputs.get("parking") == "none":
        risks.append({"rule_id": "R-PARKING", "severity": "low", "message": "No parking.", "evidence": {}})
    if any(w["code"] == "gps_poor" for w in inputs.get("warnings", [])):
        risks.append({"rule_id": "R-GPS", "severity": "low", "message": "Pin placed with poor GPS accuracy.", "evidence": {}})
    risks.sort(key=lambda r: SEVERITY_ORDER[r["severity"]])

    # Outcome
    reasons = []
    if critical_missing:
        outcome = "Needs Info"
        reasons.append(f"missing {', '.join(critical_missing)}")
    elif missing_fraction > cfg["max_missing_weight_fraction"]:
        outcome = "Needs Info"
        reasons.append(f"{missing_fraction:.0%} of the scoring weight has no data")
    else:
        outcome = next(b["label"] for b in cfg["outcome_bands"] if score >= b["min"])
        if hard_flags and outcome != LEVEL_ORDER[-1]:
            capped = LEVEL_ORDER[LEVEL_ORDER.index(outcome) + 1]
            reasons.append(f"capped from {outcome} to {capped} by hard flag")
            outcome = capped
    return {"outcome": outcome, "outcome_reasons": reasons, "score": score, "provisional": outcome == "Needs Info",
            "confidence": confidence, "factors": factors, "missing_weight_fraction": round(missing_fraction, 2),
            "hard_flags": hard_flags, "risks": risks, "completeness": completeness, "cell": cell,
            "rent": {"per_sqft": round(per_sqft, 1) if per_sqft else None, "band": band},
            "study": None if not study else {k: study[k] for k in ("study_id", "summary_id", "summary_version",
                                                                    "confidence", "facts_only")} | {"replaced": replaced}}


def review_card(p, ev) -> dict:
    """What a manager needs to decide in ~30 seconds (docs/DESIGN.md §6): rating, top three risks,
    rent vs band, completeness, duplicate flags. Full detail lives in the evaluation."""
    if ev is None:
        return {"evaluation_status": p.evaluation_status, "outcome": None}
    c = ev.completeness
    rent = c.get("rent") or {}
    band = rent.get("band") or {}
    per_sqft = rent.get("per_sqft")
    position = (None if per_sqft is None else "below band" if per_sqft < band["min"]
                else "above band" if per_sqft > band["max"] else "within band")
    return {"evaluation_status": p.evaluation_status, "evaluation_version": ev.version, "outcome": ev.outcome,
            "provisional": c.get("provisional", False), "outcome_reasons": c.get("outcome_reasons", []),
            "score": ev.score, "confidence": ev.confidence, "hard_flags": ev.hard_flags, "top_risks": ev.risks[:3],
            "rent_vs_band": {"per_sqft": per_sqft, "band": band, "position": position},
            "completeness": {k: c[k] for k in ("critical_missing", "optional_missing", "complete_pct")},
            "duplicate": {"status": p.status, "candidates": p.duplicate_candidates},
            "stale": p.evaluation_status == "pending" and ev.property_version != p.version}


class _Fields:
    """Attribute access over the inputs dict (for rent_per_sqft)."""

    def __init__(self, d: dict):
        self.__dict__.update({k: d.get(k) for k in ("monthly_rent", "rent_unit", "area_sqft")})
