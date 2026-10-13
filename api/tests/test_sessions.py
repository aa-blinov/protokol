"""History storage.

The desktop shell takes a random free port on every launch, and Chromium scopes
localStorage to the origin including the port, so keeping recordings in the
browser meant an empty history on every start. These tests pin the file-backed
behaviour that replaced it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main as api  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("STTSHKA_ENV_FILE", str(tmp_path / "settings.env"))
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with TestClient(api.app) as test_client:
        yield test_client


def make_session(name: str) -> dict:
    return {
        "id": name,
        "name": name,
        "createdAt": "2026-10-12T12:00:00.000Z",
        "result": {"transcript": f"текст {name}", "entities": [], "segments": []},
    }


class TestSessionsRoundTrip:
    def test_missing_file_reads_as_empty(self, client):
        assert client.get("/api/sessions").json() == []

    def test_saved_session_comes_back(self, client):
        client.put("/api/sessions", json=[make_session("a.mp3")])
        body = client.get("/api/sessions").json()
        assert len(body) == 1
        assert body[0]["name"] == "a.mp3"

    def test_history_survives_a_restart(self, client, tmp_path):
        """The whole point: storage must not depend on the origin."""
        client.put("/api/sessions", json=[make_session("a.mp3"), make_session("b.mp3")])
        # A second app instance reads the same file, as on the next launch.
        with TestClient(api.app) as restarted:
            assert len(restarted.get("/api/sessions").json()) == 2

    def test_survives_a_different_port(self, client, monkeypatch):
        monkeypatch.setenv("PORT", "9999")
        client.put("/api/sessions", json=[make_session("a.mp3")])
        with TestClient(api.app) as on_another_port:
            assert len(on_another_port.get("/api/sessions").json()) == 1

    def test_write_replaces_rather_than_appends(self, client):
        client.put("/api/sessions", json=[make_session("a.mp3")])
        client.put("/api/sessions", json=[make_session("b.mp3")])
        body = client.get("/api/sessions").json()
        assert [s["name"] for s in body] == ["b.mp3"]


class TestSessionsLimits:
    def test_history_is_capped(self, client):
        client.put("/api/sessions", json=[make_session(f"{i}.mp3") for i in range(80)])
        assert len(client.get("/api/sessions").json()) == 50

    def test_corrupt_file_reads_as_empty(self, client, tmp_path):
        (tmp_path / "sessions.json").write_text("{not json", encoding="utf-8")
        assert client.get("/api/sessions").json() == []

    def test_non_list_file_reads_as_empty(self, client, tmp_path):
        (tmp_path / "sessions.json").write_text('{"nope": 1}', encoding="utf-8")
        assert client.get("/api/sessions").json() == []


class TestStorageLocation:
    def test_file_sits_next_to_the_settings(self, client, tmp_path):
        client.put("/api/sessions", json=[make_session("a.mp3")])
        assert (tmp_path / "sessions.json").is_file()

    def test_no_temp_file_left_behind(self, client, tmp_path):
        """The write goes through a temp file so a crash cannot truncate history."""
        client.put("/api/sessions", json=[make_session("a.mp3")])
        assert list(tmp_path.glob("*.tmp")) == []

class TestSummariesPerMode:
    """A recording keeps one summary per mode instead of a single one.

    Switching the mode used to overwrite what was there, so the earlier summary
    was gone for good. The file also predates this, which is why a stored
    session with a single `summary` still has to come back usable.
    """

    def analysis(self) -> dict:
        return {"cache_key": "k", "transcript": "текст", "masked_text": "текст",
                "entity_map": {}, "entities": [], "segments": [], "duration_sec": 1.0,
                "timings": {}, "cached": False}

    def summary(self, preset: str, reply: str) -> dict:
        return {"reply": reply, "reply_unmasked": reply, "llm_model": "m", "preset": preset,
                "tokens_in": 1, "tokens_out": 1,
                "cost": {"input": 0.0, "output": 0.0, "total": 0.0}, "timings": {}}

    def test_two_modes_are_both_kept(self, client):
        client.put("/api/sessions", json=[{
            "id": "a", "name": "a.mp3", "createdAt": "2026-10-12T12:00:00.000Z",
            "analysis": self.analysis(),
            "summaries": {"agreements": self.summary("agreements", "договорились"),
                          "brief": self.summary("brief", "кратко")},
        }])
        stored = client.get("/api/sessions").json()[0]
        assert set(stored["summaries"]) == {"agreements", "brief"}
        assert stored["summaries"]["brief"]["reply"] == "кратко"

    def test_old_single_summary_becomes_its_own_mode(self, client):
        client.put("/api/sessions", json=[{
            "id": "a", "name": "a.mp3", "createdAt": "2026-10-12T12:00:00.000Z",
            "analysis": self.analysis(),
            "summary": self.summary("agreements", "договорились"),
        }])
        stored = client.get("/api/sessions").json()[0]
        assert "summary" not in stored
        assert stored["summaries"]["agreements"]["reply"] == "договорились"

    def test_recording_without_a_summary_reads_as_an_empty_map(self, client):
        client.put("/api/sessions", json=[{
            "id": "a", "name": "a.mp3", "createdAt": "2026-10-12T12:00:00.000Z",
            "analysis": self.analysis(), "summary": None,
        }])
        assert client.get("/api/sessions").json()[0]["summaries"] == {}
