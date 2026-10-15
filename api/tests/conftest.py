"""Shared test set-up: every test gets its own settings folder.

The settings folder holds the key, the history, the licence and the trial marker.
Without this, a test that reaches the health check would write those files next to
the repository's .env, and a test run could touch the user's own data.
"""

import pytest


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("STTSHKA_ENV_FILE", str(tmp_path / ".env"))
    yield tmp_path
