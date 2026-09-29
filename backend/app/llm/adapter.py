"""The narrative fallback chain (Core rule 7), built to spend API calls carefully:

  cache hit? → use it (no call)
  for each provider (LLM_PROVIDER, then LLM_FALLBACK_PROVIDER), unless its circuit is open:
      up to `attempts_per_provider` tries:
        transient error (timeout, 429, 5xx) → back off (honouring Retry-After) and retry
        permanent error (bad key/request/model)  → next provider immediately
        invalid JSON / validator rejects         → retry once with the checker's feedback
  → deterministic template (always succeeds)

A whole-chain time budget, per-provider minimum spacing between calls and a circuit breaker keep a
failing or rate-limited provider from eating the budget. Every attempt is logged in `llm_calls`.
This function never raises: the report always gets a narrative and records who wrote it."""
import hashlib
import json
import logging
import random
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache

import httpx

from app.core.config import load_config
from app.core.settings import get_settings
from app.llm import calls, prompt, template
from app.llm.base import ProviderError
from app.llm.gemini import Gemini
from app.llm.groq import Groq
from app.llm.validator import validate

log = logging.getLogger(__name__)
PROVIDERS = {"gemini": Gemini, "groq": Groq}


@dataclass
class NarrativeResult:
    narrative: dict
    source: str                      # gemini | groq | template
    model: str | None
    cached: bool
    attempts: list[dict] = field(default_factory=list)


class _Guards:
    """Per-process circuit breaker + call spacing (the worker is one process; each process
    guards its own calls)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.failures: dict[str, int] = {}
        self.open_until: dict[str, float] = {}
        self.last_call: dict[str, float] = {}

    def is_open(self, name: str) -> bool:
        with self.lock:
            return time.monotonic() < self.open_until.get(name, 0)

    def record(self, name: str, ok: bool, breaker: dict) -> None:
        with self.lock:
            if ok:
                self.failures[name] = 0
                return
            self.failures[name] = self.failures.get(name, 0) + 1
            if self.failures[name] >= breaker["failures"]:
                self.open_until[name] = time.monotonic() + breaker["cooldown_s"]
                self.failures[name] = 0
                log.warning("llm: circuit open for %s for %ss", name, breaker["cooldown_s"])

    def wait_turn(self, name: str, min_interval: float, remaining: float) -> bool:
        """Sleep until `min_interval` has passed since this provider's last call. False if that
        would exceed the remaining budget."""
        with self.lock:
            wait = self.last_call.get(name, 0) + min_interval - time.monotonic()
            if wait > remaining:
                return False
            if wait > 0:
                time.sleep(wait)
            self.last_call[name] = time.monotonic()
            return True


guards = _Guards()


@dataclass(frozen=True)
class NarrativeSpec:
    """What one kind of narrative needs from the chain: its prompt, output schema, validator,
    deterministic template, how to shape the final narrative (code-owned parts included), and the
    config key of its prompt version (part of the cache key)."""
    purpose: str
    prompt_version_key: str
    system: str
    schema: dict
    user_message: Callable[[dict, list[str] | None], str]
    validate: Callable[[object, dict, list[str] | None], list[str]]
    template: Callable[[dict], dict]
    finish: Callable[[dict, dict], dict]


AREA = NarrativeSpec(
    purpose="area_narrative", prompt_version_key="prompt_version", system=prompt.SYSTEM, schema=prompt.OUTPUT_SCHEMA,
    user_message=prompt.user_message, validate=validate, template=template.narrate,
    # The model writes summary/why/where; caveats always come from code.
    finish=lambda parsed, fallback: {"summary": parsed["summary"], "why": parsed["why"],
                                     "where_to_scout": parsed["where_to_scout"], "caveats": fallback["caveats"]})


@lru_cache
def configured_providers() -> tuple:
    """Built once per process (one pooled HTTP client per provider)."""
    s = get_settings()
    order = list(dict.fromkeys([s.llm_provider, s.llm_fallback_provider]))
    out = []
    for name in order:
        key, model = getattr(s, f"{name}_api_key", ""), getattr(s, f"{name}_model", "")
        if name in PROVIDERS and key and model:
            out.append(PROVIDERS[name](key, model, httpx.Client()))
    return tuple(out)


def sheet_hash(sheet: dict) -> str:
    return hashlib.sha256(json.dumps(sheet, sort_keys=True, default=str).encode()).hexdigest()


def _parse(text: str) -> object:
    text = text.strip()
    if text.startswith("```"):  # tolerate a fenced block despite JSON mode
        text = text.strip("`").removeprefix("json").strip()
    return json.loads(text)


def narrate(sheet: dict, *, entities: list[str] | None = None, job_id: int | None = None,
            providers: list | None = None, cfg: dict | None = None, purpose: str | None = None,
            spec: NarrativeSpec = AREA) -> NarrativeResult:
    cfg = cfg or load_config()["llm"]
    purpose = purpose or spec.purpose
    prompt_version = cfg[spec.prompt_version_key]
    providers = configured_providers() if providers is None else providers
    fallback = spec.template(sheet)
    digest, attempts = sheet_hash(sheet), []
    deadline = time.monotonic() + cfg["total_budget_s"]
    if not providers:
        attempts.append({"provider": "llm", "status": "skipped",
                         "reason": "no LLM provider configured (check *_API_KEY / *_MODEL in .env)"})

    def finish(parsed: dict, source: str, model: str | None, cached: bool) -> NarrativeResult:
        return NarrativeResult(spec.finish(parsed, fallback), source, model, cached, attempts)

    for p in providers:
        base = dict(purpose=purpose, provider=p.name, model=p.model, prompt_version=prompt_version,
                    sheet_sha256=digest, job_id=job_id)
        if cfg["cache"] and (hit := calls.cached(purpose, digest, p.name, p.model, prompt_version)):
            if not spec.validate(hit, sheet, entities):  # re-check: validator rules may have tightened
                calls.log(**base, attempt=0, status="cached")
                attempts.append({"provider": p.name, "status": "cached"})
                return finish(hit, p.name, p.model, cached=True)
        if guards.is_open(p.name):
            attempts.append({"provider": p.name, "status": "skipped", "reason": "circuit open"})
            continue

        feedback: list[str] | None = None
        for attempt in range(1, cfg["attempts_per_provider"] + 1):
            remaining = deadline - time.monotonic()
            if remaining <= 1 or not guards.wait_turn(p.name, cfg["min_interval_s"].get(p.name, 0), remaining):
                attempts.append({"provider": p.name, "status": "skipped", "reason": "time budget exhausted"})
                break
            timeout = httpx.Timeout(min(cfg["read_timeout_s"], max(deadline - time.monotonic(), 1)),
                                    connect=cfg["connect_timeout_s"])
            t0 = time.monotonic()
            try:
                reply = p.generate(spec.system, spec.user_message(sheet, feedback), cfg, timeout, schema=spec.schema)
            except ProviderError as exc:
                ms = int((time.monotonic() - t0) * 1000)
                calls.log(**base, attempt=attempt, status="error", http_status=exc.http_status, error=str(exc)[:1000],
                          latency_ms=ms)
                attempts.append({"provider": p.name, "attempt": attempt, "status": "error", "error": str(exc)[:200]})
                guards.record(p.name, False, cfg["circuit_breaker"])
                if not exc.retryable or attempt == cfg["attempts_per_provider"]:
                    break
                delay = exc.retry_after if exc.retry_after is not None else min(
                    cfg["backoff_base_s"] * 2 ** (attempt - 1), cfg["backoff_max_s"]) * (1 + random.random() / 4)
                if delay > deadline - time.monotonic() - 1:
                    attempts.append({"provider": p.name, "status": "skipped",
                                     "reason": f"retry-after {delay:.0f}s exceeds time budget"})
                    break
                time.sleep(delay)
                continue

            ms = int((time.monotonic() - t0) * 1000)
            usage = dict(latency_ms=ms, http_status=reply.http_status, input_tokens=reply.input_tokens,
                         output_tokens=reply.output_tokens)
            try:
                parsed = _parse(reply.text)
                errors = spec.validate(parsed, sheet, entities)
            except (json.JSONDecodeError, ValueError) as exc:
                parsed, errors = None, [f"answer is not valid JSON ({exc})"]
            if errors:
                calls.log(**base, **usage, attempt=attempt, status="invalid", validation_errors=errors,
                          response=parsed if isinstance(parsed, dict) else None)
                attempts.append({"provider": p.name, "attempt": attempt, "status": "invalid", "errors": errors})
                guards.record(p.name, False, cfg["circuit_breaker"])
                feedback = errors  # the retry is told exactly what to fix; no backoff needed
                continue

            calls.log(**base, **usage, attempt=attempt, status="ok", response=parsed)
            attempts.append({"provider": p.name, "attempt": attempt, "status": "ok", "latency_ms": ms})
            guards.record(p.name, True, cfg["circuit_breaker"])
            return finish(parsed, p.name, p.model, cached=False)

    attempts.append({"provider": "template", "status": "ok"})
    return NarrativeResult(fallback, "template", None, False, attempts)
