"""v1 → v2 evaluation diff (docs/DESIGN.md §7 Property re-evaluation). Pure: two stored evaluation
snapshots in, an explained diff out. The LLM only narrates this; it never computes any of it.

Every factor change gets a primary cause (and all causes that apply):
  factor newly included — no score before, scored now (e.g. observed footfall after a study)
  factor dropped        — scored before, not now
  data change           — the factor's source, provenance or raw value changed, or the same raw
                          value normalises differently because the data snapshot changed
  config change         — the configured weight changed, or the same raw value normalises
                          differently under a new config version
  renormalization       — nothing about this factor changed; its effective weight moved only
                          because other factors came or went
The per-factor point changes add up to the score change (up to rounding), and the diff says so.
"""

CAUSE_ORDER = ["factor newly included", "factor dropped", "data change", "config change", "renormalization"]


def _num(v):
    return None if v is None else round(float(v), 1)


def _view(f: dict | None) -> dict | None:
    if f is None:
        return None
    return {k: f.get(k) for k in ("raw", "normalized", "weight", "effective_weight", "contribution", "provenance",
                                  "source", "unit")}


def factor_changes(old: dict, new: dict) -> list[dict]:
    before = {f["factor"]: f for f in old["factors"]}
    after = {f["factor"]: f for f in new["factors"]}
    snapshot_changed = old["snapshot_id"] != new["snapshot_id"]
    config_changed = old["config_version"] != new["config_version"]
    out = []
    for key in list(before) + [k for k in after if k not in before]:
        o, n = before.get(key), after.get(key)
        o_scored = o is not None and o.get("normalized") is not None
        n_scored = n is not None and n.get("normalized") is not None
        causes = []
        if n_scored and not o_scored:
            causes.append("factor newly included")
        elif o_scored and not n_scored:
            causes.append("factor dropped")
        elif o_scored and n_scored:
            if (o["source"], o["provenance"]) != (n["source"], n["provenance"]) or o["raw"] != n["raw"]:
                causes.append("data change")
            elif _num(o["normalized"]) != _num(n["normalized"]):
                causes.append("data change" if snapshot_changed or not config_changed else "config change")
            if o["weight"] != n["weight"]:
                causes.append("config change")
            if _num(o["effective_weight"]) != _num(n["effective_weight"]):
                causes.append("renormalization")            # primary only when nothing else changed
        if not causes:
            continue                                                  # unchanged (or unscored both times)
        c_before = (o or {}).get("contribution") or 0.0
        c_after = (n or {}).get("contribution") or 0.0
        label = (n or o)["label"]
        out.append({"factor": key, "label": label, "cause": min(causes, key=CAUSE_ORDER.index), "causes": causes,
                    "before": _view(o), "after": _view(n), "points_change": round(c_after - c_before, 1),
                    "explanation": _explain(label, min(causes, key=CAUSE_ORDER.index), o, n)})
    return sorted(out, key=lambda c: -abs(c["points_change"]))


def _explain(label: str, cause: str, o: dict | None, n: dict | None) -> str:
    if cause == "factor newly included":
        return f"{label} is scored for the first time ({n['provenance'].replace('_', ' ')}: {n['source']})."
    if cause == "factor dropped":
        return f"{label} has no usable data now; its weight was redistributed."
    if cause == "data change":
        if (o["source"], o["provenance"]) != (n["source"], n["provenance"]):
            scale = (" The scales differ: the estimate was ranked against all of Chennai; the study's value is "
                     "scored on uncalibrated thresholds — compare the observed facts, not just the points."
                     if n["source"].startswith("Catchment study") and not o["source"].startswith("Catchment study") else "")
            return (f"{label} now comes from {n['source']} ({n['provenance'].replace('_', ' ')}) instead of "
                    f"{o['source']} ({o['provenance'].replace('_', ' ')}).{scale}")
        return f"{label}'s underlying value changed."
    if cause == "config change":
        return f"{label}'s configured weight or scoring thresholds changed in the new config version."
    return f"{label} itself did not change; its share of the score moved because other factors came or went."


def diff(old: dict, new: dict, summary: dict | None = None) -> dict:
    """old/new: stored evaluation snapshots (version, score, outcome, confidence, factors, risks,
    hard_flags, snapshot_id, config_version). summary: the Catchment Summary that triggered `new`."""
    changes = factor_changes(old, new)
    old_risks = {r["rule_id"]: r for r in old["risks"]}
    new_risks = {r["rule_id"]: r for r in new["risks"]}
    score_change = (round(new["score"] - old["score"], 1) if old["score"] is not None and new["score"] is not None else None)
    explained = round(sum(c["points_change"] for c in changes), 1)
    facts = []
    if summary:
        sig, cov = summary["signals"], summary["coverage"]
        facts.append({"fact": "coverage", "text": f"{round(cov['surveyed_share'] * 100)}% of the catchment's road length surveyed",
                      "value": round(cov["surveyed_share"] * 100)})
        if sig["footfall"]["value"] is not None:
            facts.append({"fact": "footfall", "text": f"observed footfall {sig['footfall']['value']:.0f} pedestrians per hour",
                          "value": round(sig["footfall"]["value"])})
        comp = sig["competition"]
        if comp.get("estimated_catchment_count") is not None:
            facts.append({"fact": "competition", "text": f"≈{comp['estimated_catchment_count']:.0f} grocery/food stores in the "
                          f"catchment by survey, vs {comp['osm_count']} in OpenStreetMap",
                          "value": round(comp["estimated_catchment_count"]), "osm": comp["osm_count"]})
        if summary["anchors"]:
            facts.append({"fact": "anchors", "text": f"{len(summary['anchors'])} anchors found on surveyed lanes",
                          "value": len(summary["anchors"])})
    return {
        "from_version": old["version"], "to_version": new["version"],
        "score": {"before": old["score"], "after": new["score"], "change": score_change,
                  "explained_by_factors": explained,
                  "rounding_gap": None if score_change is None else round(score_change - explained, 1)},
        "outcome": {"before": old["outcome"], "after": new["outcome"], "changed": old["outcome"] != new["outcome"]},
        "confidence": {"before": old["confidence"], "after": new["confidence"]},
        "config": {"before": old["config_version"], "after": new["config_version"]},
        "snapshot": {"before": old["snapshot_id"], "after": new["snapshot_id"]},
        "factors": changes,
        "causes": {c: sum(1 for x in changes if x["cause"] == c) for c in CAUSE_ORDER if any(x["cause"] == c for x in changes)},
        "new_facts": facts,
        "new_risks": [new_risks[k] for k in new_risks if k not in old_risks],
        "resolved_risks": [old_risks[k] for k in old_risks if k not in new_risks],
        "hard_flags": {"before": [f["code"] for f in old["hard_flags"]], "after": [f["code"] for f in new["hard_flags"]]},
        "study": None if not summary else {"study_id": summary["study_id"], "summary_version": summary["version"],
                                           "confidence": summary["confidence"], "facts_only": summary["facts_only"]},
    }


def fact_sheet(d: dict, label: str) -> dict:
    """What the LLM may use to narrate the diff — numbers already computed, nothing else."""
    return {
        "property": label,
        "before": {"version": d["from_version"], "score": d["score"]["before"], "rating": d["outcome"]["before"],
                   "confidence": d["confidence"]["before"]},
        "after": {"version": d["to_version"], "score": d["score"]["after"], "rating": d["outcome"]["after"],
                  "confidence": d["confidence"]["after"]},
        "score_change": d["score"]["change"],
        "study": d["study"],
        "changes": [{"factor": c["label"], "cause": c["cause"], "normalized_before": (c["before"] or {}).get("normalized"),
                     "normalized_after": (c["after"] or {}).get("normalized"), "points_change": c["points_change"],
                     "explanation": c["explanation"]} for c in d["factors"][:6]],
        "new_facts": [f["text"] for f in d["new_facts"]],
        "new_risks": [r["message"] for r in d["new_risks"]],
        "resolved_risks": [r["message"] for r in d["resolved_risks"]],
        "caveats": ["Study scores use uncalibrated thresholds, while estimates are ranked against all of Chennai — "
                    "a factor that switched source is not measured on the same scale.",
                    "The per-factor point changes are computed by code."],
    }
