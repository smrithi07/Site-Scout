"""Deterministic narrative from the fact sheet — the last link of the fallback chain, and the only
narrative until the LLM adapters land (Phase 4b). Same output shape as the LLM path."""


def _fmt(v: float | None) -> str:
    return "n/a" if v is None else (f"{v:.0f}" if float(v).is_integer() else f"{v}")


def narrate(sheet: dict) -> dict:
    area, result, facts = sheet["area"], sheet["result"], sheet["facts"]
    name = area["name"]

    if result["status"] != "scored":
        summary = f"{name}: no rating. {result['reason_no_rating']}"
    else:
        summary = (f"{name} scores {_fmt(result['score'])}/100 — {result['rating']} "
                   f"({result['confidence']} confidence), across {_fmt(area['area_km2'])} km².")

    why: list[str] = []
    scored = [f for f in sheet["factors"] if f["normalized_0_100"] is not None]
    for f in sorted(scored, key=lambda f: -(f["contribution_points"] or 0))[:2]:
        why.append(f"Strength — {f['name']}: {_fmt(f['normalized_0_100'])}/100 citywide, "
                   f"adding {_fmt(f['contribution_points'])} points.")
    for f in sorted(scored, key=lambda f: f["normalized_0_100"])[:1]:
        if f["normalized_0_100"] < 50:
            why.append(f"Weakness — {f['name']}: {_fmt(f['normalized_0_100'])}/100 citywide. {f['note']}")
    for f in sheet["factors"]:
        if f["normalized_0_100"] is None:
            why.append(f"Not scored — {f['name']}: no usable data here; its weight was redistributed.")
    if facts["nearest_savomart"]:
        n = facts["nearest_savomart"]
        why.append(f"Nearest Savomart: {n['name']}, {_fmt(n['km'])} km away.")

    where = [f"Hotspot {h['rank']} (ward {h['ward']}): score {_fmt(h['score'])}; strengths: "
             f"{', '.join(h['strengths'])}." for h in sheet["hotspots"]]
    if not where:
        where = ["No hotspots: no cell here has enough data to score."]

    caveats = list(sheet["caveats"]) + list(area["warnings"])
    if result["cells_masked"]:
        caveats.append(f"{result['cells_masked']} of {result['cells_total']} cells are not scoreable land "
                       f"({', '.join(result['masked_by'])}) and were left out.")
    return {"summary": summary, "why": why, "where_to_scout": where, "caveats": caveats}
