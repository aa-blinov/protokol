"""The commercial rules as the API applies them: retention, cache purge, locked settings, licence gate.

Every test runs against a scratch settings folder through STTSHKA_ENV_FILE, so the
user's own history and key are never touched.
"""

import datetime as dt
import json
import stat

import pytest
from fastapi.testclient import TestClient

import analysis_cache
import ed25519
import licensing
import policy
import storage
import config
import main

TEST_SEED = bytes(range(32))
TEST_PUBLIC = ed25519.public_key(TEST_SEED)


@pytest.fixture
def scratch(tmp_path, monkeypatch):
    monkeypatch.setenv("STTSHKA_ENV_FILE", str(tmp_path / ".env"))
    monkeypatch.delenv("RETENTION_DAYS", raising=False)
    monkeypatch.setattr(config, "POLICY", policy.Policy())
    monkeypatch.setattr(licensing, "PUBLIC_KEY", TEST_PUBLIC)
    return tmp_path


@pytest.fixture
def client(scratch):
    return TestClient(main.app)


def _session(identifier, created, cache_key):
    return {
        "id": identifier,
        "name": f"{identifier}.wav",
        "createdAt": created,
        "analysis": {"cache_key": cache_key, "transcript": "x", "masked_text": "x", "entity_map": {}},
        "summaries": {},
    }


def _ago(days):
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).isoformat()


def test_history_file_is_written_owner_only(client, scratch):
    response = client.put("/api/sessions", json=[])
    assert response.status_code == 200
    assert stat.S_IMODE((scratch / "sessions.json").stat().st_mode) == 0o600


def test_removing_a_recording_removes_its_cache_entry(client, scratch):
    analysis_cache.put("keep-me", {"masked_text": "a"})
    analysis_cache.put("drop-me", {"masked_text": "b"})
    client.put("/api/sessions", json=[_session("one", _ago(0), "keep-me")])
    assert analysis_cache.get("keep-me") is not None
    assert analysis_cache.get("drop-me") is None


def test_retention_drops_old_recordings_from_the_list(client, scratch, monkeypatch):
    monkeypatch.setenv("RETENTION_DAYS", "30")
    client.put(
        "/api/sessions",
        json=[_session("fresh", _ago(2), "a"), _session("stale", _ago(40), "b")],
    )
    listed = client.get("/api/sessions").json()
    assert [item["id"] for item in listed] == ["fresh"]


def test_zero_retention_keeps_everything(client, scratch):
    client.put("/api/sessions", json=[_session("stale", _ago(4000), "b")])
    assert [item["id"] for item in client.get("/api/sessions").json()] == ["stale"]


def test_undated_entry_is_not_deleted_by_guesswork(client, scratch, monkeypatch):
    monkeypatch.setenv("RETENTION_DAYS", "30")
    undated = _session("undated", "", "c")
    client.put("/api/sessions", json=[undated])
    assert [item["id"] for item in client.get("/api/sessions").json()] == ["undated"]


def test_retention_is_saved_in_settings(client, scratch):
    response = client.post(
        "/api/settings",
        json={"key": "", "model": "m", "base_url": "", "verify": False, "retention_days": 45},
    )
    assert response.status_code == 200
    assert response.json()["settings"]["retention_days"] == 45
    assert "RETENTION_DAYS=45" in (scratch / ".env").read_text(encoding="utf-8")


def test_organisation_can_lock_every_setting(client, scratch, monkeypatch):
    monkeypatch.setattr(config, "POLICY", policy.Policy(present=True, lock_settings=True))
    response = client.post("/api/settings", json={"key": "", "model": "m", "verify": False})
    assert response.status_code == 403
    assert "организация" in response.json()["detail"]


def test_organisation_can_fix_the_service_address(client, scratch, monkeypatch):
    monkeypatch.setattr(config, "POLICY", policy.Policy(present=True, base_url="https://llm.example.ru/v1"))
    refused = client.post(
        "/api/settings",
        json={"key": "", "model": "m", "base_url": "https://other.example/v1", "verify": False},
    )
    assert refused.status_code == 403
    allowed = client.post(
        "/api/settings",
        json={"key": "", "model": "m", "base_url": "https://llm.example.ru/v1/", "verify": False},
    )
    assert allowed.status_code == 200


def test_organisation_retention_cannot_be_changed_in_the_app(client, scratch, monkeypatch):
    monkeypatch.setattr(config, "POLICY", policy.Policy(present=True, retention_days=30))
    response = client.post("/api/settings", json={"key": "", "model": "m", "verify": False, "retention_days": 5})
    assert response.status_code == 403


def test_health_reports_licence_policy_disk_and_retention(client, scratch):
    body = client.get("/api/health").json()
    assert body["license"]["state"] == "trial"
    assert body["policy"] == {"managed": False, "errors": []}
    assert "filevault" in body
    assert body["retention_days"] == 0


def test_expired_trial_stops_transcription(client, scratch):
    started = (dt.date.today() - dt.timedelta(days=30)).isoformat()
    storage.write_private(scratch / "trial.json", json.dumps({"started": started}))
    response = client.post("/api/transcribe", files={"file": ("a.wav", b"RIFF")})
    assert response.status_code == 402
    assert "пробный период" in response.json()["detail"].lower()


def test_installing_a_valid_licence_restores_access(client, scratch):
    payload = {"customer": "ООО Ромашка", "edition": "team", "seats": 25, "issued": "2026-10-15", "expires": None}
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    document = {"payload": text, "signature": ed25519.sign(TEST_SEED, text.encode("utf-8")).hex()}
    response = client.post("/api/license", json={"text": json.dumps(document)})
    assert response.status_code == 200
    assert response.json()["state"] == "licensed"
    assert client.get("/api/license").json()["customer"] == "ООО Ромашка"


def test_a_forged_licence_is_refused(client, scratch):
    document = {"payload": json.dumps({"customer": "x", "edition": "team", "seats": 99, "issued": "2026-10-15"}), "signature": "00" * 64}
    response = client.post("/api/license", json={"text": json.dumps(document)})
    assert response.status_code == 400
