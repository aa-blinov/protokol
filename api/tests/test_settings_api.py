"""Tests for the settings endpoints.

Two properties matter more than the shapes here: a key that OpenRouter rejects
must not reach disk, and the key must never appear in a response. Both are easy
to regress silently, so they are asserted directly against the HTTP layer.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
import main as api  # noqa: E402
import settings  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("STTSHKA_ENV_FILE", str(tmp_path / "settings.env"))
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    # The address too: any earlier test that saved a different service writes it
    # into the config module, and `base_url` is reported straight from there.
    monkeypatch.delenv("OPENROUTER_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_PROVIDER_KEYS", raising=False)
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "")
    monkeypatch.setattr(config, "OPENROUTER_BASE_URL", settings.DEFAULT_BASE_URL)
    with TestClient(api.app) as test_client:
        yield test_client


class TestReadSettings:
    def test_reports_missing_key(self, client):
        body = client.get("/api/settings").json()
        assert body["has_key"] is False
        assert body["key_hint"] == ""

    def test_never_returns_the_key(self, client, monkeypatch):
        secret = "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"
        monkeypatch.setattr(settings, "verify", lambda key, base_url="": {"ok": True, "detail": "ок"})
        client.post("/api/settings", json={"key": secret})
        raw = client.get("/api/settings").text
        assert secret not in raw
        assert "4b4bf159" not in raw
        assert client.get("/api/settings").json()["key_hint"] == "sk-or-v1-4b…709a"

    def test_points_at_the_key_page(self, client):
        body = client.get("/api/settings").json()
        assert body["key_page"].startswith("https://openrouter.ai")
        assert body["base_url"].startswith("https://")


class TestSaveSettings:
    def test_rejected_key_is_not_written(self, client, monkeypatch):
        monkeypatch.setattr(settings, "verify", lambda key, base_url="": {"ok": False, "detail": "401"})
        response = client.post("/api/settings", json={"key": "sk-or-v1-bad"})
        assert response.json()["ok"] is False
        assert not (Path(client.app) if False else Path(settings.settings_path())).is_file()

    def test_good_key_is_written_and_applies_at_once(self, client, monkeypatch):
        monkeypatch.setattr(settings, "verify", lambda key, base_url="": {"ok": True, "detail": "ок"})
        response = client.post("/api/settings", json={"key": "sk-or-v1-good", "model": "a/b"})
        assert response.json()["ok"] is True
        # No restart: the running process already sees the new values.
        assert settings.current_key() == "sk-or-v1-good"
        assert settings.current_model() == "a/b"

    def test_empty_key_keeps_the_stored_one(self, client, monkeypatch):
        monkeypatch.setattr(settings, "verify", lambda key, base_url="": {"ok": True, "detail": "ок"})
        client.post("/api/settings", json={"key": "sk-or-v1-good"})
        client.post("/api/settings", json={"key": "", "model": "vendor/other"})
        assert settings.current_key() == "sk-or-v1-good"
        assert settings.current_model() == "vendor/other"


class TestVerifyKey:
    def test_reports_failure_without_saving(self, client, monkeypatch):
        monkeypatch.setattr(settings, "verify", lambda key, base_url="": {"ok": False, "detail": "401"})
        body = client.post("/api/settings/verify", json={"key": "sk-or-v1-bad"}).json()
        assert body["ok"] is False
        assert body["settings"] is None
        assert settings.current_key() == ""

    def test_remembers_on_request(self, client, monkeypatch):
        monkeypatch.setattr(settings, "verify", lambda key, base_url="": {"ok": True, "detail": "ок"})
        body = client.post(
            "/api/settings/verify", json={"key": "sk-or-v1-good", "remember": True}
        ).json()
        assert body["ok"] is True
        assert body["settings"]["has_key"] is True
        assert settings.current_key() == "sk-or-v1-good"


class TestModels:
    def test_endpoint_passes_the_catalogue_through(self, client, monkeypatch):
        catalogue = [
            {"id": "free/one", "name": "Free", "context": 2000, "prompt_price": 0.0, "completion_price": 0.0},
            {"id": "paid/one", "name": "Paid", "context": 1000, "prompt_price": 1.0, "completion_price": 2.0},
        ]
        monkeypatch.setattr(settings, "list_models", lambda key: catalogue)
        assert client.get("/api/models").json() == catalogue

    def test_cheapest_first_and_unpriced_last(self):
        # Ordering lives in settings._sort_models, so it is tested there rather
        # than through the endpoint -- mocking list_models would hide it.
        unsorted = [
            {"id": "unknown/one", "prompt_price": None},
            {"id": "paid/one", "prompt_price": 1.0},
            {"id": "free/one", "prompt_price": 0.0},
        ]
        assert [m["id"] for m in settings._sort_models(unsorted)] == [
            "free/one",
            "paid/one",
            "unknown/one",
        ]

    def test_upstream_failure_becomes_502(self, client, monkeypatch):
        def boom(key):
            raise RuntimeError("OpenRouter ответил 500")

        monkeypatch.setattr(settings, "list_models", boom)
        assert client.get("/api/models").status_code == 502


class TestHealthFollowsSettings:
    def test_llm_configured_reflects_the_store(self, client, monkeypatch):
        monkeypatch.setattr(settings, "verify", lambda key, base_url="": {"ok": True, "detail": "ок"})
        assert client.get("/api/health").json()["llm_configured"] is False
        client.post("/api/settings", json={"key": "sk-or-v1-good"})
        assert client.get("/api/health").json()["llm_configured"] is True

class TestCustomProvider:
    """The address is configurable; OpenRouter is only the default."""

    def test_base_url_is_reported(self, client):
        body = client.get("/api/settings").json()
        assert body["base_url"] == "https://openrouter.ai/api/v1"

    def test_custom_address_is_saved_and_used(self, client, monkeypatch):
        monkeypatch.setattr(settings, "verify", lambda key, base_url="": {"ok": True, "detail": "ок"})
        client.post(
            "/api/settings",
            json={"key": "sk-custom", "base_url": "https://api.example.com/v1", "model": "m/x"},
        )
        assert settings.current_base_url() == "https://api.example.com/v1"
        assert client.get("/api/settings").json()["base_url"] == "https://api.example.com/v1"

    def test_address_survives_a_model_only_change(self, client, monkeypatch):
        monkeypatch.setattr(settings, "verify", lambda key, base_url="": {"ok": True, "detail": "ок"})
        client.post(
            "/api/settings",
            json={"key": "sk-custom", "base_url": "https://api.example.com/v1"},
        )
        client.post("/api/settings", json={"key": "", "model": "other/model"})
        assert settings.current_base_url() == "https://api.example.com/v1"
        assert settings.current_key() == "sk-custom"

    def test_verification_receives_the_chosen_address(self, client, monkeypatch):
        seen = {}

        def capture(key, base_url=""):
            seen["base_url"] = base_url
            return {"ok": True, "detail": "ок"}

        monkeypatch.setattr(settings, "verify", capture)
        client.post("/api/settings/verify", json={"key": "k", "base_url": "https://api.example.com/v1"})
        assert seen["base_url"] == "https://api.example.com/v1"

    def test_rejected_key_from_another_provider_is_not_stored(self, client, monkeypatch):
        monkeypatch.setattr(
            settings, "verify", lambda key, base_url="": {"ok": False, "detail": "Ключ отклонён (401)"}
        )
        body = client.post(
            "/api/settings",
            json={"key": "sk-wrong", "base_url": "https://api.example.com/v1"},
        ).json()
        assert body["ok"] is False
        assert settings.current_key() == ""
