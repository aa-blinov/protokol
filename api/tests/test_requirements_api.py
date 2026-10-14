"""The summary endpoint: what the model is handed in the requirement, and what it may not get."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import llm  # noqa: E402
import main as api  # noqa: E402
from masking import Span  # noqa: E402

MASKED = "[PERSON_1] обсуждал бюджет. [PHONE_1] — рабочий номер."
ENTITY_MAP = {"PERSON_1": "Иван Сергеевич Петров", "PHONE_1": "+7 916 555-01-02"}


def fake_spans(text: str) -> list[Span]:
    """Stands in for the NER model: knows two people and the phone number."""
    spans = []
    for needle, label in [("Петров", "LAST_NAME"), ("Петрову", "LAST_NAME"), ("Марию Иванову", "FIRST_NAME"), ("Марию", "FIRST_NAME")]:
        for match in re.finditer(re.escape(needle), text):
            spans.append(Span(match.start(), match.end(), label, 0.99))
    return spans


class RecordingLlm:
    def __init__(self, reply: str = "Сводка: [PERSON_1] подтвердил бюджет."):
        self.calls: list[tuple[str, str, str, str]] = []
        self.reply = reply

    def complete_meeting(self, masked_text, model, preset, extra=""):
        self.calls.append((masked_text, model, preset, extra))
        return llm.LlmResult(reply=self.reply, model=model, tokens_in=10, tokens_out=5)


@pytest.fixture
def server(monkeypatch):
    recorder = RecordingLlm()
    monkeypatch.setattr(api, "get_llm", lambda: recorder)
    monkeypatch.setattr(api, "_spans", fake_spans)
    return TestClient(api.app), recorder


def summarize(client, extra):
    return client.post(
        "/api/summarize",
        json={
            "cache_key": "not-cached",
            "model": "test/model",
            "preset": "decisions",
            "extra": extra,
            "masked_text": MASKED,
            "entity_map": ENTITY_MAP,
        },
    )


def test_requirement_naming_a_known_person_reaches_the_model_as_a_token(server):
    client, recorder = server
    response = summarize(client, "Выдели решения, которые озвучил Петров.")
    assert response.status_code == 200
    extra = recorder.calls[0][3]
    assert "[PERSON_1]" in extra
    assert "Петров" not in extra


def test_requirement_naming_an_unknown_person_is_refused_before_anything_is_sent(server):
    client, recorder = server
    response = summarize(client, "Спроси, что сказала Марию Иванову.")
    assert response.status_code == 422
    assert "Марию Иванову" in response.json()["detail"]
    assert recorder.calls == []


def test_no_requirement_sends_nothing_extra(server):
    client, recorder = server
    assert summarize(client, "").status_code == 200
    assert recorder.calls[0][3] == ""


def test_token_the_model_invented_is_reported_as_a_warning(monkeypatch):
    recorder = RecordingLlm(reply="Итог: [PERSON_1] и [PERSON_7] согласовали срок.")
    monkeypatch.setattr(api, "get_llm", lambda: recorder)
    monkeypatch.setattr(api, "_spans", fake_spans)
    response = TestClient(api.app).post(
        "/api/summarize",
        json={"cache_key": "not-cached", "model": "test/model", "preset": "decisions", "masked_text": MASKED, "entity_map": ENTITY_MAP},
    )
    body = response.json()
    assert len(body["warnings"]) == 1
    assert "PERSON_7" in body["warnings"][0]
    # The known token is restored; the invented one stays visible for the user to see.
    assert "Иван Сергеевич Петров" in body["reply_unmasked"]
    assert "[PERSON_7]" in body["reply_unmasked"]


def test_raw_llm_passthrough_is_gone():
    client = TestClient(api.app)
    assert client.post("/api/llm", json={"masked_text": "текст", "model": "test/model"}).status_code in (404, 405)
