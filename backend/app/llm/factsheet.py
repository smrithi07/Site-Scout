"""The fact sheet: the only thing a narrative (template or LLM) may draw on (Core rule 7). Every
number is pre-rounded to the form it should appear in, so the 4b validator can check that each
number and name in a narrative traces back to this sheet."""


def build_fact_sheet(resolved: dict, area: dict, hotspots: list[dict], facts: dict) -> dict:
    nearest = facts.get("nearest_savomart")
    sheet = {
        "area": {"name": resolved["label"], "area_km2": resolved["area_km2"],
                 "boundary": resolved["basis"]["label"], "zones": facts["zones"], "wards": facts["wards"][:12],
                 "pincodes": facts["pincodes"], "warnings": resolved["warnings"]},
        "result": {"status": area["status"], "score": area["score"], "rating": area["rating"],
                   "confidence": area["confidence"], "reason_no_rating": area.get("reason"),
                   "cells_total": area["cells_total"], "cells_scoreable": area["cells_scoreable"],
                   "cells_masked": area["cells_masked"], "masked_by": facts["masked_by"]},
        "factors": [{"name": f["label"], "normalized_0_100": f["normalized"], "weight_pct": f.get("effective_weight"),
                     "contribution_points": f.get("contribution"), "raw": f["raw"], "raw_unit": f["unit"],
                     "data": f["provenance"], "note": f["note"]}
                    for f in area.get("factors", [])],
        "hotspots": [{"rank": i + 1, "score": h["score"], "ward": h["ward_no"],
                      "strengths": [f"{r['label']} ({r['normalized']:.0f}/100)" for r in h["reasons"]],
                      "nearest_savomart_km": round(h["facts"]["nearest_store_m"] / 1000, 1)
                      if h["facts"]["nearest_store_m"] is not None else None}
                     for i, h in enumerate(hotspots)],
        "facts": {"buildings_ml": facts["ml_buildings"], "buildings_osm": facts["osm_buildings"],
                  "grocery_competitors_osm": facts["competitors"]["count"],
                  "competitor_examples": facts["competitors"]["examples"],
                  "anchors": {k: v["count"] for k, v in facts["anchors"].items()},
                  "road_km": facts["road_km"], "main_road_km": facts["main_road_km"],
                  "savomart_stores_inside": [s["name"] for s in facts["savomart_stores_inside"]],
                  "nearest_savomart": {"name": nearest["name"], "km": round(nearest["distance_m"] / 1000, 1),
                                       "stores_within_radius": nearest["within_radius"]} if nearest else None},
        "caveats": ["Competition counts come from OpenStreetMap and are a lower bound: small kirana shops "
                    "are under-mapped.",
                    "Demand is estimated from building footprints (a proxy), not a population count.",
                    f"Area boundary: {resolved['basis']['label']}."],
        "data_as_of": facts["data_as_of"],
    }
    return sheet
