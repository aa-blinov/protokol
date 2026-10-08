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

# The model receives a masked, speaker-labelled transcript and must produce a
# meeting protocol, keeping the placeholder tokens verbatim so the reply can be
# de-masked locally.
SYSTEM_PROMPT = (
    "Ты составляешь протокол рабочей встречи по её транскрипту. Строки вида "
    "«Спикер 2 [12:34]: …» — это реплики с временем. Персональные данные заменены "
    "токенами вида [PERSON_1], [PHONE_1], [PASSPORT_1]: сохраняй каждый токен "
    "дословно, не раскрывай и не перевирай его, ничего не выдумывай. Отвечай "
    "по-русски, по делу, и дай: суть встречи; ключевые обсуждённые пункты; "
    "принятые решения; задачи (что сделать, кто, срок — если это названо); "
    "открытые вопросы. Опирайся только на транскрипт."
)
# A long meeting is compressed part by part first, so a single request never has
# to carry a whole hour of transcript.
PARTIAL_PROMPT = (
    "Ниже фрагмент транскрипта встречи (реплики вида «Спикер N [время]: …»; "
    "персональные данные заменены токенами вида [PERSON_1]). Сожми фрагмент в "
    "тезисы, сохраняя токены дословно: факты, решения, задачи, упомянутые токены. "
    "Без вступлений и выводов."
)

# Up to this many characters the protocol is one request; beyond it, parts first.
MEETING_MAP_CHARS = 24_000
MEETING_CHUNK_CHARS = 8_000


def split_masked_text(text: str, max_chars: int = MEETING_CHUNK_CHARS) -> list[str]:
    """Split on line boundaries into chunks of at most ``max_chars`` characters."""
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for line in text.splitlines():
        if current and size + len(line) + 1 > max_chars:
            chunks.append("\n".join(current))
            current, size = [], 0
        current.append(line)
        size += len(line) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks or [text]


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

    def complete(
        self,
        masked_text: str,
        model: str = DEFAULT_MODEL,
        prompt: str | None = None,
        system: str = SYSTEM_PROMPT,
    ) -> LlmResult:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
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

    def complete_meeting(self, masked_text: str, model: str = DEFAULT_MODEL) -> LlmResult:
        """The meeting protocol. A long transcript is summarised in parts first,
        then the protocol is composed from those parts — every request carries
        masked text only, so the reply is de-masked locally as usual."""
        if len(masked_text) <= MEETING_MAP_CHARS:
            return self.complete(masked_text, model, system=SYSTEM_PROMPT)
        partials = [
            self.complete(chunk, model, system=PARTIAL_PROMPT).reply for chunk in split_masked_text(masked_text)
        ]
        return self.complete("\n\n".join(partials), model, system=SYSTEM_PROMPT)
