"""Job kinds → ordered steps. M1/M2/M3 add their kinds here (area_report, property_evaluation, …)."""
from app.jobs import selftest
from app.jobs.context import Step

KINDS: dict[str, list[tuple[str, Step]]] = {
    "selftest": selftest.STEPS,
}
