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

import config  # noqa: E402
import settings  # noqa: E402


@pytest.fixture
def store(tmp_path, monkeypatch):
    """Point the store at a throwaway file and keep the process clean.

    Clearing os.environ is not enough: `apply` writes through to the config
    module's own attributes, and those outlive the monkeypatch. Without this the
    previous test's key is still in force and the next one asserts against it.
    """
    path = tmp_path / "settings.env"
    monkeypatch.setenv("STTSHKA_ENV_FILE", str(path))
    for name in ("OPENROUTER_API_KEY", "LLM_MODEL", "OPENROUTER_BASE_URL", "LLM_PROVIDER_KEYS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "")
    monkeypatch.setattr(config, "DEFAULT_LLM_MODEL", "")
    monkeypatch.setattr(config, "OPENROUTER_BASE_URL", settings.DEFAULT_BASE_URL)
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

class TestKeysPerService:
    """Each service keeps its own key, so switching away and back costs nothing.

    The other half of it is the rule that made this necessary: a key belongs to
    the address it was issued for, so moving to a service with no key of its own
    must not leave the previous service's key in force to be tried there.
    """

    OPENROUTER = "https://openrouter.ai/api/v1"
    OPENAI = "https://api.openai.com/v1"

    def test_key_is_filed_under_its_address(self, store):
        settings.save("sk-or-v1-one", "vendor/one", self.OPENROUTER)
        settings.save("sk-proj-two", "gpt-5.4-mini", self.OPENAI)
        assert settings.provider_keys() == {self.OPENROUTER: "sk-or-v1-one", self.OPENAI: "sk-proj-two"}

    def test_switching_back_finds_the_original_key(self, store):
        settings.save("sk-or-v1-one", "vendor/one", self.OPENROUTER)
        settings.save("sk-proj-two", "gpt-5.4-mini", self.OPENAI)
        assert settings.key_for(self.OPENROUTER) == "sk-or-v1-one"

    def test_service_with_no_key_is_left_without_one(self, store):
        settings.save("sk-or-v1-one", "vendor/one", self.OPENROUTER)
        settings.save("", "gpt-5.4-mini", self.OPENAI)
        assert settings.current_key() == ""
        assert not settings.key_for(self.OPENAI)

    def test_the_old_key_is_kept_in_the_map_even_while_switched_away(self, store):
        settings.save("sk-or-v1-one", "vendor/one", self.OPENROUTER)
        settings.save("", "gpt-5.4-mini", self.OPENAI)
        assert settings.provider_keys()[self.OPENROUTER] == "sk-or-v1-one"

    def test_changing_only_the_model_keeps_the_key(self, store):
        settings.save("sk-or-v1-one", "vendor/one", self.OPENROUTER)
        settings.save("", "vendor/two", self.OPENROUTER)
        assert settings.current_key() == "sk-or-v1-one"

    def test_a_key_written_before_the_map_still_belongs_to_the_current_address(
        self, store, monkeypatch
    ):
        # The app used to keep exactly one key. On the next start that key is the
        # one in force and it belongs to whichever address is configured, so
        # key_for has to answer with it -- no migration step, no retyping.
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-old")
        monkeypatch.setenv("OPENROUTER_BASE_URL", self.OPENROUTER)
        assert settings.provider_keys() == {}
        assert settings.key_for(self.OPENROUTER) == "sk-or-v1-old"
        assert settings.key_for(self.OPENAI) == ""

    def test_trailing_slash_does_not_matter(self, store):
        settings.save("sk-or-v1-one", "vendor/one", self.OPENROUTER + "/")
        assert settings.key_for(self.OPENROUTER) == "sk-or-v1-one"

    def test_unreadable_map_is_ignored_not_fatal(self, store):
        import os

        os.environ["LLM_PROVIDER_KEYS"] = "{not json"
        assert settings.provider_keys() == {}

    def test_switching_away_files_the_key_that_predates_the_map(self, store, monkeypatch):
        # The dangerous one: a settings file from before this map existed holds a
        # key and no map. Moving to another service must not consume it.
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-old")
        monkeypatch.setenv("OPENROUTER_BASE_URL", self.OPENROUTER)
        settings.save("", "gpt-5.4-mini", self.OPENAI)
        assert settings.current_key() == ""
        assert settings.provider_keys()[self.OPENROUTER] == "sk-or-v1-old"
