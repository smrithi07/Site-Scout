"""Job kinds → ordered steps. M2/M3 add their kinds here (property_evaluation, …)."""
from app.jobs import area_report, selftest
from app.jobs.context import Step

KINDS: dict[str, list[tuple[str, Step]]] = {
    "selftest": selftest.STEPS,
    "area_report": area_report.STEPS,
}
