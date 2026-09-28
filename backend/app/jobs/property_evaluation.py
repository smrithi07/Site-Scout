"""The `property_evaluation` job: load → evaluate → save. `load` freezes the property's fields as they
are now, so an edit arriving mid-job gets its own next version instead of mixing inputs.
Payload: {"property_id": int, "trigger": "created" | "edited" | "manual" | "study_complete"}."""
from sqlalchemy import func, select, text

from app.core import audit
from app.core.config import load_config
from app.jobs.context import Step, StepContext
from app.models import Property, PropertyEvaluation
from app.schemas.properties import PropertyFields
from app.services import evaluation
from app.services.snapshots import active_snapshot

EXTRA_INPUTS = ("zone_no", "ward_no", "status", "warnings", "missing_fields", "duplicate_candidates", "version")


def load(ctx: StepContext) -> dict:
    p = ctx.db.get(Property, ctx.payload["property_id"])
    if p is None:
        raise ValueError(f"property {ctx.payload['property_id']} no longer exists")
    inputs = {k: getattr(p, k) for k in PropertyFields.model_fields}
    inputs.update({k: getattr(p, k) for k in EXTRA_INPUTS})
    return {"inputs": inputs, "snapshot_id": active_snapshot(ctx.db).id}


def evaluate(ctx: StepContext) -> dict:
    o = ctx.outputs["load"]
    return evaluation.evaluate(ctx.db, o["inputs"], o["snapshot_id"])


def save(ctx: StepContext) -> dict:
    o, result = ctx.outputs["load"], ctx.outputs["evaluate"]
    pid = ctx.payload["property_id"]
    ctx.db.execute(text("SELECT pg_advisory_xact_lock(hashtext('property_eval:' || :p))"), dict(p=str(pid)))
    version = (ctx.db.scalar(select(func.max(PropertyEvaluation.version)).where(PropertyEvaluation.property_id == pid)) or 0) + 1
    ev = PropertyEvaluation(
        property_id=pid, version=version, property_version=o["inputs"]["version"], trigger=ctx.payload["trigger"],
        outcome=result["outcome"], score=result["score"], confidence=result["confidence"],
        hard_flags=result["hard_flags"], risks=result["risks"],
        factors=result["factors"], completeness={**result["completeness"], "outcome_reasons": result["outcome_reasons"],
                                                 "provisional": result["provisional"], "rent": result["rent"],
                                                 "missing_weight_fraction": result["missing_weight_fraction"],
                                                 "cell": result["cell"]},
        inputs=o["inputs"], snapshot_id=o["snapshot_id"], config_version=str(load_config()["version"]), job_id=ctx.job_id)
    ctx.db.add(ev)
    ctx.db.flush()
    # "current" only if nobody edited the property since `load`; otherwise its own job is queued.
    ctx.db.execute(text("""UPDATE properties SET evaluation_status = 'current'
                           WHERE id = :p AND version = :v AND latest_job_id = :j"""),
                   dict(p=pid, v=o["inputs"]["version"], j=ctx.job_id))
    audit.record(ctx.db, actor=None, entity_type="property", entity_id=pid, action="evaluated",
                 to_state=result["outcome"], reason=f"evaluation v{version} ({ctx.payload['trigger']})",
                 details={"score": result["score"], "hard_flags": [f["code"] for f in result["hard_flags"]],
                          "evaluation_id": ev.id})
    return {"evaluation_id": ev.id, "version": version, "outcome": result["outcome"]}


STEPS: list[tuple[str, Step]] = [("load", load), ("evaluate", evaluate), ("save", save)]
