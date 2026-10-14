"""The OpenRouter client: what goes on the wire, and what is done with what comes back.

httpx is replaced by a scripted fake, so nothing here reaches the network.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
import llm  # noqa: E402


class FakeResponse:
    def __init__(self, status: int = 200, body: dict | None = None, text: str = ""):
        self.status_code = status
        self._body = body or {}
        self.text = text or str(self._body)

    def json(self) -> dict:
        return self._body


def ok(content: str | None, finish: str = "stop", tokens_in: int = 100, tokens_out: int = 50) -> FakeResponse:
    return FakeResponse(
        200,
        {
            "model": "test/model",
            "choices": [{"message": {"content": content}, "finish_reason": finish}],
            "usage": {"prompt_tokens": tokens_in, "completion_tokens": tokens_out},
        },
    )


@pytest.fixture
def wire(monkeypatch):
    """Scripted httpx.post: returns the queued responses and records each payload."""
    queue: list = []
    sent: list[dict] = []

    def fake_post(url, json=None, headers=None, timeout=None):
        sent.append(json)
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    monkeypatch.setattr(llm.time, "sleep", lambda seconds: None)
    return queue, sent


def client() -> llm.OpenRouterClient:
    return llm.OpenRouterClient("test-key")


def test_request_asks_for_no_data_retention_and_low_temperature(wire):
    queue, sent = wire
    queue.append(ok("Сводка"))
    client().complete("[PERSON_1] звонил", "test/model", system="sys")
    payload = sent[0]
    assert payload["provider"] == {"data_collection": "deny"}
    assert payload["temperature"] == llm.TEMPERATURE
    assert payload["max_tokens"] == llm.MAX_OUTPUT_TOKENS


def test_transcript_is_framed_as_data(wire):
    queue, sent = wire
    queue.append(ok("Сводка"))
    client().complete("[PERSON_1] звонил", "test/model", system="sys")
    user = sent[0]["messages"][1]["content"]
    assert user.startswith("<transcript>\n") and user.endswith("\n</transcript>")
    assert "[PERSON_1] звонил" in user


def test_zdr_and_reasoning_are_sent_when_configured(wire, monkeypatch):
    queue, sent = wire
    queue.append(ok("Сводка"))
    monkeypatch.setattr(config, "LLM_ZDR", True)
    monkeypatch.setattr(config, "LLM_REASONING_EFFORT", "low")
    client().complete("текст", "test/model", system="sys")
    assert sent[0]["provider"] == {"data_collection": "deny", "zdr": True}
    assert sent[0]["reasoning"] == {"effort": "low"}


def test_unknown_data_collection_value_falls_back_to_deny():
    assert llm._provider_data_collection("publish-everything") == "deny"
    assert llm._provider_data_collection("allow") == "allow"
    assert llm._provider_data_collection("deny") == "deny"


def test_rate_limit_is_retried_then_succeeds(wire):
    queue, sent = wire
    queue.extend([FakeResponse(429, text="slow down"), ok("Сводка")])
    assert client().complete("текст", "test/model", system="sys").reply == "Сводка"
    assert len(sent) == 2


def test_network_error_is_retried(wire):
    queue, sent = wire
    import httpx

    queue.extend([httpx.ConnectError("boom"), ok("Сводка")])
    assert client().complete("текст", "test/model", system="sys").reply == "Сводка"
    assert len(sent) == 2


def test_client_error_is_not_retried(wire):
    queue, sent = wire
    queue.append(FakeResponse(400, text="bad request"))
    with pytest.raises(llm.LlmError, match="400"):
        client().complete("текст", "test/model", system="sys")
    assert len(sent) == 1


def test_persistent_rate_limit_gives_up_with_the_last_error(wire):
    queue, sent = wire
    queue.extend([FakeResponse(503, text="down")] * 4)
    with pytest.raises(llm.LlmError, match="503"):
        client().complete("текст", "test/model", system="sys")
    assert len(sent) == len(llm.RETRY_DELAYS) + 1


def test_reply_cut_at_the_cap_is_retried_with_more_room(wire):
    queue, sent = wire
    queue.extend([ok("Обрезанный отв", finish="length"), ok("Полный ответ")])
    result = client().complete("текст", "test/model", system="sys", max_tokens=1000)
    assert result.reply == "Полный ответ"
    assert [payload["max_tokens"] for payload in sent] == [1000, 2000]
    # Both requests were billed, the cut one included.
    assert result.tokens_out == 100 and result.tokens_in == 200


def test_reply_that_never_fits_is_an_error_not_a_short_summary(wire):
    queue, _ = wire
    queue.extend([ok("Обрезано", finish="length")] * 10)
    with pytest.raises(llm.LlmError, match="неполной"):
        client().complete("текст", "test/model", system="sys", max_tokens=llm.OUTPUT_CAP_CEILING)


def test_reasoning_that_used_the_whole_cap_is_retried(wire):
    queue, sent = wire
    queue.extend([ok(None, finish="length"), ok("Сводка")])
    assert client().complete("текст", "test/model", system="sys", max_tokens=500).reply == "Сводка"
    assert len(sent) == 2


def test_empty_reply_that_was_not_cut_is_an_error(wire):
    queue, _ = wire
    queue.append(ok(None, finish="stop"))
    with pytest.raises(llm.LlmError, match="empty"):
        client().complete("текст", "test/model", system="sys")


def test_long_meeting_bills_every_request_not_only_the_last(wire, monkeypatch):
    queue, sent = wire
    long_text = "\n".join(f"Спикер 1 [0:{i % 60:02d}]: " + "текст " * 30 for i in range(200))
    parts = len(llm.split_masked_text(long_text))
    queue.extend([ok(f"часть {n}", tokens_in=1000, tokens_out=100) for n in range(parts)])
    queue.append(ok("Итог", tokens_in=500, tokens_out=200))
    result = client().complete_meeting(long_text, "test/model", "decisions", "")
    assert result.reply == "Итог"
    assert result.tokens_in == parts * 1000 + 500
    assert result.tokens_out == parts * 100 + 200


def test_final_composition_is_framed_as_notes(wire):
    queue, sent = wire
    long_text = "\n".join(f"Спикер 1 [0:{i % 60:02d}]: " + "текст " * 30 for i in range(200))
    parts = len(llm.split_masked_text(long_text))
    queue.extend([ok("часть") for _ in range(parts)] + [ok("Итог")])
    client().complete_meeting(long_text, "test/model", "decisions", "")
    assert sent[-1]["messages"][1]["content"].startswith("<notes>")


def test_chunk_compression_turns_reasoning_off_and_the_final_call_keeps_the_default(wire, monkeypatch):
    queue, sent = wire
    monkeypatch.setattr(config, "LLM_REASONING_EFFORT", "")
    long_text = "\n".join(f"Спикер 1 [0:{i % 60:02d}]: " + "текст " * 30 for i in range(200))
    parts = len(llm.split_masked_text(long_text))
    queue.extend([ok("тезисы") for _ in range(parts)] + [ok("Итог")])
    client().complete_meeting(long_text, "test/model", "decisions", "")
    assert all(payload.get("reasoning") == {"effort": "none"} for payload in sent[:-1])
    assert "reasoning" not in sent[-1]
