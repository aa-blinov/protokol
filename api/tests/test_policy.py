"""Organisation policy file: what is applied, what is reported."""

import json

import policy


def _write(tmp_path, data):
    file = tmp_path / "policy.json"
    file.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
    return file


def test_missing_file_means_no_policy(tmp_path):
    loaded = policy.load(tmp_path / "absent.json")
    assert not loaded.present
    assert loaded.errors == ()


def test_valid_policy_is_applied(tmp_path):
    loaded = policy.load(
        _write(
            tmp_path,
            {
                "base_url": "https://llm.example.ru/v1/",
                "lock_settings": True,
                "retention_days": 30,
                "allow_export": False,
                "zdr": True,
                "data_collection": "deny",
            },
        )
    )
    assert loaded.present and loaded.errors == ()
    assert loaded.base_url == "https://llm.example.ru/v1"
    assert loaded.lock_settings is True
    assert loaded.retention_days == 30
    assert loaded.allow_export is False
    assert loaded.zdr is True
    assert loaded.data_collection == "deny"


def test_bad_values_are_reported_and_the_rest_still_applies(tmp_path):
    loaded = policy.load(
        _write(
            tmp_path,
            {
                "base_url": "ftp://llm.example.ru",
                "retention_days": 0,
                "zdr": "yes",
                "lock_settings": True,
                "colour": "blue",
            },
        )
    )
    assert loaded.lock_settings is True
    assert loaded.base_url is None
    assert loaded.retention_days is None
    assert loaded.zdr is None
    named = " ".join(loaded.errors)
    for name in ("base_url", "retention_days", "zdr", "colour"):
        assert name in named


def test_retention_must_be_a_whole_number_of_days(tmp_path):
    assert policy.load(_write(tmp_path, {"retention_days": True})).retention_days is None
    assert policy.load(_write(tmp_path, {"retention_days": 4000})).retention_days is None
    assert policy.load(_write(tmp_path, {"retention_days": 7})).retention_days == 7


def test_unreadable_file_is_reported_not_ignored(tmp_path):
    loaded = policy.load(_write(tmp_path, "{not json"))
    assert loaded.present
    assert loaded.errors


def test_top_level_must_be_an_object(tmp_path):
    loaded = policy.load(_write(tmp_path, ["allow_export"]))
    assert loaded.present
    assert loaded.errors


def test_the_example_policy_in_the_docs_is_valid():
    from pathlib import Path

    example = Path(__file__).resolve().parents[2] / "docs" / "policy.example.json"
    loaded = policy.load(example)
    assert loaded.present
    assert loaded.errors == ()
    assert loaded.lock_settings is True
