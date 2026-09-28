"""Live check of one provider against a saved report's fact sheet (costs at most
`attempts_per_provider` calls; a repeat run is served from the cache for free).

    python -m app.llm.smoke --report 3 --provider gemini
"""
import argparse
import json

from app.core.db import SessionLocal
from app.llm import adapter, calls
from app.llm.entities import known_entities
from app.models import AreaReport


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m app.llm.smoke")
    ap.add_argument("--report", type=int, required=True)
    ap.add_argument("--provider", choices=list(adapter.PROVIDERS), required=True)
    args = ap.parse_args()
    providers = [p for p in adapter.configured_providers() if p.name == args.provider]
    if not providers:
        raise SystemExit(f"{args.provider} is not configured (key/model missing in .env)")
    with SessionLocal() as db:
        report = db.get(AreaReport, args.report)
        if report is None:
            raise SystemExit(f"no area report {args.report}")
        sheet, entities = report.result["fact_sheet"], known_entities(db, report.snapshot_id)
    result = adapter.narrate(sheet, entities=entities, providers=providers, purpose="smoke_test")
    print(f"source={result.source} model={result.model} cached={result.cached}")
    print("attempts:", json.dumps(result.attempts, indent=1))
    print(json.dumps({k: result.narrative[k] for k in ("summary", "why", "where_to_scout")}, indent=1, ensure_ascii=False))
    print("usage (last 24h):", json.dumps(calls.stats(), default=str))


if __name__ == "__main__":
    main()
