"""On-device model downloads: verified, resumable, cancellable, and deletable.

Every test talks to a local server that serves the same paths as Hugging Face, so no
test reaches the network or a real model. The settings and models folders are scratch
folders, so the user's own files are never read or written.
"""

from __future__ import annotations

import hashlib
import http.server
import json
import threading

import pytest
from fastapi.testclient import TestClient

import config
import main
import model_store
import policy

CONTENT = {
    "model.bin": b"weights-" * 5000,
    "config.json": b'{"ok": true}',
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class _Hub(http.server.BaseHTTPRequestHandler):
    files: dict[str, bytes] = {}
    seen_ranges: list[str | None] = []
    support_ranges = True

    def log_message(self, *args):  # keep test output quiet
        pass

    def do_GET(self):
        _Hub.seen_ranges.append(self.headers.get("Range"))
        body = _Hub.files.get(self.path)
        if body is None:
            self.send_error(404)
            return
        start = 0
        requested = self.headers.get("Range")
        if requested and _Hub.support_ranges:
            start = int(requested.split("=", 1)[1].split("-", 1)[0])
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{len(body) - 1}/{len(body)}")
        else:
            self.send_response(200)
        self.send_header("Content-Length", str(len(body) - start))
        self.end_headers()
        self.wfile.write(body[start:])


@pytest.fixture
def hub(monkeypatch):
    _Hub.files = {
        "/fake/repo/resolve/r1/model.bin": CONTENT["model.bin"],
        "/fake/repo/resolve/r1/config.json": CONTENT["config.json"],
    }
    _Hub.seen_ranges = []
    _Hub.support_ranges = True
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Hub)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(model_store, "HUB", f"http://127.0.0.1:{server.server_address[1]}")
    yield _Hub
    server.shutdown()
    server.server_close()


@pytest.fixture
def fake_models(monkeypatch):
    files = (
        model_store.ModelFile("fake/model.bin", "fake/repo", "r1", "model.bin", len(CONTENT["model.bin"]), _sha(CONTENT["model.bin"])),
        model_store.ModelFile("fake/config.json", "fake/repo", "r1", "config.json", len(CONTENT["config.json"]), _sha(CONTENT["config.json"])),
    )
    spec = model_store.ModelSpec("fake", "Тестовая модель", True, files)
    monkeypatch.setattr(model_store, "MODELS", (spec,))
    return spec


def test_the_registry_pins_every_file_to_a_commit_and_a_hash():
    for spec in model_store.MODELS:
        assert spec.files, spec.id
        for file in spec.files:
            assert len(file.revision) == 40 and all(c in "0123456789abcdef" for c in file.revision)
            assert len(file.sha256) == 64 and all(c in "0123456789abcdef" for c in file.sha256)
            assert file.size > 0
    paths = [file.path for spec in model_store.MODELS for file in spec.files]
    assert len(paths) == len(set(paths))


def test_status_reports_nothing_installed_before_a_download(tmp_path, fake_models):
    item = model_store.status(tmp_path)[0]
    assert item["installed"] is False
    assert item["missing"] == fake_models.size
    assert item["partial_bytes"] == 0


def test_status_counts_an_interrupted_download_as_progress(tmp_path, fake_models):
    (tmp_path / "fake").mkdir(parents=True)
    (tmp_path / "fake" / "model.bin.part").write_bytes(b"x" * 1000)
    assert model_store.status(tmp_path)[0]["partial_bytes"] == 1000


def test_download_fetches_verifies_and_installs(tmp_path, fake_models, hub):
    events = list(model_store.download(["fake"], threading.Event(), base=tmp_path))
    assert (tmp_path / "fake" / "model.bin").read_bytes() == CONTENT["model.bin"]
    assert (tmp_path / "fake" / "config.json").read_bytes() == CONTENT["config.json"]
    assert events[-1]["done"] == events[-1]["total"] == fake_models.size
    assert model_store.status(tmp_path)[0]["installed"] is True
    assert not list(tmp_path.rglob("*.part"))


def test_a_file_that_fails_the_hash_is_not_installed(tmp_path, fake_models, hub):
    hub.files["/fake/repo/resolve/r1/model.bin"] = b"z" * len(CONTENT["model.bin"])
    with pytest.raises(model_store.ModelError, match="не прошёл проверку"):
        list(model_store.download(["fake"], threading.Event(), base=tmp_path))
    assert not (tmp_path / "fake" / "model.bin").exists()
    assert not (tmp_path / "fake" / "model.bin.part").exists()


def test_cancel_keeps_the_partial_file_so_the_next_try_resumes(tmp_path, fake_models, hub, monkeypatch):
    monkeypatch.setattr(model_store, "CHUNK", 8 * 1024)
    cancel = threading.Event()
    events = model_store.download(["fake"], cancel, base=tmp_path)
    next(events)
    cancel.set()
    with pytest.raises(model_store.Cancelled):
        list(events)
    part = tmp_path / "fake" / "model.bin.part"
    assert part.is_file()
    assert 0 < part.stat().st_size < len(CONTENT["model.bin"])


def test_resume_asks_only_for_the_rest(tmp_path, fake_models, hub):
    data = CONTENT["model.bin"]
    (tmp_path / "fake").mkdir(parents=True)
    (tmp_path / "fake" / "model.bin.part").write_bytes(data[:1000])
    list(model_store.download(["fake"], threading.Event(), base=tmp_path))
    assert (tmp_path / "fake" / "model.bin").read_bytes() == data
    assert "bytes=1000-" in hub.seen_ranges


def test_a_server_that_ignores_ranges_is_handled_by_starting_over(tmp_path, fake_models, hub):
    hub.support_ranges = False
    data = CONTENT["model.bin"]
    (tmp_path / "fake").mkdir(parents=True)
    (tmp_path / "fake" / "model.bin.part").write_bytes(data[:1000])
    list(model_store.download(["fake"], threading.Event(), base=tmp_path))
    assert (tmp_path / "fake" / "model.bin").read_bytes() == data


def test_delete_removes_the_files_and_reports_the_space(tmp_path, fake_models, hub):
    list(model_store.download(["fake"], threading.Event(), base=tmp_path))
    freed = model_store.delete("fake", base=tmp_path)
    assert freed == fake_models.size
    assert model_store.status(tmp_path)[0]["installed"] is False


@pytest.fixture
def api_client(tmp_path, monkeypatch, fake_models):
    monkeypatch.setattr(config, "MODELS_DIR", tmp_path)
    with TestClient(main.app) as client:
        yield client


def test_a_recording_analysed_before_the_speaker_models_arrived_is_analysed_again(tmp_path, monkeypatch):
    import analysis_cache

    seg, emb = tmp_path / "diarization" / "segmentation" / "model.onnx", tmp_path / "diarization" / "embedding.onnx"
    monkeypatch.setattr(config, "DIARIZATION_SEG_DIR", seg.parent)
    monkeypatch.setattr(config, "DIARIZATION_EMB_PATH", emb)
    audio = b"the same recording"
    before = analysis_cache.key_for(audio, ".wav")
    seg.parent.mkdir(parents=True)
    seg.write_bytes(b"segmentation")
    emb.write_bytes(b"embedding")
    assert analysis_cache.key_for(audio, ".wav") != before


def test_the_state_endpoint_says_whether_the_app_can_work(api_client):
    body = api_client.get("/api/local-models").json()
    assert body["ready"] is False
    assert body["allowed"] is True
    assert body["models"][0]["id"] == "fake"


def test_the_download_endpoint_streams_progress_and_finishes(api_client, hub):
    with api_client.stream("POST", "/api/local-models/download", json={"ids": ["fake"]}) as response:
        assert response.status_code == 200
        lines = [json.loads(line) for line in response.iter_lines() if line]
    assert any(line["stage"] == "progress" for line in lines)
    assert lines[-1]["stage"] == "done"
    assert api_client.get("/api/local-models").json()["ready"] is True


def test_a_second_download_is_refused_while_one_runs(api_client):
    assert model_store.lock.acquire(blocking=False)
    try:
        assert api_client.post("/api/local-models/download", json={"ids": ["fake"]}).status_code == 409
    finally:
        model_store.lock.release()


def test_cancel_when_nothing_runs_says_so(api_client):
    assert api_client.post("/api/local-models/cancel").json() == {"cancelled": False}


def test_a_policy_can_switch_downloads_off(api_client, monkeypatch):
    monkeypatch.setattr(config, "POLICY", policy.Policy(present=True, allow_model_download=False))
    assert api_client.post("/api/local-models/download", json={}).status_code == 403
    assert api_client.get("/api/local-models").json()["allowed"] is False


def test_deleting_an_unknown_model_is_a_clear_refusal(api_client):
    assert api_client.delete("/api/local-models/nope").status_code == 404
