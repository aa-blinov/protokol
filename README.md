# Protokol

Transcribe a meeting recording on your own machine, mask the personal data in the transcript, and send only the tokenized text to a language model. The reply comes back with the names restored locally, and the original recording never leaves the computer.

![The finished result: a transcript with highlighted entities, the masked text and the model reply](docs/screenshots/app-results.png)

[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

Product documentation: [docs/PRODUCT.md](docs/PRODUCT.md). For administrators: [docs/ADMIN.md](docs/ADMIN.md). Issuing licences: [docs/LICENSING.md](docs/LICENSING.md).

---

## Quick start

The desktop app carries the models inside the bundle, so nothing is downloaded at run time.

```bash
./download_models.sh      # the ONNX models, about 0.7 GB, once
./desktop/build.sh        # the target follows the platform: mac or linux
./desktop/verify.sh       # the bundle, the models and a real inference
```

| Platform | Command | Artefact |
| --- | --- | --- |
| macOS 13 or newer, Apple Silicon | `./desktop/build.sh --mac` | `.dmg` and `.zip`, arm64 |
| Linux | `./desktop/build.sh --linux` | `AppImage` and `.deb` |

Nothing is cross-compiled. A macOS bundle is built on a Mac and the Linux targets on Linux, because PyInstaller and `onnxruntime` produce a binary only for the machine that builds them.

Docker, for development on any machine:

```bash
./download_models.sh
docker compose up --build
```

The interface is on http://localhost:3000 and the API on http://localhost:8000/docs.

The app runs without a licence for 14 days from the first launch. After that it needs a signed licence file, installed in Settings.

## What it does

- **Transcribe on the CPU, locally.** The audio is decoded in process and recognised by GigaAM v3 (ONNX, int8). There is no limit on the length of a recording: a 75-minute file, 137 MB, was recognised in 1 minute 25 seconds.
- **Mask personal data before anything is sent.** Names, phones, passports, tax and insurance numbers, cards, addresses and access tokens become tokens such as `[PERSON_1]` and `[PHONE_1]`.
- **Split a recording by speaker.** Turns carry a speaker label and a timecode. The labels are relative: the app never tells you who spoke.
- **Read what the model will get, and what it costs.** The whole masked text and a cost estimate are on screen before the request, and a transcript with no summary is a legitimate outcome.
- **Summarise in three modes, or with your own requirements.** Decisions and tasks, a short retelling, agreements between the parties. The requirements field is added to the mode, and personal data named there is masked as well.
- **Run the summary again without listening again.** A second mode costs one model call and no transcription: 0.025 s against 1.29 s on the same file.
- **Keep a history on this machine.** Up to 50 recordings in a file next to the settings, with search by name, rename and delete.
- **Export the result.** Copy the transcript or the reply, download a `.txt`, or print to PDF.
- **Search inside a transcript.** Matches are highlighted and Enter steps through them.
- **Light and dark themes.**

## Screenshots

| The empty state | The result |
| :---: | :---: |
| ![The empty state explains what happens to the data](docs/screenshots/app-empty.png) | ![A document with a summary and collapsible sections](docs/screenshots/app-results.png) |

| A meeting with several speakers | Search inside the transcript |
| :---: | :---: |
| ![Turns with speaker labels and timecodes](docs/screenshots/app-diarization.png) | ![Matches highlighted in the transcript](docs/screenshots/app-search.png) |

| The settings panel | The history |
| :---: | :---: |
| ![The provider and the state of the key](docs/screenshots/app-settings.png) | ![Renaming a session in the history](docs/screenshots/app-history.png) |

![The same document in the dark theme](docs/screenshots/app-dark-results.png)

![The empty state on a 375 px screen](docs/screenshots/app-empty-mobile.png)

The screenshots are taken from the current build by `npm --prefix web run shots`. The meeting in them is invented: the names, the phone number, the passport and the address are made up.

## How it works

```
recording -> decode -> transcript -> speakers -> mask -> provider -> restore
             local     local, CPU    local      local    one call    local
```

The desktop app is one process tree. An Electron window loads a page from a Python sidecar that listens on `127.0.0.1`; the sidecar serves the built web interface and the API from the same origin, so there is no proxy and no CORS. Under Docker the same sidecar sits behind nginx, with the interface in a container of its own.

The recording is decoded to 16 kHz mono by PyAV, whose wheel carries the FFmpeg libraries, so the app needs no `ffmpeg` on the machine. GigaAM v3 recognises the speech in chunks of at most 20 seconds, each cut at the quietest frame near the limit so a cut rarely lands inside a word. Speaker turns come from pyannote segmentation plus a CAM++ voice embedding, grouped by cosine clustering. Both diarization models are optional: without them the app still transcribes, it just cannot name the turns.

Masking has two layers. A ruBERT PII model finds the entities that depend on meaning, in windows of 512 tokens that overlap by 128, with a confidence threshold of 0.3. A rule layer covers the identifiers whose format can be checked mechanically: the tax id, the social insurance number, a card number by the Luhn algorithm, the passport, the phone, the insurance policy number, one-time codes and access tokens. The rule layer only fills the gaps the model left, because a rule that argues with the model costs accuracy on the cases the model already gets right.

A person is one token whatever the case. "Ольга Николаевна", "Ольги Николаевны Смирновой" and "Ольге Николаевне" all become `[PERSON_1]`, and the reply is restored with the case the model asks for, using the Russian morphology dictionaries.

Only masked text reaches the provider. The model returns a protocol in which the tokens are still there, the tokens are replaced by the original values on the machine, and the restored text is never sent anywhere.

The pipeline is split in two on purpose. Transcription takes about 30 s for a 20-minute recording and costs nothing, because nothing leaves the machine. The summary is one call to the provider and it costs money. `/api/analyse` produces the transcript, the speakers and the masked text; `/api/summarize` produces the summary over an already analysed recording, so a second mode costs one call and no transcription. The analysed transcript is cached under a digest of the audio bytes, the file format, the model directory and a pipeline version, and the cache holds the eight most recent recordings.

## Configuration

Everything the app needs at run time lives in one file next to the settings, `.env` by default, or the file the desktop shell points at with `STTSHKA_ENV_FILE`. The settings panel in the interface writes the same file, so a key typed there works on the next request without a restart.

| Variable | Default | What it does |
| --- | --- | --- |
| `OPENROUTER_API_KEY` | none | The provider key. A value already in the environment wins over the file. |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | The provider address. Any service with an OpenAI-compatible API works. |
| `LLM_MODEL` | `deepseek/deepseek-v4.1-flash` | The model that writes the summary. |
| `LLM_PRESET` | `decisions` | The default summary mode. |
| `LLM_EXTRA` | none | Extra requirements for the summary. |
| `LLM_PROVIDER_KEYS` | none | The keys of several providers, as one JSON object keyed by address. |
| `LLM_DATA_COLLECTION` | `deny` | What the provider may do with the prompt. `deny` keeps requests away from providers that store prompts or train on them. |
| `LLM_ZDR` | `0` | `1` allows only endpoints with a zero data retention policy. Some models have none, and the request then fails. |
| `LLM_REASONING_EFFORT` | none | How hard the model reasons: `low`, `medium` or `high`. |
| `INFERENCE_THREADS` | `4` | The ONNX Runtime threads. |
| `USE_COREML` | `0` | The CoreML execution provider on Apple Silicon. Off, because it measured slower on these models. |
| `MODELS_DIR` | `models/` beside `api/` | Where the ONNX models are. |
| `WEB_DIST_DIR` | `web/dist` | The built interface the sidecar serves. |
| `RETENTION_DAYS` | `0` | How many days of history to keep. `0` keeps everything. |
| `PROTOKOL_POLICY_FILE` | `/Library/Application Support/Protokol/policy.json` | The organisation's policy file. |
| `HOST`, `PORT` | `127.0.0.1`, `8000` | The address the sidecar listens on. |

An administrator can fix the rules of the machine with one JSON file, read at start and applied after a restart. A key that is left out is not enforced, and a bad value is reported in the interface and skipped rather than stopping the app.

| Key | What it does |
| --- | --- |
| `base_url` | Fixes the provider address; the interface cannot change it. |
| `lock_settings` | Locks every setting in the interface. |
| `retention_days` | Deletes recordings older than that, with their transcripts. |
| `allow_export` | `false` hides the `.txt` export, the print and the copy buttons. |
| `zdr` | `true` allows only providers with a zero data retention policy. |
| `data_collection` | `deny` or `allow`, the same switch as `LLM_DATA_COLLECTION`. |

The example file is [docs/policy.example.json](docs/policy.example.json), and the guide for administrators is [docs/ADMIN.md](docs/ADMIN.md). The interface language is Russian.

## Development

```bash
./download_models.sh                       # the ONNX models, about 0.7 GB, once
cd api && python3.12 -m venv .venv         # not bare python3: on macOS that is Xcode's 3.9 or 3.10
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install pytest               # for the tests; requirements.txt does not carry it
.venv/bin/python -m pytest tests -q        # 361 tests
cd ../web && npm install && npm run dev    # the interface on :3000, /api is proxied
cd ../web && npm run build                 # the interface the desktop app ships
cd ../desktop && STTSHKA_PYTHON=python3 npx electron .
```

Python 3.11 or newer, Node 18 or newer. The browser checks need Google Chrome and a recording:

```bash
cd web && E2E_AUDIO=/path/to/call.wav npm run e2e
cd web && npm run shots                   # the screenshots in docs/screenshots/
```

The external PII-Bench set is not in the repository. Fetch the two parquet files from the `data` folder of `hivetrace/pii-bench` into one directory, install `pyarrow`, and run:

```bash
api/.venv/bin/python benchmarks/run_pii_bench_ru.py <folder with the parquet files>
```

| Path | What it holds |
| --- | --- |
| `api/main.py` | The FastAPI app and every route. |
| `api/stt.py` | Audio decoding and speech recognition. |
| `api/diarization.py` | Speaker turns: segmentation, embeddings, clustering. |
| `api/ner.py` | The PII model and the windowing it runs in. |
| `api/rules.py` | The deterministic recognizers for identifiers. |
| `api/masking.py` | The tokens, the reverse map and the requirement binding. |
| `api/names.py` | Russian person names: one person, one token. |
| `api/llm.py` | The provider client, the prompts and the cost estimate. |
| `api/settings.py` | The key, the model and the address. |
| `api/policy.py` | The organisation's policy file. |
| `api/licensing.py`, `api/ed25519.py` | The trial and the licence signature. |
| `api/analysis_cache.py` | The eight cached analyses. |
| `api/storage.py` | The files written 0600, and the FileVault check. |
| `desktop/main.js` | The shell: a free port, the sidecar, the window. |
| `desktop/build.sh`, `desktop/verify.sh` | The bundle for this platform, and its check. |
| `web/src/` | The React interface. |
| `web/e2e/` | The browser checks and the screenshot script. |
| `benchmarks/` | The measurement scripts and the corpus builders. |
| `tools/license_tool.py` | The vendor-side tool that issues licences. |
| `docs/` | The product, administrator and licence documents. |

## License

MIT, © Alexander Blinov. See [LICENSE](LICENSE).

The third-party parts of the bundle carry their own terms, listed in [desktop/THIRD_PARTY_NOTICES.txt](desktop/THIRD_PARTY_NOTICES.txt): GigaAM (MIT), ruBERT-base-pii-ner and CAM++ (Apache-2.0), the pymorphy3 dictionaries (MIT code, CC BY-SA data) and Electron (MIT). That file also lists what the bundle does not settle: the FFmpeg libraries PyAV carries are GPL, and the access terms of the pyannote segmentation model have not been checked.
