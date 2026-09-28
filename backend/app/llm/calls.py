"""`llm_calls`: log of every attempt + the response cache. Written on its own connection and
committed immediately, so the record (and the cache entry for a paid-for answer) survives even if
the job step that made the call later rolls back or crashes."""
from sqlalchemy import select, text

from app.core.db import SessionLocal, engine
from app.models import LlmCall


def log(**fields) -> None:
    with engine.begin() as conn:
        conn.execute(LlmCall.__table__.insert().values(**fields))


def cached(purpose: str, sheet_sha256: str, provider: str, model: str, prompt_version: str) -> dict | None:
    """The most recent validated response for exactly this fact sheet + provider + model + prompt."""
    with SessionLocal() as db:
        return db.scalar(select(LlmCall.response).where(
            LlmCall.purpose == purpose, LlmCall.sheet_sha256 == sheet_sha256, LlmCall.provider == provider,
            LlmCall.model == model, LlmCall.prompt_version == prompt_version, LlmCall.status == "ok",
        ).order_by(LlmCall.id.desc()).limit(1))


def stats(since_hours: int = 24) -> list[dict]:
    """Per provider/model outcome counts — how often each model fails or is rejected."""
    with engine.connect() as conn:
        return [dict(r) for r in conn.execute(text("""
            SELECT provider, model, status, count(*) AS n, round(avg(latency_ms)) AS avg_ms,
                   sum(input_tokens) AS input_tokens, sum(output_tokens) AS output_tokens
            FROM llm_calls WHERE created_at > now() - make_interval(hours => :h)
            GROUP BY 1, 2, 3 ORDER BY 1, 2, 3"""), dict(h=since_hours)).mappings()]
