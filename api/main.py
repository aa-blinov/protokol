"""STT -> PII masking -> OpenRouter.

Nothing that reaches OpenRouter contains original personal data: the transcript
is masked first and placeholders are only restored in the response, locally.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from threading import Lock

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

import config
import analysis_cache
import llm
import schemas
from dialogue import assign_words_to_turns, build_dialogue
from diarization import Diarizer
from llm import DEFAULT_MODEL, PRESET_LABELS, LlmError, OpenRouterClient
from masking import mask, unmask
from ner import PiiNer
import settings
from rules import fill_gaps, find_candidates
from stt import TARGET_SAMPLE_RATE, Stt

log = logging.getLogger("sttshka")
app = FastAPI(title="STT → PII → OpenRouter", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Models are large (GigaAM ~885 MB, PII-NER ~711 MB) and slow to load, so they
# are created once, lazily, and shared. This keeps /api/mask usable without them.
_stt: Stt | None = None
_ner: PiiNer | None = None
_load_lock = Lock()


def get_stt() -> Stt:
    global _stt
    if _stt is None:
        with _load_lock:
            if _stt is None:
                try:
                    _stt = Stt(config.GIGAAM_DIR, threads=config.INFERENCE_THREADS)
                except FileNotFoundError as error:
                    raise HTTPException(503, f"STT model unavailable: {error}") from error
    return _stt


def get_ner() -> PiiNer:
    global _ner
    if _ner is None:
        with _load_lock:
            if _ner is None:
                try:
                    _ner = PiiNer(config.PII_NER_DIR, threads=config.INFERENCE_THREADS)
                except FileNotFoundError as error:
                    raise HTTPException(503, f"PII model unavailable: {error}") from error
    return _ner


def get_llm() -> OpenRouterClient:
    """Build a client for the key currently in force.

    Reads through the settings store rather than `config` directly, so a key
    typed into the settings dialog works on the very next request.
    """
    key = settings.current_key()
    if not key:
        raise HTTPException(503, "Ключ API не задан, укажите его в настройках")
    return OpenRouterClient(key, settings.current_base_url())


_diarizer: Diarizer | None = None
_diarizer_checked = False


def get_diarizer() -> Diarizer | None:
    """The diarizer, or ``None`` when its models are absent.

    Optional on purpose: the transcript, masking and LLM answer must keep working
    on a machine that has only the ASR/NER models, and a single-speaker recording
    gains nothing from diarization anyway.
    """
    global _diarizer, _diarizer_checked
    if not _diarizer_checked:
        with _load_lock:
            if not _diarizer_checked:
                _diarizer_checked = True
                try:
                    _diarizer = Diarizer(
                        config.DIARIZATION_SEG_DIR,
                        config.DIARIZATION_EMB_PATH,
                        threads=config.INFERENCE_THREADS,
                    )
                except Exception as error:  # noqa: BLE001 - a missing/broken model must not break the pipeline
                    log.warning("diarization unavailable: %s", error)
                    _diarizer = None
    return _diarizer


def _entities_out(result) -> list[schemas.Entity]:
    return [schemas.Entity(**vars(entity)) for entity in result.entities]


def _spans(text: str) -> list:
    """Every span to mask: the model's, plus the rules only where it missed.

    The deterministic layer was reworked on 2026-10-11. Run unconditionally it
    hurt: card -6.2 F1, phone -2.2 on redmadrobot-rnd/pii_benchmark, because a
    rule span and a model span landing on the same number under different labels
    scored as both a hit and a miss. Now `fill_gaps` keeps only the parts a rule
    covers that the model did not, so the model keeps its own label where it was
    right and the rules complete it where it was not.
    """
    model_spans = get_ner().predict(text)
    return model_spans + fill_gaps(text, model_spans, find_candidates(text))


def _settings_state() -> schemas.SettingsState:
    key = settings.current_key()
    return schemas.SettingsState(
        has_key=bool(key),
        key_hint=settings.KeyHint.of(key).masked,
        model=settings.current_model(),
        base_url=settings.current_base_url(),
        key_page=settings.KEY_PAGE,
        models_page="https://openrouter.ai/models",
        preset=settings.current_preset(),
        extra=settings.current_extra(),
        presets=[
            {"key": key, "label": label} for key, label in PRESET_LABELS.items()
        ],
        saved_keys={
            address: settings.KeyHint.of(saved).masked
            for address, saved in settings.provider_keys().items()
        },
    )


def _sessions_path() -> Path:
    """Where processed recordings are kept between runs.

    The browser's localStorage cannot hold this: the desktop shell picks a random
    free port on every launch, and Chromium scopes localStorage to the origin
    including the port, so each start looked like a brand-new site and the history
    was empty again. A file next to the settings file sits at a fixed path and
    survives restarts, rebuilds and reinstalls.
    """
    return settings.settings_path().with_name("sessions.json")


@app.get("/api/sessions")
def read_sessions() -> list[dict]:
    """Previously processed recordings, newest first."""
    path = _sessions_path()
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(data, list):
        return []
    return [_migrate_session(item) for item in data]


def _migrate_session(session: dict) -> dict:
    """Give an older session the shape the app now expects.

    Sessions used to hold a single `summary`, so switching the mode replaced it
    and the earlier one was gone. They now hold one summary per mode. The single
    summary becomes the entry for the mode it was made in — `preset` travels in
    the summary itself — so nothing already on disk is lost and nothing has to be
    summarised twice.
    """
    if not isinstance(session, dict) or "summaries" in session:
        return session
    summary = session.pop("summary", None)
    session["summaries"] = {summary.get("preset") or "decisions": summary} if summary else {}
    return session


@app.put("/api/sessions")
def write_sessions(payload: list[dict]) -> dict[str, int]:
    """Replace the stored history. Written whole, so a crash cannot truncate it."""
    path = _sessions_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload[:50], ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)
    return {"saved": min(len(payload), 50)}


@app.get("/api/settings", response_model=schemas.SettingsState)
def read_settings() -> schemas.SettingsState:
    """Current key/model/address state. The key itself is never in the response."""
    return _settings_state()


@app.post("/api/settings", response_model=schemas.SettingsResult)
def update_settings(request: schemas.SettingsUpdate) -> schemas.SettingsResult:
    """Save the address, key and model. A bad key is reported, not stored."""
    key = request.key.strip()
    model = request.model.strip()
    base_url = request.base_url.strip()
    target = base_url or settings.current_base_url()
    if request.verify and key:
        check = settings.verify(key, target)
        if not check["ok"]:
            return schemas.SettingsResult(ok=False, detail=check["detail"], settings=_settings_state())
    settings.save(key, model, base_url, request.preset, request.extra)
    detail = "Сохранено" if not key else "Ключ проверен и сохранён"
    return schemas.SettingsResult(ok=True, detail=detail, settings=_settings_state())


@app.post("/api/settings/verify", response_model=schemas.KeyCheckResult)
def verify_key(request: schemas.KeyCheck) -> schemas.KeyCheckResult:
    """Check a key against the configured address, without saving unless asked."""
    target = request.base_url.strip() or settings.current_base_url()
    check = settings.verify(request.key, target)
    if check["ok"] and request.remember:
        settings.save(request.key.strip(), settings.current_model(), target)
    return schemas.KeyCheckResult(
        ok=check["ok"], detail=check["detail"], settings=_settings_state() if check["ok"] else None
    )


@app.get("/api/models", response_model=list[schemas.ModelInfo])
def list_models() -> list[schemas.ModelInfo]:
    """The configured provider's catalogue, for the picker."""
    try:
        return [
            schemas.ModelInfo(**item)
            for item in settings.list_models(settings.current_key())
        ]
    except RuntimeError as error:
        raise HTTPException(502, str(error)) from error


@app.get("/api/health")
def health() -> dict:
    return {
        "stt": (config.GIGAAM_DIR / "config.json").is_file(),
        "ner": (config.PII_NER_DIR / "model.optimized.fp32.onnx").is_file(),
        "diarization": (config.DIARIZATION_SEG_DIR / "model.onnx").is_file()
        and config.DIARIZATION_EMB_PATH.is_file(),
        "llm_configured": bool(settings.current_key()),
        "providers": config.ort_providers(),
        # Requested providers above can include CoreML while onnxruntime actually
        # fell back to CPU; only the loaded session knows the truth. Null until the
        # first /api/mask — /api/transcribe loads STT and never touches this one.
        "ner_provider": _ner.active_provider if _ner is not None else None,
        "web": config.WEB_DIST_DIR.is_dir(),
    }


@app.post("/api/transcribe", response_model=schemas.TranscribeResponse)
async def transcribe(file: UploadFile = File(...)) -> schemas.TranscribeResponse:
    audio = await file.read()
    if not audio:
        raise HTTPException(400, "Empty file")
    suffix = _suffix(file.filename)
    try:
        text, duration = get_stt().transcribe(audio, suffix)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    return schemas.TranscribeResponse(text=text, duration_sec=round(duration, 2))


@app.post("/api/mask", response_model=schemas.MaskResponse)
def mask_text(request: schemas.MaskRequest) -> schemas.MaskResponse:
    spans = _spans(request.text)
    result = mask(request.text, spans)
    return schemas.MaskResponse(
        masked_text=result.masked_text,
        entity_map=result.entity_map,
        entities=_entities_out(result),
    )


@app.post("/api/llm", response_model=schemas.LLMResponse)
def llm_complete(request: schemas.LLMRequest) -> schemas.LLMResponse:
    """A single completion over text the caller has already masked.

    Kept for the pipeline tests and for scripting; the app itself goes through
    /api/analyse then /api/summarize. Named `llm_complete` rather than `llm`
    because a function of that name shadows the `llm` module for the whole
    file -- which silently broke every `llm.exact_cost` call below.
    """
    try:
        result = get_llm().complete(request.masked_text, request.model)
    except LlmError as error:
        raise HTTPException(502, str(error)) from error
    return schemas.LLMResponse(
        reply=result.reply,
        reply_unmasked=unmask(result.reply, request.entity_map),
        model=result.model,
        tokens_in=result.tokens_in,
        tokens_out=result.tokens_out,
    )


def _analyse(audio: bytes, suffix: str):
    """Transcribe, split by speaker, mask -- everything except the summary.

    A generator: yields ``(stage, pct, message)`` while the work happens and
    finishes with a ``payload`` instead. The browser needs those lines, because
    transcription alone takes about thirty seconds for a twenty-minute
    recording and a frozen spinner for half a minute reads as a hang.

    The result is cached under the digest of the audio, so a second summary of
    the same recording -- a different focus, a tweaked instruction -- costs
    nothing but the model call itself.
    """
    key = analysis_cache.key_for(audio, suffix)
    cached = analysis_cache.get(key)
    if cached is not None:
        yield ("done", 100, "Расшифровка уже готова", {**cached, "cached": True})
        return

    started = time.perf_counter()
    yield ("transcribe", 5, "Транскрибация аудио", None)
    samples = Stt.decode(audio)
    duration = len(samples) / TARGET_SAMPLE_RATE
    stt = get_stt()
    timings: dict[str, float] = {}
    segments: list[schemas.SpeakerSegment] = []

    diarizer = get_diarizer()
    if diarizer is not None:
        yield ("diarize", 20, "Определение говорящих", None)
        diarize_started = time.perf_counter()
        turns = diarizer.diarize(samples)
        # Timed apart from transcribe, for the same reason as in /api/process:
        # the progress line names this stage "diarize", so an estimate for it
        # needs a duration under that name.
        timings["diarize"] = round(time.perf_counter() - diarize_started, 2)
        if len({turn.speaker for turn in turns}) > 1:
            # One pass over the whole audio (the model keeps its own context),
            # then each word is assigned to the speaker turn it falls in.
            words = stt.transcribe_words(samples)
            attributed = assign_words_to_turns(
                words, [(turn.speaker, turn.start, turn.end) for turn in turns]
            )
            for speaker, start, end, turn_text in attributed:
                turn_text = turn_text.strip()
                if turn_text:
                    # 0-based, like /api/process and like the schema says; the
                    # "+1" that turns it into a label happens in speaker_line_prefix
                    # and in the UI, so it must not happen here as well.
                    segments.append(
                        schemas.SpeakerSegment(
                            speaker=speaker, start=start, end=end, text=turn_text
                        )
                    )

    if segments:
        # The model is given the meeting as speaker turns, and it is this
        # labelled text that gets masked: who said what stays visible, the PII
        # in it does not.
        text, offsets = build_dialogue(
            [(item.speaker, item.start, item.text) for item in segments]
        )
        for segment, offset in zip(segments, offsets):
            segment.offset = offset
    else:
        text = stt.transcribe_samples(samples)
    timings["transcribe"] = round(time.perf_counter() - started, 2)

    if not text.strip():
        raise ValueError("В аудио не распознано речи")

    mask_started = time.perf_counter()
    yield ("mask", 45, "Маскирование персональных данных", None)
    masked = mask(text, _spans(text))
    timings["mask"] = round(time.perf_counter() - mask_started, 2)

    payload = {
        "cache_key": key,
        "transcript": text,
        "masked_text": masked.masked_text,
        "entity_map": masked.entity_map,
        # Dumped, not kept as models: this payload goes straight to json.dumps
        # when it is written to the cache file.
        "entities": [entity.model_dump() for entity in _entities_out(masked)],
        "segments": [segment.model_dump() for segment in segments],
        "duration_sec": round(duration, 2),
        "timings": timings,
        "cached": False,
    }
    analysis_cache.put(key, payload)
    yield ("done", 100, "Готово", payload)


def _analysis_line(
    stage: str, pct: int, message: str, payload: dict | None = None
) -> str:
    return json.dumps(
        schemas.AnalysisProgress(
            stage=stage, pct=pct, message=message,
            result=schemas.AnalysisResult(**payload) if payload else None,
        ).model_dump(mode="json"),
        ensure_ascii=False,
    ) + "\n"


@app.post("/api/analyse")
async def analyse(file: UploadFile = File(...)) -> StreamingResponse:
    """Everything up to the masked text, as NDJSON. No model call happens here.

    Split from the summary so this half can be reused: the focus can change any
    number of times without listening to the recording again.
    """
    audio = await file.read()
    if not audio:
        raise HTTPException(400, "Empty file")
    suffix = _suffix(file.filename)

    def stream():
        try:
            for stage, pct, message, payload in _analyse(audio, suffix):
                yield _analysis_line(stage, pct, message, payload)
        except HTTPException as error:
            yield _analysis_line("error", 100, str(error.detail))
        except ValueError as error:
            yield _analysis_line("error", 100, str(error))
        except Exception as error:  # keep the stream well-formed for the UI
            log.exception("analyse failed")
            yield _analysis_line("error", 100, f"Не удалось разобрать запись: {error}")

    return StreamingResponse(stream(), media_type="application/x-ndjson")


@app.post("/api/summarize", response_model=schemas.SummarizeResult)
def summarize(request: schemas.SummarizeRequest) -> schemas.SummarizeResult:
    """The summary alone, over an already-analysed recording."""
    cached = analysis_cache.get(request.cache_key)
    # The cache is bounded at eight entries, so a recording analysed last week is
    # simply gone from it -- and saying "загрузите заново" about a file that is
    # still in the history, still transcribed, and whose summary the user wants
    # to re-run is both wrong and unusable. The masked text lives in the session
    # file on this machine, so accept it from there when the cache misses.
    masked_text = (cached or {}).get("masked_text") or request.masked_text
    if not masked_text.strip():
        raise HTTPException(
            404,
            "Расшифровка этой записи не сохранилась для повторной выжимки. "
            "Загрузите файл заново, это займёт столько же времени, сколько занял первый раз.",
        )
    entity_map = (cached or {}).get("entity_map") or request.entity_map or {}
    preset = request.preset or settings.current_preset()
    started = time.perf_counter()
    try:
        result = get_llm().complete_meeting(
            masked_text,
            request.model,
            preset,
            settings.current_extra() if request.extra is None else request.extra,
        )
    except LlmError as error:
        raise HTTPException(502, str(error)) from error
    elapsed = round(time.perf_counter() - started, 2)
    cost = llm.exact_cost(
        result.tokens_in,
        result.tokens_out,
        _price_of(request.model, "prompt"),
        _price_of(request.model, "completion"),
    )
    return schemas.SummarizeResult(
        reply=result.reply,
        reply_unmasked=unmask(result.reply, entity_map),
        llm_model=result.model,
        preset=preset,
        tokens_in=result.tokens_in,
        tokens_out=result.tokens_out,
        cost=cost,
        timings={"llm": elapsed},
    )


# Prices belong to the address they were fetched from. Keyed by it, because the
# service is switchable now: one flat cache would keep OpenAI's price-less
# catalogue after a trip back to OpenRouter and every estimate would quietly
# read "unknown" until the app restarted.
_PRICES: dict[str, dict[str, dict[str, float | None]]] = {}


def _price_of(model: str, which: str) -> float | None:
    """Per-million price for a model, or None when the catalogue quotes none."""
    return (_load_prices().get(model) or {}).get(which)


def _load_prices() -> dict[str, dict[str, float | None]]:
    """Fetch one address's prices once and keep them for the session.

    Lazy rather than at import: it is a network call, and the app must start
    without a key and without a connection. The models list is public on
    OpenRouter, so this works before a key is even entered. Other services
    answer /models too, but without the price fields, so their models come back
    unpriced rather than wrongly priced.
    """
    root = settings.current_base_url()
    if root not in _PRICES:
        try:
            _PRICES[root] = {
                item["id"]: {
                    "prompt": item.get("prompt_price"),
                    "completion": item.get("completion_price"),
                }
                for item in settings.list_models("")
            }
        except RuntimeError:
            _PRICES[root] = {}
    return _PRICES[root]


@app.post("/api/estimate", response_model=schemas.EstimateResult)
def estimate(request: schemas.EstimateRequest) -> schemas.EstimateResult:
    """What one summary over this much text will roughly cost."""
    prices = _load_prices().get(request.model) or {}
    rough = llm.estimate_summary(request.chars, prices.get("prompt"), prices.get("completion"))
    return schemas.EstimateResult(**rough)


@app.get("/api/model-prices")
def model_prices() -> dict[str, dict[str, float | None]]:
    """Per-million prices for the catalogue, so the estimate needs no second call."""
    return _load_prices()


@app.post("/api/process")
async def process(
    file: UploadFile = File(...),
    llm_model: str = Form(DEFAULT_MODEL),
) -> StreamingResponse:
    """Full pipeline as NDJSON so the UI can drive a real progress bar.

    Every line is a ``ProcessProgress`` object; the last one carries the result.
    """
    audio = await file.read()
    if not audio:
        raise HTTPException(400, "Empty file")

    def stream():
        timings: dict[str, float] = {}
        try:
            started = time.perf_counter()
            yield _line("transcribe", 5, "Транскрибация аудио")
            samples = Stt.decode(audio)
            duration = len(samples) / TARGET_SAMPLE_RATE
            stt = get_stt()
            diarizer = get_diarizer()
            segments: list[schemas.SpeakerSegment] = []
            if diarizer is not None:
                yield _line("diarize", 20, "Определение говорящих")
                diarize_started = time.perf_counter()
                turns = diarizer.diarize(samples)
                # Timed apart from transcribe: the progress line names this stage
                # "diarize", so an estimate for it needs a duration under that name.
                timings["diarize"] = round(time.perf_counter() - diarize_started, 2)
                if len({turn.speaker for turn in turns}) > 1:
                    # One pass over the whole audio (the model keeps its own
                    # context), then each word is assigned to the speaker turn it
                    # falls in — instead of transcribing every turn in isolation.
                    words = stt.transcribe_words(samples)
                    attributed = assign_words_to_turns(
                        words, [(turn.speaker, turn.start, turn.end) for turn in turns]
                    )
                    for speaker, start, end, turn_text in attributed:
                        turn_text = turn_text.strip()
                        if turn_text:
                            segments.append(
                                schemas.SpeakerSegment(
                                    speaker=speaker,
                                    start=round(start, 2),
                                    end=round(end, 2),
                                    text=turn_text,
                                )
                            )
            if segments:
                # The model is given the meeting as speaker turns, and it is this
                # labelled text that gets masked: who said what stays visible, the
                # PII in it does not.
                text, offsets = build_dialogue([(item.speaker, item.start, item.text) for item in segments])
                for segment, offset in zip(segments, offsets):
                    segment.offset = offset
            else:
                text = stt.transcribe_samples(samples)
            timings["transcribe"] = round(time.perf_counter() - started, 2)
            if not text.strip():
                yield _line("error", 100, "В аудио не распознано речи")
                return

            started = time.perf_counter()
            yield _line("mask", 45, "Маскирование персональных данных")
            result = mask(text, _spans(text))
            timings["mask"] = round(time.perf_counter() - started, 2)

            started = time.perf_counter()
            yield _line("llm", 70, f"Запрос к {llm_model}")
            completion = get_llm().complete_meeting(
                result.masked_text,
                llm_model,
                settings.current_preset(),
                settings.current_extra(),
            )
            timings["llm"] = round(time.perf_counter() - started, 2)

            payload = schemas.ProcessResult(
                transcript=text,
                masked_text=result.masked_text,
                entity_map=result.entity_map,
                entities=_entities_out(result),
                llm_model=completion.model,
                reply=completion.reply,
                reply_unmasked=unmask(completion.reply, result.entity_map),
                duration_sec=round(duration, 2),
                segments=segments,
                timings=timings,
            )
            yield _line("done", 100, "Готово", payload)
        except HTTPException as error:
            yield _line("error", 100, error.detail)
        except LlmError as error:
            yield _line("error", 100, str(error))
        except Exception as error:  # keep the stream well-formed for the UI
            log.exception("process failed")
            yield _line("error", 100, f"Ошибка обработки: {error}")

    return StreamingResponse(stream(), media_type="application/x-ndjson")


def _line(stage: str, pct: int, message: str, result: schemas.ProcessResult | None = None) -> str:
    return json.dumps(
        schemas.ProcessProgress(stage=stage, pct=pct, message=message, result=result).model_dump(mode="json"),
        ensure_ascii=False,
    ) + "\n"


def _suffix(filename: str | None) -> str:
    if not filename or "." not in filename:
        return ".wav"
    return "." + filename.rsplit(".", 1)[1].lower()


# Registered last so every /api route above wins over the SPA catch-all. This is
# what lets the desktop app be a single process: no nginx, no CORS, no proxy.
if config.WEB_DIST_DIR.is_dir():
    app.mount("/", StaticFiles(directory=config.WEB_DIST_DIR, html=True), name="web")


if __name__ == "__main__":
    # Entry point for the packaged desktop sidecar: it reads PORT/HOST itself so
    # the Electron shell only has to pick a free port and spawn this binary.
    import os

    import uvicorn

    uvicorn.run(app, host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "8000")))
