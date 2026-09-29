"""The `property_evaluation` job: load → evaluate → diff → narrative → save. `load` freezes the
property's fields, its latest completed catchment summary and the previous evaluation as they are
now, so an edit arriving mid-job gets its own next version instead of mixing inputs. `diff` is
pure code; `narrative` only phrases it (LLM chain with validator, template fallback — never raises).
Payload: {"property_id": int, "trigger": "created" | "edited" | "manual" | "study_complete"}."""
from sqlalchemy import func, select, text

from app.core import audit
from app.core.config import load_config
from app.llm import adapter, diff_narrative
from app.llm.entities import known_entities
from app.jobs.context import Step, StepContext
from app.models import Property, PropertyEvaluation
from app.schemas.properties import PropertyFields
from app.services import diff as diffs
from app.services import evaluation
from app.services.snapshots import active_snapshot

EXTRA_INPUTS = ("zone_no", "ward_no", "status", "warnings", "missing_fields", "duplicate_candidates", "version")


def load(ctx: StepContext) -> dict:
    p = ctx.db.get(Property, ctx.payload["property_id"])
    if p is None:
        raise ValueError(f"property {ctx.payload['property_id']} no longer exists")
    inputs = {k: getattr(p, k) for k in PropertyFields.model_fields}
    inputs.update({k: getattr(p, k) for k in EXTRA_INPUTS})
    summary = ctx.db.execute(text("""
        SELECT cs.id, cs.study_id, cs.version, cs.signals, cs.coverage, cs.anchors, cs.confidence, cs.facts_only
        FROM catchment_summaries cs JOIN studies s ON s.id = cs.study_id
        WHERE s.property_id = :p AND s.status = 'complete'
        ORDER BY s.id DESC, cs.version DESC LIMIT 1"""), dict(p=p.id)).mappings().one_or_none()
    prev = ctx.db.scalar(select(PropertyEvaluation).where(PropertyEvaluation.property_id == p.id)
                         .order_by(PropertyEvaluation.version.desc()).limit(1))
    return {"inputs": inputs, "snapshot_id": active_snapshot(ctx.db).id,
            "study": None if summary is None else {
                "study_id": summary["study_id"], "summary_id": summary["id"], "summary_version": summary["version"],
                "signals": summary["signals"], "coverage": summary["coverage"], "anchors": summary["anchors"],
                "confidence": summary["confidence"], "facts_only": summary["facts_only"]},
            "previous": None if prev is None else {k: getattr(prev, k) for k in (
                "version", "score", "outcome", "confidence", "factors", "risks", "hard_flags", "snapshot_id",
                "config_version", "summary_id")}}


def evaluate(ctx: StepContext) -> dict:
    o = ctx.outputs["load"]
    return evaluation.evaluate(ctx.db, o["inputs"], o["snapshot_id"], o["study"])


def diff(ctx: StepContext) -> dict:
    """What changed since the previous version, and why (pure code)."""
    o, result = ctx.outputs["load"], ctx.outputs["evaluate"]
    prev = o["previous"]
    if prev is None:
        return {"diff": None}
    new = {"version": prev["version"] + 1, "score": result["score"], "outcome": result["outcome"],
           "confidence": result["confidence"], "factors": result["factors"], "risks": result["risks"],
           "hard_flags": result["hard_flags"], "snapshot_id": o["snapshot_id"], "config_version": str(load_config()["version"])}
    study = o["study"]
    new_study = study if study and study["summary_id"] != prev.get("summary_id") else None
    summary = None if new_study is None else {"study_id": study["study_id"], "version": study["summary_version"],
                                              "signals": study["signals"], "coverage": study["coverage"],
                                              "anchors": study["anchors"], "confidence": study["confidence"],
                                              "facts_only": study["facts_only"]}
    return {"diff": diffs.diff(prev, new, summary)}


def narrative(ctx: StepContext) -> dict:
    d = ctx.outputs["diff"]["diff"]
    if d is None:
        return {"narrative": None}
    sheet = diffs.fact_sheet(d, ctx.outputs["load"]["inputs"]["label"])
    r = adapter.narrate(sheet, entities=known_entities(ctx.db, ctx.outputs["load"]["snapshot_id"]), job_id=ctx.job_id,
                        spec=diff_narrative.spec())
    return {"narrative": r.narrative, "source": r.source,
            "meta": {"model": r.model, "cached": r.cached, "attempts": r.attempts, "fact_sheet": sheet}}


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
        inputs=o["inputs"], snapshot_id=o["snapshot_id"], config_version=str(load_config()["version"]), job_id=ctx.job_id,
        study_id=(o.get("study") or {}).get("study_id"), summary_id=(o.get("study") or {}).get("summary_id"))
    d = (ctx.outputs.get("diff") or {}).get("diff")
    if d is not None:
        d = {**d, "to_version": version}          # another version may have landed between diff and save
        n = ctx.outputs.get("narrative") or {}
        ev.diff, ev.narrative, ev.narrative_source, ev.narrative_meta = d, n.get("narrative"), n.get("source"), n.get("meta")
    ctx.db.add(ev)
    ctx.db.flush()
    # "current" only if nobody edited the property since `load`; otherwise its own job is queued.
    ctx.db.execute(text("""UPDATE properties SET evaluation_status = 'current'
                           WHERE id = :p AND version = :v AND latest_job_id = :j"""),
                   dict(p=pid, v=o["inputs"]["version"], j=ctx.job_id))
    audit.record(ctx.db, actor=None, entity_type="property", entity_id=pid, action="evaluated",
                 to_state=result["outcome"], reason=f"evaluation v{version} ({ctx.payload['trigger']})",
                 details={"score": result["score"], "hard_flags": [f["code"] for f in result["hard_flags"]],
                          "evaluation_id": ev.id, "study_id": ev.study_id,
                          "score_change": None if d is None else d["score"]["change"]})
    return {"evaluation_id": ev.id, "version": version, "outcome": result["outcome"]}


STEPS: list[tuple[str, Step]] = [("load", load), ("evaluate", evaluate), ("diff", diff), ("narrative", narrative),
                                 ("save", save)]
