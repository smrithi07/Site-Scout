"""Google Gemini (generateContent REST API) with JSON-constrained output."""
import httpx

from app.llm.base import ProviderError, Reply, post
from app.llm.prompt import OUTPUT_SCHEMA

URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class Gemini:
    name = "gemini"

    def __init__(self, api_key: str, model: str, client: httpx.Client):
        self.api_key, self.model, self.client = api_key, model, client

    def generate(self, system: str, user: str, cfg: dict, timeout: httpx.Timeout) -> Reply:
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"temperature": cfg["temperature"], "maxOutputTokens": cfg["max_output_tokens"],
                                 "responseMimeType": "application/json", "responseSchema": OUTPUT_SCHEMA},
        }
        r = post(self.client, self.name, URL.format(model=self.model), json=body,
                 headers={"x-goog-api-key": self.api_key}, timeout=timeout)
        data = r.json()
        candidates = data.get("candidates") or []
        if not candidates:
            reason = (data.get("promptFeedback") or {}).get("blockReason", "no candidates")
            raise ProviderError(f"gemini returned no answer ({reason})", retryable=False, http_status=r.status_code)
        parts = (candidates[0].get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        usage = data.get("usageMetadata") or {}
        return Reply(text, r.status_code, usage.get("promptTokenCount"), usage.get("candidatesTokenCount"))
