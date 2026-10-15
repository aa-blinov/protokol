"""Pydantic contracts for the API.

``ProcessRequest.audio_url`` from the design sketch is intentionally not kept:
the UI uploads a local recording through drag & drop, so ``/api/process`` takes
multipart audio instead. Fetching a remote URL would also be an SSRF footgun for
no benefit in a single-user tool.
"""

from __future__ import annotations

from llm import DEFAULT_MODEL
from pydantic import BaseModel, Field


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


class SpeakerSegment(BaseModel):
    speaker: int = Field(description="Speaker index, 0-based")
    start: float = Field(description="Turn start, seconds")
    end: float = Field(description="Turn end, seconds")
    text: str = Field(description="Transcript of this turn")
    offset: int = Field(default=0, description="Char offset of this turn's text in the full transcript")


class ProcessResult(BaseModel):
    transcript: str
    masked_text: str
    entity_map: dict[str, str]
    entities: list[Entity]
    llm_model: str
    reply: str
    reply_unmasked: str
    duration_sec: float
    segments: list[SpeakerSegment] = Field(
        default_factory=list,
        description="Speaker turns with their text; empty when diarization is unavailable or the audio is single-speaker",
    )
    timings: dict[str, float] = Field(default_factory=dict, description="Stage timings in seconds")


class ProcessProgress(BaseModel):
    """One line of the ``/api/process`` NDJSON stream."""

    stage: str = Field(description="transcribe | mask | llm | done | error")
    pct: int = Field(ge=0, le=100)
    message: str = ""
    result: ProcessResult | None = None


class PolicyState(BaseModel):
    """What the organisation fixed on this Mac. A field that is off means nothing is fixed."""

    managed: bool = Field(default=False, description="A policy file is present")
    lock_settings: bool = Field(default=False, description="No setting can be changed in the app")
    base_url_locked: bool = Field(default=False, description="The service address is fixed")
    allow_export: bool = Field(default=True, description="The .txt export, copy and print are offered")
    retention_days: int | None = Field(default=None, description="History is kept this many days")
    errors: list[str] = Field(default_factory=list, description="Problems in the policy file, reported and skipped")


class SettingsState(BaseModel):
    """What the settings dialog needs to render itself.

    ``key_hint`` is a masked prefix/suffix, never the key itself -- the browser
    gets enough to say "sk-or-v1-…3709a" and nothing more.
    """

    has_key: bool = Field(description="Whether a key is currently set")
    key_hint: str = Field(description="Masked key for display, e.g. sk-or-v1-…3709a")
    model: str = Field(description="Selected chat model id")
    base_url: str = Field(description="OpenAI-compatible API base URL; OpenRouter by default")
    key_page: str = Field(description="Where to obtain a key")
    models_page: str = Field(description="OpenRouter model catalogue")
    preset: str = Field(default="decisions", description="What to pull out of the recording")
    extra: str = Field(default="", description="Extra requirement appended to the prompt")
    presets: list[dict] = Field(default_factory=list, description="Available presets with labels")
    saved_keys: dict[str, str] = Field(
        default_factory=dict,
        description="Masked keys per API address, so switching service and back keeps each one",
    )
    retention_days: int = Field(default=0, description="Days of history to keep; 0 keeps everything")
    policy: PolicyState = Field(default_factory=PolicyState, description="What the organisation fixed")


class SettingsUpdate(BaseModel):
    """Save the key and/or the model. An empty ``key`` keeps the stored one."""

    key: str = Field(default="", description="New API key; empty means keep the current one")
    base_url: str = Field(default="", description="New API address; empty means keep the current one")
    model: str = Field(default="", description="New model id; empty means keep the current one")
    verify: bool = Field(default=True, description="Check the key against that address before saving")
    preset: str = Field(default="", description="Preset key; empty means keep the current one")
    extra: str | None = Field(default=None, description="Extra requirement; null means keep, empty string clears")
    retention_days: int | None = Field(
        default=None, ge=0, le=3650, description="Days of history to keep; null keeps the stored value"
    )


class SettingsResult(BaseModel):
    ok: bool
    detail: str = ""
    settings: SettingsState


class KeyCheck(BaseModel):
    key: str
    base_url: str = Field(default="", description="Address to check against; empty means the current one")
    remember: bool = Field(default=False, description="Save the key when it turns out to work")


class KeyCheckResult(BaseModel):
    ok: bool
    detail: str = ""
    settings: SettingsState | None = None


class ModelInfo(BaseModel):
    id: str
    name: str
    context: int | None = None
    prompt_price: float | None = Field(default=None, description="USD per million prompt tokens")
    completion_price: float | None = Field(default=None, description="USD per million completion tokens")


class AnalysisResult(BaseModel):
    """Audio turned into text, speakers and masks -- but no summary yet."""

    cache_key: str
    transcript: str
    masked_text: str
    entity_map: dict[str, str]
    entities: list[Entity]
    segments: list[SpeakerSegment] = Field(default_factory=list)
    duration_sec: float
    timings: dict[str, float] = Field(default_factory=dict)
    cached: bool = Field(default=False, description="True when the transcript was reused from a previous run")


class AnalysisProgress(BaseModel):
    """One line of the ``/api/analyse`` NDJSON stream.

    Same shape as ``ProcessProgress`` so the browser can share one reader, but
    without an ``llm`` stage: this half of the pipeline never calls a model.
    """

    stage: str = Field(description="transcribe | diarize | mask | done | error")
    pct: int = Field(ge=0, le=100)
    message: str = ""
    result: AnalysisResult | None = None


class SummarizeRequest(BaseModel):
    cache_key: str
    model: str = DEFAULT_MODEL
    preset: str = ""
    extra: str | None = None
    # Fallback for a recording whose cache entry has been evicted. The masked
    # text already lives in the session file on this machine, so re-running a
    # summary should never depend on a bounded cache still holding it.
    masked_text: str = ""
    # The map that puts the names back arrives with it. Without it a re-run over
    # a recording whose cache entry is gone comes back full of [PERSON_1] where
    # the names should be -- and that is exactly the recording most likely to
    # need a re-run, because it is the one with no cache to read from.
    entity_map: dict[str, str] = Field(default_factory=dict)


class SummarizeResult(BaseModel):
    reply: str
    reply_unmasked: str
    llm_model: str
    preset: str = Field(default="", description="Which focus was applied, echoed back for the UI")
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost: dict[str, float | None] = Field(default_factory=dict)
    timings: dict[str, float] = Field(default_factory=dict)
    # Things the user should look at before trusting the summary, e.g. a placeholder
    # the model invented. Empty when the reply checks out.
    warnings: list[str] = Field(default_factory=list)


class EstimateRequest(BaseModel):
    chars: int = Field(description="Length of the text that would be sent, in characters")
    model: str = DEFAULT_MODEL


class EstimateResult(BaseModel):
    """Pre-flight figures for one summary. All money fields are null when the
    provider quotes no fixed price for the model, rather than rounded to zero."""

    tokens_in: int
    tokens_out: int
    requests: int = Field(description="How many provider requests this summary takes")
    input: float | None = Field(default=None, description="USD for the incoming text")
    output: float | None = Field(default=None, description="USD for the reply")
    total: float | None = None
    currency: str = "USD"


class LicenceActivate(BaseModel):
    """A licence file as the customer received it."""

    text: str = Field(description="The licence document: JSON with payload and signature")
