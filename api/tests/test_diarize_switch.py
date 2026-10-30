"""The speaker switch: off keeps the speaker model out of the run, and the cache keeps that apart."""

import json
import sys
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import analysis_cache  # noqa: E402
import main as api  # noqa: E402


class FakeStt:
    def transcribe_samples(self, samples):
        return "Иван позвонил в 15:00"


class FakeNer:
    def predict(self, text):
        return []


@pytest.fixture
def pipeline(tmp_path, monkeypatch):
    """Fake the models, and record every time the speaker model is asked for."""
    monkeypatch.setenv("STTSHKA_ENV_FILE", str(tmp_path / "settings.env"))
    monkeypatch.setattr(api.Stt, "decode", staticmethod(lambda audio: np.zeros(16_000, dtype=np.float32)))
    monkeypatch.setattr(api, "get_stt", lambda: FakeStt())
    monkeypatch.setattr(api, "get_ner", lambda: FakeNer())
    asked = []

    def speaker_model():
        asked.append(True)
        return None

    monkeypatch.setattr(api, "get_diarizer", speaker_model)
    return asked


@pytest.fixture
def client(pipeline):
    with TestClient(api.app) as test_client:
        yield test_client


def stages(response) -> list[str]:
    return [json.loads(line)["stage"] for line in response.text.splitlines() if line.strip()]


def test_switched_off_the_speaker_model_is_not_asked_for(pipeline):
    events = list(api._analyse(b"off", ".m4a", None, diarize=False))
    assert events[-1][0] == "done"
    assert pipeline == []


def test_switched_on_the_speaker_model_is_asked_for(pipeline):
    list(api._analyse(b"on", ".m4a"))
    assert pipeline == [True]


def test_the_route_passes_the_switch_through(client, pipeline):
    off = client.post("/api/analyse", files={"file": ("call.m4a", b"off", "audio/mp4")}, data={"diarize": "false"})
    assert stages(off)[-1] == "done"
    assert pipeline == []
    on = client.post("/api/analyse", files={"file": ("call.m4a", b"on", "audio/mp4")})
    assert stages(on)[-1] == "done"
    assert pipeline == [True]


def test_switched_off_shares_the_entry_of_a_recording_with_no_speaker_models(monkeypatch):
    monkeypatch.setattr(analysis_cache, "_diarization_installed", lambda: False)
    assert analysis_cache.key_for(b"same", ".m4a", None, diarize=False) == analysis_cache.key_for(b"same", ".m4a")


def test_switched_off_is_a_separate_entry_when_the_speaker_models_are_installed(monkeypatch):
    monkeypatch.setattr(analysis_cache, "_diarization_installed", lambda: True)
    assert analysis_cache.key_for(b"same", ".m4a", None, diarize=False) != analysis_cache.key_for(b"same", ".m4a")
