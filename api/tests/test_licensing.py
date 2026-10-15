"""Trial, signed licence files, expiry, and what stops when the trial is over."""

import datetime as dt
import json
import stat

import pytest

import ed25519
import licensing
from licensing import LicenceError

TEST_SEED = bytes(range(32))
TEST_PUBLIC = ed25519.public_key(TEST_SEED)
TODAY = dt.date(2026, 10, 15)
DAY = dt.timedelta(days=1)


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A clean settings folder, and a test key in place of the vendor's."""
    monkeypatch.setenv("STTSHKA_ENV_FILE", str(tmp_path / ".env"))
    monkeypatch.setattr(licensing, "PUBLIC_KEY", TEST_PUBLIC)
    return tmp_path


def issue(payload, seed=TEST_SEED):
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    signature = ed25519.sign(seed, text.encode("utf-8")).hex()
    return json.dumps({"payload": text, "signature": signature}, ensure_ascii=False)


def team(expires="2027-10-14"):
    return {"customer": "ООО Ромашка", "edition": "team", "seats": 25, "issued": "2026-10-15", "expires": expires}


def test_trial_lasts_fourteen_days(home):
    first = licensing.status(TODAY)
    assert first["state"] == "trial" and first["days_left"] == 14
    assert licensing.status(TODAY + 13 * DAY)["days_left"] == 1
    assert licensing.status(TODAY + 14 * DAY)["state"] == "expired"


def test_trial_marker_is_private_and_written_once(home):
    licensing.status(TODAY)
    marker = home / "trial.json"
    assert stat.S_IMODE(marker.stat().st_mode) == 0o600
    before = marker.read_text(encoding="utf-8")
    licensing.status(TODAY + 3 * DAY)
    assert marker.read_text(encoding="utf-8") == before


def test_require_active_stops_work_after_the_trial(home):
    licensing.status(TODAY)
    licensing.require_active(TODAY)
    with pytest.raises(LicenceError):
        licensing.require_active(TODAY + 14 * DAY)


def test_valid_licence_activates_and_is_stored_privately(home):
    result = licensing.activate(issue(team()), TODAY)
    assert result["state"] == "licensed"
    assert result["customer"] == "ООО Ромашка" and result["seats"] == 25
    stored = home / "license.json"
    assert stat.S_IMODE(stored.stat().st_mode) == 0o600
    assert licensing.status(TODAY + 30 * DAY)["state"] == "licensed"


def test_licence_stops_working_after_its_expiry(home):
    licensing.activate(issue(team("2026-12-31")), TODAY)
    assert licensing.status(dt.date(2026, 12, 31))["state"] == "licensed"
    later = licensing.status(dt.date(2027, 1, 1))
    assert later["state"] == "expired"
    assert later["problem"]


def test_perpetual_licence_has_no_expiry(home):
    licensing.activate(issue(team(None)), TODAY)
    state = licensing.status(TODAY + 5000 * DAY)
    assert state["state"] == "licensed" and state["days_left"] is None


def test_changed_payload_is_rejected_and_not_stored(home):
    document = json.loads(issue(team()))
    document["payload"] = document["payload"].replace('"seats": 25', '"seats": 250')
    with pytest.raises(LicenceError, match="Подпись"):
        licensing.activate(json.dumps(document), TODAY)
    assert not (home / "license.json").exists()


def test_licence_from_another_key_is_rejected(home):
    with pytest.raises(LicenceError, match="Подпись"):
        licensing.activate(issue(team(), seed=bytes(range(1, 33))), TODAY)


def test_already_expired_licence_is_refused_at_activation(home):
    with pytest.raises(LicenceError):
        licensing.activate(issue(team("2026-01-01")), TODAY)


@pytest.mark.parametrize("text", ["hello", '{"payload": 1, "signature": "zz"}', '{"payload": "{}", "signature": "00"}'])
def test_non_licences_are_refused(home, text):
    with pytest.raises(LicenceError):
        licensing.activate(text, TODAY)


def test_a_damaged_installed_licence_falls_back_to_the_trial(home):
    licensing.activate(issue(team()), TODAY)
    (home / "license.json").write_text("{}", encoding="utf-8")
    state = licensing.status(TODAY)
    assert state["state"] == "trial"
    assert state["problem"]
