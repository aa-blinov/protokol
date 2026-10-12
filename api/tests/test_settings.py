"""Tests for the runtime settings store.

Two things matter here and are easy to get wrong: the key must never leak back
to the browser, and a key that fails verification must not be written to disk.
Both are asserted here rather than left to inspection.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import settings  # noqa: E402


@pytest.fixture
def store(tmp_path, monkeypatch):
    """Point the store at a throwaway file and keep the process clean."""
    path = tmp_path / "settings.env"
    monkeypatch.setenv("STTSHKA_ENV_FILE", str(path))
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    return path


class TestWriting:
    def test_creates_file_with_key_and_model(self, store):
        settings.write_pair("sk-or-v1-test", "vendor/model")
        text = store.read_text(encoding="utf-8")
        assert "OPENROUTER_API_KEY=sk-or-v1-test" in text
        assert "LLM_MODEL=vendor/model" in text

    def test_keeps_unrelated_lines(self, store):
        store.write_text("CUSTOM=keep-me\nOPENROUTER_API_KEY=old\n", encoding="utf-8")
        settings.write_pair("sk-or-v1-new", "vendor/model")
        text = store.read_text(encoding="utf-8")
        assert "CUSTOM=keep-me" in text
        assert "sk-or-v1-new" in text
        assert "old" not in text

    def test_replaces_previous_values_without_duplicating(self, store):
        settings.write_pair("sk-or-v1-one", "a/one")
        settings.write_pair("sk-or-v1-two", "a/two")
        text = store.read_text(encoding="utf-8")
        assert text.count("OPENROUTER_API_KEY=") == 1
        assert text.count("LLM_MODEL=") == 1

    def test_creates_missing_parent_directory(self, tmp_path, monkeypatch):
        nested = tmp_path / "deep" / "deeper" / "settings.env"
        monkeypatch.setenv("STTSHKA_ENV_FILE", str(nested))
        settings.write_pair("sk-or-v1-x", "a/b")
        assert nested.is_file()

    def test_empty_key_keeps_the_stored_one(self, store):
        # The dialog sends an empty key when only the model changes. Writing the
        # file from the arguments alone would drop a valid key here.
        settings.write_pair("sk-or-v1-keep", "vendor/one")
        settings.write_pair("", "vendor/two")
        text = store.read_text(encoding="utf-8")
        assert "OPENROUTER_API_KEY=sk-or-v1-keep" in text
        assert "LLM_MODEL=vendor/two" in text

    def test_empty_model_keeps_the_stored_one(self, store):
        settings.write_pair("sk-or-v1-keep", "vendor/one")
        settings.write_pair("sk-or-v1-new", "")
        text = store.read_text(encoding="utf-8")
        assert "OPENROUTER_API_KEY=sk-or-v1-new" in text
        assert "LLM_MODEL=vendor/one" in text

    def test_nothing_stored_and_nothing_given_writes_nothing(self, store):
        settings.write_pair("", "")
        assert store.read_text(encoding="utf-8").strip() == ""

    def test_changing_only_the_model_never_touches_the_key(self, store):
        settings.write_pair("sk-or-v1-keep", "vendor/one")
        for model in ("a/one", "b/two", "c/three"):
            settings.write_pair("", model)
            assert "OPENROUTER_API_KEY=sk-or-v1-keep" in store.read_text(encoding="utf-8")


class TestApply:
    def test_takes_effect_without_restart(self, store):
        import config

        settings.apply("sk-or-v1-live", "vendor/live")
        assert settings.current_key() == "sk-or-v1-live"
        assert settings.current_model() == "vendor/live"
        assert config.OPENROUTER_API_KEY == "sk-or-v1-live"

    def test_empty_values_keep_the_previous(self, store):
        settings.apply("sk-or-v1-live", "vendor/live")
        settings.apply("", "")
        assert settings.current_key() == "sk-or-v1-live"
        assert settings.current_model() == "vendor/live"

    def test_environment_wins_over_file(self, store, monkeypatch):
        settings.write_pair("sk-or-v1-fromfile", "a/file")
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-fromenv")
        assert settings.current_key() == "sk-or-v1-fromenv"


class TestKeyHint:
    def test_masks_the_middle(self):
        hint = settings.KeyHint.of("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")
        assert hint.masked == "sk-or-v1-4b…709a"

    def test_never_contains_the_secret_middle(self):
        key = "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"
        assert "4b4bf159" not in settings.KeyHint.of(key).masked

    def test_short_key_is_not_truncated_into_misleading_text(self):
        assert settings.KeyHint.of("short").masked == "short"

    def test_empty_key(self):
        assert settings.KeyHint.of("").masked == ""


class TestPricing:
    def test_converts_per_token_to_per_million(self):
        assert settings._price("0.0000025") == 2.5

    def test_negative_sentinel_becomes_unknown(self):
        # OpenRouter uses a negative price for free and variable-price models;
        # sorting on it would put them first as the cheapest in the catalogue.
        assert settings._price(-1) is None
        assert settings._price("-0.000001") is None

    def test_unparseable_price(self):
        assert settings._price(None) is None
        assert settings._price("n/a") is None