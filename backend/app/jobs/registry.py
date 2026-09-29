"""Job kinds → ordered steps. M3 adds its kinds here (study planning, roll-up, …).

Loaded lazily: job modules import services, and services enqueue jobs — importing every kind at
module import time would make that a cycle."""
from functools import cache

from app.jobs.context import Step


@cache
def kinds() -> dict[str, list[tuple[str, Step]]]:
    from app.jobs import area_report, property_evaluation, selftest, study_rollup
    return {
        "selftest": selftest.STEPS,
        "area_report": area_report.STEPS,
        "property_evaluation": property_evaluation.STEPS,
        "study_rollup": study_rollup.STEPS,
    }
