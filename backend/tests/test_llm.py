"""Phase 4b checkpoint: the narrative chain spends API calls carefully and always ends with a
narrative. Providers are the real Gemini/Groq adapters over fake HTTP transports — zero quota used."""
import json
import uuid

import httpx
import pytest
from sqlalchemy import text

from app.core.auth import Role
from app.core.db import SessionLocal, engine
from app.jobs import queue
from app.jobs.worker import run_once
from app.llm import adapter, template
from app.llm.gemini import Gemini
from app.llm.groq import Groq
from app.llm.validator import validate
from app.models import AreaReport, User
from tests.conftest import USER_IDS

CFG = {"prompt_version": "test-v1", "cache": True, "temperature": 0.2, "max_output_tokens": 500,
       "connect_timeout_s": 1, "read_timeout_s": 2, "attempts_per_provider": 2, "backoff_base_s": 0.01,
       "backoff_max_s": 0.02, "total_budget_s": 10, "min_interval_s": {"gemini": 0, "groq": 0},
       "circuit_breaker": {"failures": 3, "cooldown_s": 60}}
PURPOSE = "test_narrative"


@pytest.fixture(autouse=True)
def cleanup():
    yield
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM llm_calls WHERE purpose = :p"), dict(p=PURPOSE))


def sheet() -> dict:
    """A small but realistic fact sheet; unique per test so cache entries don't leak across tests."""
    return {"area": {"name": f"Pincode 600017 · T Nagar [{uuid.uuid4().hex}]", "area_km2": 4.75, "zones": ["Kodambakkam"],
                     "wards": [113, 133], "pincodes": ["600017"], "warnings": [], "boundary": "approximate"},
            "result": {"status": "scored", "score": 65.8, "rating": "Moderate fit", "confidence": "High",
                       "reason_no_rating": None, "cells_total": 42, "cells_scoreable": 42, "cells_masked": 0,
                       "masked_by": {}},
            "factors": [{"name": "Demand", "normalized_0_100": 68.4, "weight_pct": 30.0, "contribution_points": 20.5,
                         "raw": 39656.1, "raw_unit": "m²", "data": "proxy", "note": "Building footprint proxy."},
                        {"name": "Competition", "normalized_0_100": 16.2, "weight_pct": 20.0,
                         "contribution_points": 3.2, "raw": 5.9, "raw_unit": "shops", "data": "observed_lower_bound",
                         "note": "Lower bound."}],
            "hotspots": [{"rank": 1, "score": 75.4, "ward": 133, "strengths": ["Demand (94/100)"],
                          "nearest_savomart_km": 7.9}],
            "facts": {"nearest_savomart": {"name": "Example Nagar, Sample Town", "km": 8.1}},
            "caveats": ["Competition is a lower bound."], "data_as_of": {}}


GOOD = {"summary": "T Nagar scores 65.8/100, a Moderate fit with High confidence.",
        "why": ["Demand is strong at 68.4/100.", "Competition is weak at 16.2/100 (a lower bound)."],
        "where_to_scout": ["Hotspot 1 in ward 133 scores 75.4, strong on demand (94/100)."]}


class Fake:
    """Scripted HTTP responses for one provider; records every request body."""

    def __init__(self, provider: str, script: list):
        self.provider, self.script, self.requests = provider, list(script), []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(json.loads(request.content))
        step = self.script.pop(0) if self.script else 500
        if isinstance(step, Exception):
            raise step
        if isinstance(step, int):
            return httpx.Response(step, json={"error": {"message": "scripted"}})
        if isinstance(step, tuple):  # (status, headers)
            return httpx.Response(step[0], headers=step[1], json={"error": {}})
        body = json.dumps(step)
        if self.provider == "gemini":
            return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": body}]}}],
                                             "usageMetadata": {"promptTokenCount": 900, "candidatesTokenCount": 120}})
        return httpx.Response(200, json={"choices": [{"message": {"content": body}}],
                                         "usage": {"prompt_tokens": 900, "completion_tokens": 120}})

    def provider_obj(self):
        client = httpx.Client(transport=httpx.MockTransport(self.handler))
        return (Gemini if self.provider == "gemini" else Groq)("test-key", f"{self.provider}-test", client)


def run(s: dict, gemini: list, groq: list | None = None, cfg: dict | None = None):
    g, q = Fake("gemini", gemini), Fake("groq", groq or [])
    providers = [g.provider_obj()] + ([q.provider_obj()] if groq is not None else [])
    return adapter.narrate(s, entities=["Adyar", "Example Nagar, Sample Town", "Kodambakkam"], providers=providers,
                           cfg=cfg or CFG, purpose=PURPOSE), g, q


def test_success_uses_provider_and_keeps_code_owned_caveats():
    s = sheet()
    res, g, _ = run(s, [GOOD])
    assert (res.source, res.cached, len(g.requests)) == ("gemini", False, 1)
    assert res.narrative["summary"] == GOOD["summary"]
    assert res.narrative["caveats"] == template.narrate(s)["caveats"]  # not the model's to drop


def test_same_fact_sheet_is_served_from_cache_without_a_call():
    s = sheet()
    run(s, [GOOD])
    res, g, _ = run(s, [500])  # would fail if it called out
    assert (res.source, res.cached, len(g.requests)) == ("gemini", True, 0)


def test_rate_limited_then_retried_honouring_retry_after():
    res, g, _ = run(sheet(), [(429, {"retry-after": "0"}), GOOD])
    assert res.source == "gemini" and len(g.requests) == 2


def test_transient_errors_exhaust_retry_then_fall_back_to_groq():
    res, g, q = run(sheet(), [503, httpx.ReadTimeout("slow")], [GOOD])
    assert res.source == "groq" and len(g.requests) == 2 and len(q.requests) == 1
    assert [a["status"] for a in res.attempts] == ["error", "error", "ok"]


def test_permanent_error_is_not_retried():
    res, g, q = run(sheet(), [401, GOOD], [GOOD])
    assert res.source == "groq" and len(g.requests) == 1  # bad key: no second try on gemini


def test_invented_number_is_rejected_and_retried_with_feedback():
    bad = {**GOOD, "summary": "T Nagar scores 72.3/100, a Moderate fit."}
    res, g, _ = run(sheet(), [bad, GOOD])
    assert res.source == "gemini" and len(g.requests) == 2
    retry_prompt = g.requests[1]["contents"][0]["parts"][0]["text"]
    assert "rejected" in retry_prompt and "72.3" in retry_prompt
    with engine.connect() as conn:
        assert conn.execute(text("SELECT status FROM llm_calls WHERE purpose = :p ORDER BY id"),
                            dict(p=PURPOSE)).scalars().all() == ["invalid", "ok"]


def test_forced_failure_everywhere_falls_back_to_template():
    s = sheet()
    res, g, q = run(s, [500, 500], [500, 500])
    assert res.source == "template" and res.narrative == template.narrate(s)
    assert (len(g.requests), len(q.requests)) == (2, 2)


def test_retry_after_longer_than_budget_skips_instead_of_waiting():
    res, g, q = run(sheet(), [(429, {"retry-after": "600"})], [GOOD])
    assert res.source == "groq" and len(g.requests) == 1
    assert any("exceeds time budget" in a.get("reason", "") for a in res.attempts)


def test_circuit_breaker_skips_a_failing_provider():
    cfg = {**CFG, "circuit_breaker": {"failures": 2, "cooldown_s": 60}}
    run(sheet(), [500, 500], [GOOD], cfg=cfg)        # 2 failures → gemini circuit opens
    res, g, q = run(sheet(), [GOOD], [GOOD], cfg=cfg)
    assert res.source == "groq" and len(g.requests) == 0
    assert res.attempts[0] == {"provider": "gemini", "status": "skipped", "reason": "circuit open"}


def test_validator_rules():
    s = sheet()
    assert validate(GOOD, s) == []
    assert validate({**GOOD, "summary": "Scores 66/100."}, s) == []                       # rounding a sheet number
    assert "numbers not in the fact sheet: 12" in validate({**GOOD, "why": ["12 new shops opened."]}, s)[0]
    assert "rating label" in validate({**GOOD, "summary": "A Strong fit."}, s)[0]
    assert "Adyar" in validate({**GOOD, "why": ["Better than Adyar."]}, s, ["Adyar"])[0]
    assert validate({"summary": "x", "why": "not a list", "where_to_scout": []}, s)
    assert validate(["not", "an", "object"], s) == ["answer is not a JSON object"]


def test_area_report_job_falls_back_to_template_and_records_why(monkeypatch):
    """The checkpoint, end to end: every provider fails → the report is still saved, written by the
    template, and says which attempts failed."""
    failing = [Fake("gemini", [500, 500]).provider_obj(), Fake("groq", [401]).provider_obj()]
    monkeypatch.setattr(adapter, "configured_providers", lambda: tuple(failing))
    monkeypatch.setattr(adapter, "load_config", lambda: {"llm": CFG})
    with SessionLocal() as db:
        job = queue.enqueue(db, "area_report", {"selection": {"mode": "pincode", "pincode": "600017"},
                                                "actor_id": USER_IDS[Role.BD_MANAGER]},
                            db.get(User, USER_IDS[Role.BD_MANAGER]), queue="test")
        db.commit()
        job_id = job.id
    try:
        assert run_once("w-test", {"queues": ["test"], "heartbeat_seconds": 1, "stale_after_seconds": 30,
                                   "max_attempts": 3}) == (job_id, "succeeded")
        with SessionLocal() as db:
            report = db.query(AreaReport).filter(AreaReport.job_id == job_id).one()
            meta = report.result["narrative_meta"]
            assert report.narrative_source == "template"
            assert [a["status"] for a in meta["attempts"]] == ["error", "error", "error", "ok"]
            assert validate({k: report.narrative[k] for k in ("summary", "why", "where_to_scout")},
                            report.result["fact_sheet"]) == []  # the template passes its own checker
    finally:
        with engine.begin() as conn:
            conn.execute(text("SET LOCAL sitescout.purge = 'on'"))
            conn.execute(text("DELETE FROM area_reports WHERE job_id = :j"), dict(j=job_id))
            conn.execute(text("DELETE FROM jobs WHERE id = :j"), dict(j=job_id))
            conn.execute(text("DELETE FROM llm_calls WHERE job_id = :j"), dict(j=job_id))
