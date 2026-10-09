"""STT -> PII masking -> OpenRouter.

Nothing that reaches OpenRouter contains original personal data: the transcript
is masked first and placeholders are only restored in the response, locally.
"""

from __future__ import annotations

import json
import logging
import time
from threading import Lock

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

import config
import schemas
from dialogue import assign_words_to_turns, build_dialogue
from diarization import Diarizer
from llm import DEFAULT_MODEL, LlmError, OpenRouterClient
from masking import mask, unmask
from ner import PiiNer
from rules import find_structured
from stt import MAX_AUDIO_SECONDS, TARGET_SAMPLE_RATE, Stt

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
    if not config.OPENROUTER_API_KEY:
        raise HTTPException(503, "OPENROUTER_API_KEY is not set")
    return OpenRouterClient(config.OPENROUTER_API_KEY, config.OPENROUTER_BASE_URL)


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
    """Every span to mask: the NER model's, plus the deterministic rules'.

    The rules exist because the model's own weak spots (IP, INN, SNILS,
    passport) are structured, machine-checkable identifiers — a missed one is a
    leak. ``mask`` resolves any overlap between the two sources.
    """
    return get_ner().predict(text) + find_structured(text)


@app.get("/api/health")
def health() -> dict:
    return {
        "stt": (config.GIGAAM_DIR / "config.json").is_file(),
        "ner": (config.PII_NER_DIR / "model.optimized.fp32.onnx").is_file(),
        "diarization": (config.DIARIZATION_SEG_DIR / "model.onnx").is_file()
        and config.DIARIZATION_EMB_PATH.is_file(),
        "llm_configured": bool(config.OPENROUTER_API_KEY),
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
def llm(request: schemas.LLMRequest) -> schemas.LLMResponse:
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
            if duration > MAX_AUDIO_SECONDS:
                yield _line("error", 100, f"Аудио {duration:.0f} с, лимит {MAX_AUDIO_SECONDS} с")
                return
            stt = get_stt()
            diarizer = get_diarizer()
            segments: list[schemas.SpeakerSegment] = []
            if diarizer is not None:
                yield _line("diarize", 20, "Определение говорящих")
                turns = diarizer.diarize(samples)
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
            completion = get_llm().complete_meeting(result.masked_text, llm_model)
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
