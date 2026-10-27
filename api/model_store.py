"""The model files the app fetches on first use, and how a fetch is made safe.

Nothing here runs on import. The files come from public Hugging Face repositories,
each pinned to the commit its SHA-256 was checked against, so a model that changes
upstream cannot slip into the app unnoticed. A file takes its final name only after
the hash matches; a download that fails or is cancelled leaves a ``.part`` file, and
the next attempt resumes from it instead of starting over.
"""

from __future__ import annotations

import hashlib
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import httpx

import config

# Tests and offline checks point this at a local server that serves the same paths.
HUB = os.getenv("MODEL_HUB_URL", "https://huggingface.co").rstrip("/")
CHUNK = 1 << 20
TIMEOUT = httpx.Timeout(30.0, read=60.0)

# Only one fetch or delete at a time: two writers on the same .part file corrupt it.
lock = threading.Lock()


class ModelError(Exception):
    """A sentence the person can read in the app."""


class Cancelled(ModelError):
    """The person asked to stop. Whatever was fetched stays as a .part file."""


@dataclass(frozen=True)
class ModelFile:
    path: str  # where the app loads it from, relative to the models folder
    repo: str  # Hugging Face repository
    revision: str  # commit the hash was checked against
    source: str  # file name inside that repository
    size: int
    sha256: str


@dataclass(frozen=True)
class ModelSpec:
    id: str
    title: str
    required: bool
    files: tuple[ModelFile, ...]

    @property
    def size(self) -> int:
        return sum(file.size for file in self.files)


GIGAAM = ("istupakov/gigaam-v3-onnx", "322c3b29492673eb7d0b434bfa9dfb8653e34d02")
PII = ("lockR/rubert-base-pii-ner-onnx", "ea7610b22808c509c0c8b7c7b0f6639c19684d08")
SEGMENTATION = ("onnx-community/pyannote-segmentation-3.0", "733a93b6473d019a773298e08cefa686894b1854")
EMBEDDING = ("Luigi/campplus-zh-en-onnx", "aa79cf9b8628a46ca362bf9bf7cde226a470a282")

# Sizes and hashes were read from the repositories' metadata and matched against the
# files the app shipped with, byte for byte. The text files carry no LFS hash, so their
# hash is the one of the copy that matched in size.
MODELS: tuple[ModelSpec, ...] = (
    ModelSpec(
        id="stt",
        title="Распознавание речи (GigaAM v3)",
        required=True,
        files=(
            ModelFile("gigaam/v3_e2e_rnnt_encoder.int8.onnx", *GIGAAM, "v3_e2e_rnnt_encoder.int8.onnx", 224570477, "4e0e076a6076cd110277e529b8ac8f32cd5297f7fbebad5341ae8ddb7d00817b"),
            ModelFile("gigaam/v3_e2e_rnnt_decoder.int8.onnx", *GIGAAM, "v3_e2e_rnnt_decoder.int8.onnx", 1159170, "89014e134865615b91e037157e46e389b1271e6072460efc010ea08e61e23146"),
            ModelFile("gigaam/v3_e2e_rnnt_joint.int8.onnx", *GIGAAM, "v3_e2e_rnnt_joint.int8.onnx", 687791, "ade116563dbf66e503b0994efab6b5861412743e52bf31c39fc3fffa3783d5d1"),
            ModelFile("gigaam/v3_e2e_rnnt_vocab.txt", *GIGAAM, "v3_e2e_rnnt_vocab.txt", 13354, "39abae20e692998290c574e606f11a9edef2902a1995463fcff63d1490cf22b7"),
            ModelFile("gigaam/config.json", *GIGAAM, "config.json", 135, "0641fcf73f4af791c73f05083e38a658ff5dcbee3534a0c61396c10f4b97f0fe"),
        ),
    ),
    ModelSpec(
        id="pii",
        title="Поиск персональных данных (ruBERT)",
        required=True,
        files=(
            ModelFile("rubert-pii/model.optimized.fp16.onnx", *PII, "model.optimized.fp16.onnx", 355541615, "039aba6be0c64f50f37c64ddc6c6d4e2fd91cbdcf5c9291056ec6bc96c70a501"),
            ModelFile("rubert-pii/config.json", *PII, "config.json", 2831, "f4eeba88d1503a56d629195c9307d42c1acf4ce53ab88fdaecfc754fd0745cf9"),
            ModelFile("rubert-pii/tokenizer.json", *PII, "tokenizer.json", 3714701, "f61eee9d0dc18f14c195321a37eadf9e5aeb3a323bc278dec689adeb89dec1b9"),
            ModelFile("rubert-pii/tokenizer_config.json", *PII, "tokenizer_config.json", 322, "ffe381e31042ba94cb077bf7d5b9cee944dbd0c2a85079b095bea7e5a5a6058b"),
        ),
    ),
    ModelSpec(
        id="diarization",
        title="Разделение по говорящим",
        required=False,
        files=(
            ModelFile("diarization/segmentation/model.onnx", *SEGMENTATION, "onnx/model.onnx", 5986908, "057ee564753071c0b09b5b611648b50ac188d50846bff5f01e9f7bbf1591ea25"),
            ModelFile("diarization/segmentation/config.json", *SEGMENTATION, "config.json", 408, "5a4c6bb4f49f1b47c9bd398aac78b8cd4a9f30a0ff91b5c2dc68d05e13e160cf"),
            ModelFile("diarization/embedding.onnx", *EMBEDDING, "campplus_zh_en_fp32.onnx", 28281164, "aa3cfc16963a10586a9393f5035d6d6b57e98d358b347f80c2a30bf4f00ceba2"),
        ),
    ),
)


def root() -> Path:
    return Path(config.MODELS_DIR)


def required_ids() -> list[str]:
    return [spec.id for spec in MODELS if spec.required]


def _complete(base: Path, file: ModelFile) -> bool:
    # Size only, not the hash: hashing 600 MB on every status check would make the
    # first screen wait. The hash is checked once, when the file is fetched.
    target = base / file.path
    return target.is_file() and target.stat().st_size == file.size


def status(base: Path | None = None) -> list[dict]:
    base = base or root()
    items = []
    for spec in MODELS:
        present = [file for file in spec.files if _complete(base, file)]
        # Bytes of an interrupted download count as done for the person deciding what to
        # fetch next: a resume only transfers the rest, so the figure must say so.
        partial_bytes = sum(
            (base / f"{file.path}.part").stat().st_size
            for file in spec.files
            if not _complete(base, file) and (base / f"{file.path}.part").is_file()
        )
        items.append(
            {
                "id": spec.id,
                "title": spec.title,
                "required": spec.required,
                "installed": len(present) == len(spec.files),
                "size": spec.size,
                "missing": spec.size - sum(file.size for file in present),
                "partial_bytes": partial_bytes,
            }
        )
    return items


def download(ids: list[str], cancel: threading.Event, base: Path | None = None) -> Iterator[dict]:
    """Fetch the missing files of the chosen models, yielding progress as it goes."""
    base = base or root()
    chosen = [spec for spec in MODELS if spec.id in ids]
    pending = [(spec, file) for spec in chosen for file in spec.files if not _complete(base, file)]
    total = sum(file.size for _, file in pending)
    done = 0
    for spec, file in pending:
        if cancel.is_set():
            raise Cancelled("Загрузка остановлена.")
        before = done
        for offset in _fetch(file, base, cancel):
            yield {
                "model": spec.id,
                "file": file.path,
                "file_done": offset,
                "file_size": file.size,
                "done": before + offset,
                "total": total,
            }
        done = before + file.size


def _fetch(file: ModelFile, base: Path, cancel: threading.Event) -> Iterator[int]:
    target = base / file.path
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + ".part")
    offset = part.stat().st_size if part.is_file() else 0
    if offset > file.size:
        part.unlink()
        offset = 0

    # The bytes already on disk count toward the hash, so a resumed file is checked
    # the same way as one fetched in a single go.
    digest = hashlib.sha256()
    if offset:
        with part.open("rb") as existing:
            for block in iter(lambda: existing.read(CHUNK), b""):
                digest.update(block)

    url = f"{HUB}/{file.repo}/resolve/{file.revision}/{file.source}"
    headers = {"Range": f"bytes={offset}-"} if offset else {}
    try:
        with httpx.stream("GET", url, headers=headers, follow_redirects=True, timeout=TIMEOUT) as response:
            if offset and response.status_code == 200:
                # The server ignored the Range header and sent the whole file. Start over.
                offset = 0
                digest = hashlib.sha256()
                part.unlink(missing_ok=True)
            elif response.status_code not in (200, 206):
                raise ModelError(f"Сервер моделей ответил {response.status_code}. Попробуйте позже.")
            with part.open("ab" if offset else "wb") as out:
                for block in response.iter_bytes(CHUNK):
                    if cancel.is_set():
                        raise Cancelled("Загрузка остановлена.")
                    out.write(block)
                    digest.update(block)
                    offset += len(block)
                    yield offset
    except httpx.HTTPError as error:
        raise ModelError("Нет связи с Hugging Face. Проверьте подключение и попробуйте снова.") from error

    if offset != file.size or digest.hexdigest() != file.sha256:
        part.unlink(missing_ok=True)
        raise ModelError(f"Файл {file.path} не прошёл проверку. Загрузка начнётся заново.")
    os.replace(part, target)


def delete(model_id: str, base: Path | None = None) -> int:
    """Remove a model's files and partial downloads. Returns the bytes freed."""
    base = base or root()
    spec = next((spec for spec in MODELS if spec.id == model_id), None)
    if spec is None:
        raise ModelError(f"Неизвестная модель: {model_id}")
    freed = 0
    for file in spec.files:
        for candidate in (base / file.path, base / f"{file.path}.part"):
            if candidate.is_file():
                freed += candidate.stat().st_size
                candidate.unlink()
    return freed

