"""A three-step job that exercises the machinery: failure injection, resume, heartbeats.
Payload: {"fail_at": step, "fail_times": n} fails that step on its first n attempts;
{"sleep_in": step, "sleep_seconds": s} makes a step slow (for heartbeat tests)."""
import time

from app.jobs.context import Step, StepContext


def _step(name: str) -> Step:
    def run(ctx: StepContext) -> dict:
        p = ctx.payload
        if p.get("sleep_in") == name:
            time.sleep(float(p.get("sleep_seconds", 0)))
        if p.get("fail_at") == name and ctx.attempt <= int(p.get("fail_times", 1)):
            raise RuntimeError(f"injected failure in {name} (attempt {ctx.attempt})")
        return {"step": name, "attempt": ctx.attempt, "saw_outputs_of": sorted(ctx.outputs)}

    return run


STEPS: list[tuple[str, Step]] = [(name, _step(name)) for name in ("prepare", "compute", "save")]
