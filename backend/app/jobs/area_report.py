"""The `area_report` job (docs/DESIGN.md §5): resolve → gather → score → hotspots → narrative →
validate → save. Each step's output is persisted, so a failure (e.g. in narrative) resumes there
without recomputing the rest. Payload: {"selection": {...}, "actor_id": int}."""
from app.jobs.context import Step, StepContext
from app.llm import template
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
    o = ctx.outputs
    sheet = build_fact_sheet(o["resolve"], o["score"], o["hotspots"]["hotspots"], o["gather"])
    # Phase 4b: LLM (Gemini → Groq) with retry, falling back to this template.
    return {"fact_sheet": sheet, "narrative": template.narrate(sheet), "source": "template"}


def validate(ctx: StepContext) -> dict:
    # Phase 4b: every number/name in an LLM narrative must trace to the fact sheet. The template
    # is built only from the sheet, so it passes by construction.
    return {"valid": True, "source": ctx.outputs["narrative"]["source"], "checked": "by construction (template)"}


def save(ctx: StepContext) -> dict:
    o = ctx.outputs
    actor = ctx.db.get(User, ctx.payload["actor_id"]) if ctx.payload.get("actor_id") else None
    report = area_report.save_report(
        ctx.db, resolved=o["resolve"], area=o["score"], hotspots=o["hotspots"]["hotspots"], facts=o["gather"],
        fact_sheet=o["narrative"]["fact_sheet"], narrative=o["narrative"]["narrative"],
        narrative_source=o["validate"]["source"], job_id=ctx.job_id, actor=actor)
    return {"report_id": report.id, "area_key": report.area_key, "version": report.version}


STEPS: list[tuple[str, Step]] = [("resolve", resolve), ("gather", gather), ("score", score), ("hotspots", hotspots),
                                 ("narrative", narrative), ("validate", validate), ("save", save)]
