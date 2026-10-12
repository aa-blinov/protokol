"""Run the real pipeline end to end on real Russian audio.

Uses the same functions as the /api/process endpoint rather than a reimplementation:
Stt.transcribe_words + Diarizer + build_dialogue for the transcript, NER + the
structured rules for masking, and OpenRouter for the answer.

The LibriVox audio carries no personal data (it is Tolstoy read aloud), so the
masking and LLM steps run on a separate realistic call transcript -- otherwise
those two stages would have nothing to find and the run would look clean for the
wrong reason.

Run: .venv/bin/python benchmarks/run_pipeline_real.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[0]
sys.path.insert(0, str(ROOT / "api"))

import config  # noqa: E402
from dialogue import build_dialogue  # noqa: E402
from diarization import Diarizer  # noqa: E402
from llm import OpenRouterClient, LlmError  # noqa: E402
from masking import mask, unmask  # noqa: E402
from ner import PiiNer  # noqa: E402
from stt import Stt  # noqa: E402

CORPUS = HERE / "corpus" / "librivox"

# A realistic support call: the kind of text the app exists for, with every kind
# of identifier the NER and the structured rules are supposed to catch.
#
# The identifiers are checksum-valid. An INN that fails its own checksum, or a
# card number that fails Luhn, is not an identifier -- the rules refuse to call
# it one, so a demo built from invented digits shows holes that are not there.
CALL = """Спикер 1 [0.0–8.4]: Здравствуйте, меня зовут Светлана Николаевна Кузнецова, я звоню по заказу номер 4471.
Спикер 2 [8.6–14.2]: Здравствуйте. Назовите, пожалуйста, номер телефона, по которому оформлен заказ.
Спикер 1 [14.4–22.8]: +7 916 448 22 09. И почта для отправки чека: svetlana.kuznetsova@yandex.ru.
Спикер 2 [23.0–30.5]: Хорошо. Для оформления возврата нужен паспорт. Серия 4508 номер 123456, выдан в отделе МВД на Лермонтова.
Спикер 1 [30.8–38.0]: Верно. ИИН 100000000074, прописана по адресу Москва, улица Тверская, дом 12, квартира 34.
Спикер 2 [38.3–45.9]: Принято. Карта для возврата 4276380012345679, срок действия до 12 2027.
Спикер 1 [46.2–52.0]: Да, всё верно. Жду возврат до конца недели.
Спикер 2 [52.3–57.1]: Возврат займёт три рабочих дня, деньги придут на карту."""


def stage(name: str, function):
    started = time.perf_counter()
    result = function()
    print(f"[{name}] {time.perf_counter() - started:.2f} с")
    return result


def main() -> int:
    audio_path = CORPUS / "two_readers.npy"
    if not audio_path.is_file():
        raise SystemExit("нет корпуса: .venv/bin/python benchmarks/make_librivox_corpus.py")
    audio = np.load(audio_path)
    print(f"аудио: {audio.size / 16000:.0f} с, реальные голоса (2 читателя LibriVox)")
    print(f"USE_COREML={config.USE_COREML}, провайдеры: {config.ort_providers()}")
    print(f"модель LLM: {config.DEFAULT_LLM_MODEL}")
    print()

    stt = stage("загрузка STT", lambda: Stt(config.GIGAAM_DIR, threads=config.INFERENCE_THREADS))
    diarizer = stage(
        "загрузка диаризации",
        lambda: Diarizer(
            config.DIARIZATION_SEG_DIR, config.DIARIZATION_EMB_PATH, threads=config.INFERENCE_THREADS
        ),
    )
    ner = stage("загрузка NER", lambda: PiiNer(config.PII_NER_DIR, threads=config.INFERENCE_THREADS))

    turns = stage("диаризация", lambda: diarizer.diarize(audio))
    # Diarization is happy with float samples, the recognizer is not: it writes
    # samples.tobytes() under an int16 WAV header.
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
    words = stage("транскрибация со словами", lambda: stt.transcribe_words(pcm))

    from dialogue import assign_words_to_turns  # noqa: PLC0415 - keeps module import order clear

    attributed = assign_words_to_turns(words, [(t.speaker, t.start, t.end) for t in turns])
    transcript, offsets = build_dialogue([(s, start, text) for s, start, _, text in attributed])

    print()
    print("=" * 70)
    print("РАСШИФРОВКА (фрагмент, первые 1200 символов)")
    print("=" * 70)
    print(transcript[:1200])
    print()

    # Masking and the LLM see text with personal data in it, not Tolstoy.
    spans = stage("поиск персональных данных", lambda: ner.predict(CALL))
    masked = stage("маскирование", lambda: mask(CALL, spans))
    print("=" * 70)
    print("МАСКИРОВАНИЕ")
    print("=" * 70)
    print(masked.masked_text)
    print()
    print(f"найдено сущностей: {len(masked.entities)}")
    for entity in masked.entities:
        print(f"  {entity.label:14s} {entity.text!r}")
    leftover = [entity.text for entity in masked.entities if entity.text in masked.masked_text]
    print(f"не замаскировано (утечки): {leftover if leftover else 'нет'}")
    print()

    if not config.OPENROUTER_API_KEY:
        print("OPENROUTER_API_KEY не задан, шаг LLM пропущен")
        return 0

    client = OpenRouterClient(config.OPENROUTER_API_KEY, config.OPENROUTER_BASE_URL)
    try:
        completion = stage(
            "LLM", lambda: client.complete_meeting(masked.masked_text, config.DEFAULT_LLM_MODEL)
        )
    except LlmError as error:
        print(f"LLM не ответил: {error}")
        return 0

    print("=" * 70)
    print(f"ОТВЕТ МОДЕЛИ ({completion.model})")
    print("=" * 70)
    print(completion.reply)
    print()
    print(f"токены: вход {completion.tokens_in}, выход {completion.tokens_out}")
    print()
    print("обратная подстановка:")
    print(unmask(completion.reply, masked.entity_map)[:600])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())