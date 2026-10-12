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