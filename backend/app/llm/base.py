"""Provider-neutral pieces: the error type the fallback chain reasons about, the reply shape, and
HTTP-status classification shared by every adapter."""
import re
from dataclasses import dataclass

import httpx

RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


class ProviderError(Exception):
    """`retryable` → worth one more try on the same provider (timeouts, 429, 5xx).
    Not retryable → move to the next provider now (bad key, bad request, unknown model, blocked)."""

    def __init__(self, message: str, *, retryable: bool, http_status: int | None = None,
                 retry_after: float | None = None):
        super().__init__(message)
        self.retryable, self.http_status, self.retry_after = retryable, http_status, retry_after


@dataclass(frozen=True)
class Reply:
    text: str
    http_status: int
    input_tokens: int | None
    output_tokens: int | None


def retry_after_seconds(response: httpx.Response) -> float | None:
    """Standard Retry-After header, or Google's RetryInfo `retryDelay: "23s"` in the error body."""
    header = response.headers.get("retry-after")
    if header:
        try:
            return float(header)
        except ValueError:
            pass
    match = re.search(r'"retryDelay"\s*:\s*"(\d+(?:\.\d+)?)s"', response.text)
    return float(match.group(1)) if match else None


def raise_for_status(response: httpx.Response, provider: str) -> None:
    if response.status_code < 400:
        return
    retryable = response.status_code in RETRYABLE_STATUS
    raise ProviderError(f"{provider} HTTP {response.status_code}: {response.text[:300]}", retryable=retryable,
                        http_status=response.status_code,
                        retry_after=retry_after_seconds(response) if retryable else None)


def post(client: httpx.Client, provider: str, url: str, *, json: dict, headers: dict, timeout: httpx.Timeout) -> httpx.Response:
    """POST with network failures mapped to retryable ProviderErrors."""
    try:
        response = client.post(url, json=json, headers=headers, timeout=timeout)
    except httpx.TimeoutException as exc:
        raise ProviderError(f"{provider} timed out ({type(exc).__name__})", retryable=True) from exc
    except httpx.TransportError as exc:
        raise ProviderError(f"{provider} connection failed ({type(exc).__name__}: {exc})", retryable=True) from exc
    raise_for_status(response, provider)
    return response
