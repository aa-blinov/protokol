"""The two-stage pipeline: analyse once, summarise as often as you like.

The point of splitting `/api/process` in two is that transcription is the
expensive half and the summary prompt is the part the user iterates on. So the
properties pinned here are:

  * the same audio never gets transcribed twice,
  * the summary runs over cached text and reaches no audio at all,
  * nothing unmasked leaves the machine -- the cache stores masked text only,
  * the estimate before sending is derived from the same rules that decide how
    many requests the summary will actually take.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import analysis_cache  # noqa: E402
import llm  # noqa: E402
import main as api  # noqa: E402
import settings  # noqa: E402
from dialogue import Word  # noqa: E402
from masking import Span  # noqa: E402

SAMPLE_RATE = 16000


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("STTSHKA_ENV_FILE", str(tmp_path / "settings.env"))
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with TestClient(api.app) as test_client:
        yield test_client


class FakeStt:
    """Counts its calls, which is how "not transcribed twice" is asserted."""

    calls = 0
    text = "Иван Петров позвонил в 15:00"

    def transcribe_samples(self, samples):
        FakeStt.calls += 1
        return FakeStt.text

    def transcribe_words(self, samples):
        FakeStt.calls += 1
        # Spread across eight seconds so a two-turn recording actually puts
        # words in both turns; bunching them at the start would leave the
        # second speaker empty and hide whatever the segmentation does.
        parts = FakeStt.text.split()
        step = 8.0 / max(len(parts), 1)
        return [Word(part, i * step, i * step + step * 0.8) for i, part in enumerate(parts)]

    def word_chunks(self, samples):
        return [samples]

    def words_in_chunk(self, chunk, offset):
        FakeStt.calls += 1
        parts = FakeStt.text.split()
        step = 8.0 / max(len(parts), 1)
        return [Word(part, offset + i * step, offset + i * step + step * 0.8) for i, part in enumerate(parts)]


class FakeNer:
    def predict(self, text):
        return [Span(0, 4, "FIRST_NAME", 0.99)]


class FakeLlm:
    def __init__(self):
        self.calls = []

    def complete_meeting(self, masked_text, model, preset, extra=""):
        self.calls.append((masked_text, preset, extra))
        return llm.LlmResult(reply="Позвонил [PERSON_1]", model=model, tokens_in=100, tokens_out=50)


@pytest.fixture
def pipeline(monkeypatch):
    """Replace the three heavy models with fakes and count what gets called."""
    FakeStt.calls = 0
    FakeStt.text = "Иван Петров позвонил в 15:00"
    fake_llm = FakeLlm()
    monkeypatch.setattr(api.Stt, "decode", staticmethod(lambda audio: np.zeros(SAMPLE_RATE, dtype=np.float32)))
    monkeypatch.setattr(api, "get_stt", lambda: FakeStt())
    monkeypatch.setattr(api, "get_ner", lambda: FakeNer())
    monkeypatch.setattr(api, "get_diarizer", lambda: None)
    monkeypatch.setattr(api, "get_llm", lambda: fake_llm)
    return fake_llm


def ndjson(response) -> list[dict]:
    return [json.loads(line) for line in response.text.splitlines() if line.strip()]


def upload(client, audio=b"fake-audio-bytes", name="meeting.m4a"):
    return client.post("/api/analyse", files={"file": (name, audio, "audio/mp4")})


class TestAnalyse:
    def test_streams_progress_then_a_result(self, client, pipeline):
        lines = ndjson(upload(client))
        stages = [line["stage"] for line in lines]
        assert stages == ["transcribe", "mask", "done"]
        assert lines[-1]["result"]["transcript"].startswith("Иван")

    def test_masked_text_is_what_would_be_sent(self, client, pipeline):
        result = ndjson(upload(client))[-1]["result"]
        assert "Иван Петров" not in result["masked_text"]
        assert "[PERSON_1]" in result["masked_text"]

    def test_entity_map_holds_the_original_locally(self, client, pipeline):
        result = ndjson(upload(client))[-1]["result"]
        assert result["entity_map"]["PERSON_1"] == "Иван"

    def test_timings_cover_every_stage_it_reports(self, client, pipeline):
        lines = ndjson(upload(client))
        reported = {line["stage"] for line in lines} - {"done"}
        assert reported <= set(lines[-1]["result"]["timings"])

    def test_empty_transcript_is_an_error_not_an_empty_document(self, client, pipeline, monkeypatch):
        monkeypatch.setattr(FakeStt, "transcribe_samples", lambda self, samples: "   ")
        assert ndjson(upload(client))[-1]["stage"] == "error"

    def test_empty_file_is_rejected(self, client, pipeline):
        assert upload(client, audio=b"").status_code == 400


class TestCache:
    def test_same_audio_is_not_transcribed_twice(self, client, pipeline):
        first = ndjson(upload(client))[-1]["result"]
        second = ndjson(upload(client))[-1]["result"]
        assert FakeStt.calls == 1
        assert second["cached"] is True
        assert second["transcript"] == first["transcript"]

    def test_different_audio_misses_the_cache(self, client, pipeline):
        upload(client, audio=b"one")
        upload(client, audio=b"two")
        assert FakeStt.calls == 2

    def test_different_extension_misses_the_cache(self, client, pipeline):
        """Same bytes, different declared format: the decoder may read them
        differently, so it must not reuse the other transcript."""
        upload(client, audio=b"same", name="a.m4a")
        upload(client, audio=b"same", name="a.mp3")
        assert FakeStt.calls == 2

    def test_cache_key_changes_with_the_model_directory(self, client, pipeline, monkeypatch):
        import config

        before = analysis_cache.key_for(b"audio", ".m4a")
        monkeypatch.setattr(config, "GIGAAM_DIR", Path("/somewhere/else"))
        assert analysis_cache.key_for(b"audio", ".m4a") != before

    def test_cache_survives_a_restart(self, client, pipeline):
        upload(client)
        FakeStt.calls = 0
        with TestClient(api.app) as restarted:
            restarted.post("/api/analyse", files={"file": ("meeting.m4a", b"fake-audio-bytes", "audio/mp4")})
        assert FakeStt.calls == 0

    def test_corrupt_entry_is_retranscribed_not_trusted(self, client, pipeline):
        upload(client)
        key = analysis_cache.key_for(b"fake-audio-bytes", ".m4a")
        analysis_cache._path(key).write_text("{broken", encoding="utf-8")
        FakeStt.calls = 0
        assert ndjson(upload(client))[-1]["result"]["cached"] is False
        assert FakeStt.calls == 1

    def test_cache_is_capped(self, client, pipeline, monkeypatch):
        monkeypatch.setattr(analysis_cache, "MAX_ENTRIES", 3)
        for index in range(6):
            upload(client, audio=f"audio-{index}".encode())
        assert len(list(analysis_cache._path("").parent.glob("*.json"))) == 3

    def test_no_temp_files_left_behind(self, client, pipeline):
        upload(client)
        assert list(analysis_cache._path("").parent.glob("*.tmp")) == []


class TestDiarizedSegments:
    """Speaker numbering is 0-based in the contract and becomes 1-based only
    where a label is printed. Adding the shift in both places renumbered every
    speaker by one and the transcript then disagreed with the document."""

    def two_turns(self):
        from diarization import Turn

        return [Turn(start=0.0, end=4.0, speaker=0), Turn(start=4.0, end=8.0, speaker=1)]

    def diarized(self, monkeypatch, turns):
        class FakeDiarizer:
            def diarize(self, samples, speakers=None):
                return turns

        monkeypatch.setattr(api, "get_diarizer", lambda: FakeDiarizer())

    def test_first_speaker_is_index_zero(self, client, pipeline, monkeypatch):
        self.diarized(monkeypatch, self.two_turns())
        result = ndjson(upload(client))[-1]["result"]
        # Over the wire segments are plain dicts, not models.
        assert [segment["speaker"] for segment in result["segments"]] == [0, 1]

    def test_label_in_the_transcript_and_in_the_segments_agree(self, client, pipeline, monkeypatch):
        """Both must say "Спикер 1" for the first voice -- one comes from
        dialogue.build_dialogue, the other the UI adds when it prints."""
        self.diarized(monkeypatch, self.two_turns())
        result = ndjson(upload(client))[-1]["result"]
        first = result["segments"][0]  # a dict over HTTP
        assert result["transcript"].startswith(f"Спикер {first['speaker'] + 1} [")

    def test_single_speaker_audio_stays_undivided(self, client, pipeline):
        result = ndjson(upload(client))[-1]["result"]
        assert result["segments"] == []


class TestSummarize:
    def test_runs_without_touching_the_audio(self, client, pipeline):
        upload(client)
        FakeStt.calls = 0
        key = ndjson(upload(client))[-1]["result"]["cache_key"]
        response = client.post("/api/summarize", json={"cache_key": key})
        assert response.status_code == 200
        assert FakeStt.calls == 0

    def test_only_masked_text_is_sent(self, client, pipeline):
        key = ndjson(upload(client))[-1]["result"]["cache_key"]
        client.post("/api/summarize", json={"cache_key": key})
        sent = pipeline.calls[0][0]
        assert "Иван" not in sent
        assert "[PERSON_1]" in sent

    def test_the_reply_is_restored_locally(self, client, pipeline):
        key = ndjson(upload(client))[-1]["result"]["cache_key"]
        body = client.post("/api/summarize", json={"cache_key": key}).json()
        assert body["reply"] == "Позвонил [PERSON_1]"
        assert body["reply_unmasked"] == "Позвонил Иван"

    def test_changing_the_focus_costs_no_new_transcription(self, client, pipeline):
        """The whole reason the pipeline was split."""
        key = ndjson(upload(client))[-1]["result"]["cache_key"]
        client.post("/api/summarize", json={"cache_key": key, "preset": "decisions"})
        client.post("/api/summarize", json={"cache_key": key, "preset": "agreements"})
        assert FakeStt.calls == 1
        assert [call[1] for call in pipeline.calls] == ["decisions", "agreements"]

    def test_focus_is_echoed_back(self, client, pipeline):
        key = ndjson(upload(client))[-1]["result"]["cache_key"]
        body = client.post("/api/summarize", json={"cache_key": key, "preset": "summary"}).json()
        assert body["preset"] == "summary"

    def test_evicted_cache_still_summarises(self, client, pipeline):
        """The cache holds eight recordings and the history holds more.

        Without the masked text coming along with the request, re-running a
        summary on a recording analysed last week answers "загрузите заново" —
        about a file the user can still see sitting in their own sidebar.
        """
        session = ndjson(upload(client))[-1]["result"]
        # Delete the file, which is exactly what evicting the entry does.
        analysis_cache._path(session["cache_key"]).unlink(missing_ok=True)
        assert analysis_cache.get(session["cache_key"]) is None
        response = client.post(
            "/api/summarize",
            json={"cache_key": session["cache_key"], "masked_text": session["masked_text"]},
        )
        assert response.status_code == 200
        assert "Иван" not in pipeline.calls[0][0]

    def test_neither_cache_nor_text_is_a_clear_404(self, client, pipeline):
        response = client.post("/api/summarize", json={"cache_key": "nope", "masked_text": ""})
        assert response.status_code == 404
        # The message must say what to do, not just that something is missing.
        assert "файл заново" in response.json()["detail"]

    def test_unknown_cache_key_is_a_404(self, client, pipeline):
        response = client.post("/api/summarize", json={"cache_key": "nope"})
        assert response.status_code == 404

    def test_actual_cost_is_reported(self, client, pipeline, monkeypatch):
        key = ndjson(upload(client))[-1]["result"]["cache_key"]
        monkeypatch.setattr(api, "_load_prices", lambda: {"a/b": {"prompt": 1.0, "completion": 2.0}})
        body = client.post("/api/summarize", json={"cache_key": key, "model": "a/b"}).json()
        # 100 prompt tokens at $1/M, 50 completion tokens at $2/M.
        assert body["cost"]["total"] == 0.0002

    def test_model_without_prices_costs_nothing_claimed(self, client, pipeline):
        key = ndjson(upload(client))[-1]["result"]["cache_key"]
        body = client.post("/api/summarize", json={"cache_key": key, "model": "unknown/x"}).json()
        assert body["cost"]["total"] is None


class TestEstimate:
    def test_short_text_is_one_request(self, client, pipeline, monkeypatch):
        monkeypatch.setattr(api, "_load_prices", lambda: {"a/b": {"prompt": 1.0, "completion": 2.0}})
        body = client.post("/api/estimate", json={"chars": 20_000, "model": "a/b"}).json()
        assert body["requests"] == 1
        assert body["total"] > 0

    def test_long_text_counts_every_request(self, client, pipeline, monkeypatch):
        """An hour-long meeting is not one request. Quoting one would
        understate the bill several times over."""
        monkeypatch.setattr(api, "_load_prices", lambda: {"a/b": {"prompt": 1.0, "completion": 2.0}})
        short = client.post("/api/estimate", json={"chars": 20_000, "model": "a/b"}).json()
        long = client.post("/api/estimate", json={"chars": 400_000, "model": "a/b"}).json()
        assert long["requests"] > 10
        assert long["total"] > short["total"] * 5

    def test_unpriced_model_yields_no_money(self, client, pipeline):
        body = client.post("/api/estimate", json={"chars": 20_000, "model": "unknown/x"}).json()
        assert body["total"] is None
        assert body["tokens_in"] > 0

    def test_estimate_matches_the_tokens_the_model_actually_sees(self, client, pipeline, monkeypatch):
        """The estimate is derived from the length of the text that would be
        sent, so feeding back the real masked length must predict the same
        input tokens as the pre-flight figure."""
        result = ndjson(upload(client))[-1]["result"]
        rough = client.post("/api/estimate", json={"chars": len(result["masked_text"])}).json()
        assert rough["tokens_in"] == llm.tokens_for(len(result["masked_text"]))


class TestEstimateMath:
    def test_plan_follows_the_split_threshold(self):
        assert llm.plan_summary(llm.MEETING_MAP_CHARS)["requests"] == 1
        assert llm.plan_summary(llm.MEETING_MAP_CHARS + 1)["requests"] > 1

    def test_chunk_count_is_never_zero_once_over_the_threshold(self):
        for chars in (llm.MEETING_MAP_CHARS + 1, 100_000, 1_000_000):
            assert llm.plan_summary(chars)["chunks"] >= 1

    def test_exact_cost_uses_reported_tokens(self):
        assert llm.exact_cost(1_000_000, 1_000_000, 1.0, 2.0) == {"input": 1.0, "output": 2.0, "total": 3.0}

    def test_missing_tokens_do_not_become_zero(self):
        assert llm.exact_cost(None, 100, 1.0, 2.0)["total"] is None
