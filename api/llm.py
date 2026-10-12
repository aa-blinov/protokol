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
# summary, keeping the placeholder tokens verbatim so the reply can be de-masked
# locally.
#
# SAFETY_PREFIX is not editable. The user picks *what* to pull out of the
# recording, never whether the masking rules apply -- a prompt they type is added
# to these instructions, it cannot replace them.
SAFETY_PREFIX = (
    "Ты работаешь по транскрипту разговора. Строки вида «Спикер 2 [12:34]: …» — "
    "это реплики с временем. Персональные данные заменены токенами вида "
    "[PERSON_1], [PHONE_1], [PASSPORT_1]: сохраняй каждый токен дословно, не "
    "раскрывай и не перевирай его, ничего не выдумывай, опирайся только на "
    "транскрипт. Отвечай по-русски и по делу."
)

# What to pull out. Keyed by the value the settings dialog stores.
PRESET_BODIES: dict[str, str] = {
    "decisions": "Дай: суть разговора; ключевые обсуждённые пункты; принятые решения; задачи (что сделать, кто, срок — если это названо); открытые вопросы.",
    "summary": "Дай краткий пересказ: о чём шёл разговор, по порядку, без списка мелких деталей.",
    "agreements": "Дай договорённости сторон: что стороны обещали друг другу, под какие сроки и на каких условиях.",
}

# Labels shown in the settings dialog, keyed the same as PRESET_BODIES.
PRESET_LABELS = {
    "decisions": "Решения и задачи",
    "summary": "Краткий пересказ",
    "agreements": "Договорённости сторон",
}

DEFAULT_PRESET = "decisions"


def build_system_prompt(preset: str = DEFAULT_PRESET, extra: str = "") -> str:
    """Assemble the system prompt: safety rules, then the chosen focus."""
    body = PRESET_BODIES.get(preset, PRESET_BODIES[DEFAULT_PRESET])
    extra = (extra or "").strip()
    tail = f"\n\nДополнительные требования: {extra}" if extra else ""
    return f"{SAFETY_PREFIX}\n\n{body}{tail}"


SYSTEM_PROMPT = build_system_prompt()

# A long meeting is compressed part by part first, so a single request never has
# to carry a whole hour of transcript.
PARTIAL_PROMPT = (
    "Ниже фрагмент транскрипта разговора (реплики вида «Спикер N [время]: …»; "
    "персональные данные заменены токенами вида [PERSON_1]). Сожми фрагмент в "
    "тезисы, сохраняя токены дословно: факты, решения, задачи, упомянутые токены. "
    "Без вступлений и выводов."
)

# Up to this many characters the protocol is one request; beyond it, parts first.
MEETING_MAP_CHARS = 24_000
MEETING_CHUNK_CHARS = 8_000

# Two constants the pre-flight estimate rests on. They are assumptions, not
# measurements: no run longer than a single request has been timed end to end,
# because every recording measured so far fits under MEETING_MAP_CHARS. They
# affect only the "about" figure shown before sending -- the exact cost arrives
# from the provider afterwards and is what the document reports. Replace them
# once a long call has actually been processed.
PARTIAL_COMPRESSION = 0.15  # what survives compressing a chunk into theses
TYPICAL_PARTIAL_TOKENS = 400  # a compressed chunk, back from the model


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


# --- pre-flight estimate -------------------------------------------------------
#
# Lives here, next to the splitting rules, on purpose: an estimate is only worth
# showing if it follows the same branch `complete_meeting` takes. A 60-minute
# meeting is not one request but one per chunk plus a final one, and quoting the
# single-request price would understate the bill by more than an order of
# magnitude.

TOKENS_PER_CHAR = 0.34  # Russian prose against a BPE vocabulary
TYPICAL_OUTPUT_TOKENS = 1200  # a protocol-length summary


def tokens_for(chars: int) -> int:
    return int(max(chars, 0) * TOKENS_PER_CHAR)


def plan_summary(chars: int) -> dict[str, int]:
    """How many requests a summary of ``chars`` characters will take.

    Derived from the length alone, because that is all the UI has before the
    first request. ``split_masked_text`` works on real line boundaries, so the
    chunk count here is an approximation -- off by at most one, since transcript
    lines are far shorter than a chunk.
    """
    if chars <= MEETING_MAP_CHARS:
        return {"requests": 1, "chunks": 0}
    return {"requests": -(-chars // MEETING_CHUNK_CHARS) + 1, "chunks": -(-chars // MEETING_CHUNK_CHARS)}


def exact_cost(
    tokens_in: int | None, tokens_out: int | None, prompt_price: float | None, completion_price: float | None
) -> dict[str, float | None]:
    """Money actually spent, from the token counts the provider reported.

    This is the figure the document shows; the pre-flight estimate above is the
    approximation, this one is not.
    """

    def money(tokens: int | None, price: float | None) -> float | None:
        if tokens is None or price is None:
            return None
        return round(tokens / 1_000_000 * price, 4)

    incoming = money(tokens_in, prompt_price)
    outgoing = money(tokens_out, completion_price)
    total = None if incoming is None or outgoing is None else round(incoming + outgoing, 4)
    return {"input": incoming, "output": outgoing, "total": total}


def estimate_summary(
    chars: int, prompt_price: float | None, completion_price: float | None
) -> dict[str, float | None | int]:
    """Rough cost of one summary over ``chars`` characters of masked text.

    The input side is the part that can be computed rather than guessed: the
    whole transcript is sent once, plus the compressed parts once more. Output
    is a flat allowance. Both are pre-flight figures -- the exact numbers come
    back from the provider in ``tokens_in``/``tokens_out`` and are shown after
    the summary, not before it.
    """

    def money(tokens: int, price: float | None) -> float | None:
        return None if price is None else round(tokens / 1_000_000 * price, 4)

    plan = plan_summary(chars)
    # Each chunk is compressed before the final call, so the transcript travels
    # roughly twice; PARTIAL_COMPRESSION is the one guessed constant here.
    input_tokens = int(tokens_for(chars) * (1 + PARTIAL_COMPRESSION if plan["chunks"] else 1))
    output_tokens = TYPICAL_OUTPUT_TOKENS + plan["chunks"] * TYPICAL_PARTIAL_TOKENS
    incoming = money(input_tokens, prompt_price)
    outgoing = money(output_tokens, completion_price)
    total = None if incoming is None or outgoing is None else round(incoming + outgoing, 4)
    return {
        "tokens_in": input_tokens,
        "tokens_out": output_tokens,
        "requests": plan["requests"],
        "input": incoming,
        "output": outgoing,
        "total": total,
    }


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

    def complete_meeting(
        self,
        masked_text: str,
        model: str = DEFAULT_MODEL,
        preset: str = DEFAULT_PRESET,
        extra: str = "",
    ) -> LlmResult:
        """The summary. A long transcript is summarised in parts first, then the
        summary is composed from those parts — every request carries masked text
        only, so the reply is de-masked locally as usual."""
        system = build_system_prompt(preset, extra)
        if len(masked_text) <= MEETING_MAP_CHARS:
            return self.complete(masked_text, model, system=system)
        partials = [
            self.complete(chunk, model, system=PARTIAL_PROMPT).reply for chunk in split_masked_text(masked_text)
        ]
        return self.complete("\n\n".join(partials), model, system=system)
