"""Groq (OpenAI-compatible chat completions) with JSON-object output."""
import httpx

from app.llm.base import ProviderError, Reply, post

URL = "https://api.groq.com/openai/v1/chat/completions"


class Groq:
    name = "groq"

    def __init__(self, api_key: str, model: str, client: httpx.Client):
        self.api_key, self.model, self.client = api_key, model, client

    def generate(self, system: str, user: str, cfg: dict, timeout: httpx.Timeout) -> Reply:
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": cfg["temperature"],
            "max_completion_tokens": cfg["max_output_tokens"],
            "response_format": {"type": "json_object"},
        }
        if self.model.startswith("openai/gpt-oss"):
            body["reasoning_effort"] = "low"  # phrasing, not problem-solving: keep hidden tokens down
        r = post(self.client, self.name, URL, json=body, headers={"Authorization": f"Bearer {self.api_key}"},
                 timeout=timeout)
        data = r.json()
        choices = data.get("choices") or []
        if not choices:
            raise ProviderError("groq returned no choices", retryable=False, http_status=r.status_code)
        usage = data.get("usage") or {}
        return Reply(choices[0]["message"].get("content") or "", r.status_code,
                     usage.get("prompt_tokens"), usage.get("completion_tokens"))
