"""The `area_report` job (docs/DESIGN.md §5): resolve → gather → score → hotspots → narrative →
validate → save. Each step's output is persisted, so a failure (e.g. in narrative) resumes there
without recomputing the rest. Payload: {"selection": {...}, "actor_id": int}."""
from app.jobs.context import Step, StepContext
from app.llm import adapter, template, validator
from app.llm.entities import known_entities
from app.llm.factsheet import build_fact_sheet
from app.models import User
from app.services import area_report, scoring, selection


def resolve(ctx: StepContext) -> dict:
    return selection.resolve(ctx.db, selection.Selection(**ctx.payload["selection"]))


def gather(ctx: StepContext) -> dict:
    r = ctx.outputs["resolve"]
    return area_report.gather_facts(ctx.db, r["snapshot_id"], r["score_cells"])


def score(ctx: StepContext) -> dict:
    r = ctx.outputs["resolve"]
    return scoring.score_area(scoring.city_model(ctx.db, r["snapshot_id"]), r["score_cells"])


def hotspots(ctx: StepContext) -> dict:
    area = ctx.outputs["score"]
    if area["status"] != "scored":
        return {"hotspots": []}
    return {"hotspots": scoring.hotspots(scoring.city_model(ctx.db, area["snapshot_id"]), area)}


def narrative(ctx: StepContext) -> dict:
    """LLM chain (cache → Gemini → Groq → template); never raises. Paid-for answers are logged and
    cached outside this step's transaction, so a crash here doesn't cost a second API call."""
    o = ctx.outputs
    sheet = build_fact_sheet(o["resolve"], o["score"], o["hotspots"]["hotspots"], o["gather"])
    result = adapter.narrate(sheet, entities=known_entities(ctx.db, o["resolve"]["snapshot_id"]), job_id=ctx.job_id)
    return {"fact_sheet": sheet, "narrative": result.narrative, "source": result.source, "model": result.model,
            "cached": result.cached, "attempts": result.attempts}


def validate(ctx: StepContext) -> dict:
    """Independent re-check of whatever the narrative step chose (defence in depth). The template
    is built only from the sheet; anything else must pass the validator or is replaced by it."""
    n = ctx.outputs["narrative"]
    if n["source"] == "template":
        return {"source": "template", "narrative": n["narrative"], "valid": True, "checked": "by construction"}
    errors = validator.validate(n["narrative"], n["fact_sheet"], known_entities(ctx.db, ctx.outputs["resolve"]["snapshot_id"]))
    if errors:
        return {"source": "template", "narrative": template.narrate(n["fact_sheet"]), "valid": False,
                "checked": "replaced by template", "errors": errors}
    return {"source": n["source"], "narrative": n["narrative"], "valid": True, "checked": "validator passed"}


def save(ctx: StepContext) -> dict:
    o = ctx.outputs
    actor = ctx.db.get(User, ctx.payload["actor_id"]) if ctx.payload.get("actor_id") else None
    meta = {k: o["narrative"].get(k) for k in ("model", "cached", "attempts")}
    meta.update({k: o["validate"].get(k) for k in ("valid", "checked", "errors")})
    report = area_report.save_report(
        ctx.db, resolved=o["resolve"], area=o["score"], hotspots=o["hotspots"]["hotspots"], facts=o["gather"],
        fact_sheet=o["narrative"]["fact_sheet"], narrative=o["validate"]["narrative"],
        narrative_source=o["validate"]["source"], narrative_meta=meta, job_id=ctx.job_id, actor=actor)
    return {"report_id": report.id, "area_key": report.area_key, "version": report.version}


STEPS: list[tuple[str, Step]] = [("resolve", resolve), ("gather", gather), ("score", score), ("hotspots", hotspots),
                                 ("narrative", narrative), ("validate", validate), ("save", save)]
