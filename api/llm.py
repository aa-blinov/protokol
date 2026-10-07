"""OpenRouter chat completion over masked text.

Only the masked text is ever sent. The caller restores placeholders locally
afterwards, so original PII never crosses the network.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

import config

# Both come from config, which reads the environment — otherwise an override in
# .env would be silently ignored and the hardcoded value would always ship.
DEFAULT_MODEL = config.DEFAULT_LLM_MODEL
OPENROUTER_BASE_URL = config.OPENROUTER_BASE_URL
SYSTEM_PROMPT = (
    "Ты — аналитик банковских звонков. На вход приходит транскрипция разговора, "
    "в которой персональные данные заменены токенами вида [PERSON_1], [PHONE_1], "
    "[PASSPORT_1]. Сохраняй эти токены в ответе буквально, без изменений: "
    "не раскрывай и не перевирай их. Отвечай кратко и по-русски."
)


class LlmError(RuntimeError):
    """Raised when OpenRouter rejects the request or returns no content."""


@dataclass(frozen=True)
class LlmResult:
    reply: str
    model: str
    tokens_in: int | None
    tokens_out: int | None


class OpenRouterClient:
    def __init__(self, api_key: str, base_url: str = OPENROUTER_BASE_URL, timeout: float = 120.0):
        if not api_key:
            raise ValueError("OPENROUTER_API_KEY is empty")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def complete(self, masked_text: str, model: str = DEFAULT_MODEL, prompt: str | None = None) -> LlmResult:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt or masked_text},
            ],
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            response = httpx.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=headers,
                timeout=self.timeout,
            )
        except httpx.HTTPError as error:
            raise LlmError(f"OpenRouter request failed: {error}") from error

        if response.status_code != 200:
            raise LlmError(f"OpenRouter returned {response.status_code}: {response.text[:300]}")

        data = response.json()
        choices = data.get("choices") or []
        if not choices:
            raise LlmError("OpenRouter returned no choices")
        content = (choices[0].get("message") or {}).get("content")
        if not content:
            raise LlmError("OpenRouter returned empty content")

        usage = data.get("usage") or {}
        return LlmResult(
            reply=content,
            model=data.get("model", model),
            tokens_in=usage.get("prompt_tokens"),
            tokens_out=usage.get("completion_tokens"),
        )
