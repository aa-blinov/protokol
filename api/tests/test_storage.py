"""Owner-only files and the FileVault answer."""

import os
import stat

import storage


def test_write_private_sets_owner_only_mode(tmp_path):
    target = tmp_path / "sessions.json"
    storage.write_private(target, "[]")
    assert target.read_text(encoding="utf-8") == "[]"
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_write_private_fixes_a_leftover_temporary_file(tmp_path):
    target = tmp_path / "x.json"
    leftover = tmp_path / "x.json.tmp"
    leftover.write_text("old", encoding="utf-8")
    os.chmod(leftover, 0o644)
    storage.write_private(target, "new")
    assert target.read_text(encoding="utf-8") == "new"
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_parse_filevault_answers():
    assert storage.parse_filevault("FileVault is On.\n") is True
    assert storage.parse_filevault("FileVault is Off.") is False
    assert storage.parse_filevault("") is None
    assert storage.parse_filevault("Error: unknown") is None
