"""Pydantic contracts for the API.

``ProcessRequest.audio_url`` from the design sketch is intentionally not kept:
the UI uploads a local recording through drag & drop, so ``/api/process`` takes
multipart audio instead. Fetching a remote URL would also be an SSRF footgun for
no benefit in a single-user tool.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from llm import DEFAULT_MODEL


class Entity(BaseModel):
    token: str = Field(description="Placeholder token, e.g. PERSON_1")
    type: str = Field(description="Display type, e.g. PERSON")
    label: str = Field(description="Raw model label, e.g. LAST_NAME")
    start: int
    end: int
    text: str = Field(description="Original surface string")
    score: float


class MaskRequest(BaseModel):
    text: str


class MaskResponse(BaseModel):
    masked_text: str
    entity_map: dict[str, str]
    entities: list[Entity] = Field(default_factory=list, description="Spans for UI highlighting")


class TranscribeResponse(BaseModel):
    text: str
    duration_sec: float


class LLMRequest(BaseModel):
    masked_text: str
    model: str = DEFAULT_MODEL
    entity_map: dict[str, str] = Field(
        default_factory=dict,
        description="Optional; when given the reply is de-masked back to the originals",
    )


class LLMResponse(BaseModel):
    reply: str = Field(description="Model output, still masked")
    reply_unmasked: str = Field(description="Placeholders restored to original values")
    model: str
    tokens_in: int | None = None
    tokens_out: int | None = None


class ProcessResult(BaseModel):
    transcript: str
    masked_text: str
    entity_map: dict[str, str]
    entities: list[Entity]
    llm_model: str
    reply: str
    reply_unmasked: str
    duration_sec: float
    timings: dict[str, float] = Field(default_factory=dict, description="Stage timings in seconds")


class ProcessProgress(BaseModel):
    """One line of the ``/api/process`` NDJSON stream."""

    stage: str = Field(description="transcribe | mask | llm | done | error")
    pct: int = Field(ge=0, le=100)
    message: str = ""
    result: ProcessResult | None = None
