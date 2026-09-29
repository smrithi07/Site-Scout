"""The `study_rollup` job: collect → aggregate → save. `collect` freezes the lanes and captures as
they are now (JSON), `aggregate` is pure, `save` writes the immutable summary version and completes
the study. Payload: {"study_id": int, "trigger": "all_units_submitted" | "closed_early" | "reuse_only" | "rerun"}."""
from app.jobs.context import Step, StepContext
from app.models import Study
from app.services import rollup


def collect(ctx: StepContext) -> dict:
    study = ctx.db.get(Study, ctx.payload["study_id"])
    if study is None:
        raise ValueError(f"study {ctx.payload['study_id']} no longer exists")
    if study.status == "cancelled":
        raise ValueError(f"study {study.id} was cancelled; nothing to roll up")
    return rollup.collect(ctx.db, study)


def aggregate(ctx: StepContext) -> dict:
    return rollup.aggregate(ctx.outputs["collect"], rollup._cfg())


def save(ctx: StepContext) -> dict:
    s = rollup.save(ctx.db, ctx.payload["study_id"], ctx.outputs["aggregate"], ctx.payload["trigger"], ctx.job_id)
    return {"summary_id": s.id, "version": s.version, "confidence": s.confidence, "facts_only": s.facts_only}


STEPS: list[tuple[str, Step]] = [("collect", collect), ("aggregate", aggregate), ("save", save)]
