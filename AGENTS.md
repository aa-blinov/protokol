# AGENTS.md — agent context for `protokol`

Protokol transcribes meeting recordings on the owner's machine, masks the personal data in the transcript, and sends only the masked text to a language model. The desktop app is an Electron window over a Python sidecar that runs three ONNX models on the CPU.

This file is what you need to work on the project without reading all of it.

## Run / build / test

```bash
./download_models.sh                    # the ONNX models, about 0.7 GB, once
cd api && python3.12 -m venv .venv      # not bare python3: on macOS that is Xcode's 3.9 or 3.10
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install pytest            # the tests; requirements.txt does not carry it
.venv/bin/python -m pytest tests -q     # 361 tests, no network and no model files
cd ../web && npm install && npm run dev # the interface on :3000, /api is proxied
cd ../web && npm run build              # the interface the desktop app ships
cd ../desktop && STTSHKA_PYTHON=python3 npx electron .
./desktop/build.sh                      # the bundle for this platform
./desktop/verify.sh                     # the bundle, the models, a real inference
cd ../web && E2E_AUDIO=/path/call.wav npm run e2e
```

Python 3.11 or newer, Node 18 or newer. Always work inside a venv: pip refuses to write into the system interpreter, and on macOS `python3` is the Xcode build of 3.9 or 3.10, so use `python3.12` from Homebrew. `desktop/build.sh` picks the interpreter itself and refuses a venv built on an older one.

## Where things live

| Path | What it holds |
| --- | --- |
| `api/main.py` | The FastAPI app and every route. Mounts the built interface at the root, last, so the API routes win. |
| `api/stt.py` | Audio decoding and speech recognition. Knows about the model, nothing about masking. |
| `api/diarization.py` | Speaker turns: segmentation, embeddings, clustering. |
| `api/ner.py` | The PII model and the windowing it runs in. |
| `api/rules.py` | The deterministic recognizers for identifiers. |
| `api/masking.py` | The tokens, the reverse map and the binding of the user's requirement. |
| `api/names.py` | Russian person names: one person, one token, whatever the case. |
| `api/llm.py` | The provider client, the prompts and the cost estimate. |
| `api/settings.py` | The key, the model and the address, and the settings file itself. |
| `api/policy.py` | The organisation's policy file, read once at start. |
| `api/licensing.py`, `api/ed25519.py` | The trial, the licence file and its signature. |
| `api/analysis_cache.py` | The eight cached analyses and the digest that keys them. |
| `api/model_store.py` | The on-device models: pinned Hugging Face sources, the verified and resumable download, and delete. |
| `api/storage.py` | The files written 0600, and the FileVault check. |
| `api/tests/` | 361 tests in 21 files. Each test gets its own settings folder. |
| `desktop/main.js` | The shell: a free port, the sidecar, the window. |
| `desktop/build.sh`, `desktop/verify.sh` | The bundle for this platform, and the check that runs on it. |
| `web/src/` | The React interface. |
| `web/e2e/` | The browser checks against a stub provider, and the screenshot script. |
| `benchmarks/` | The measurement scripts and the corpus builders. The corpora are downloaded, not committed. |
| `tools/license_tool.py` | The vendor-side tool that issues licence files. The signing key never goes in the repository. |
| `docs/` | The product, administrator and licence documents. |

## Traps

- **The `e2e` head of GigaAM is a privacy requirement.** `api/stt.py` loads `gigaam-v3-e2e-rnnt`. The plain head writes dictated digits as words, the PII model does not read "восемь девятьсот..." as a phone number, and the number reaches the provider unmasked. Do not switch the head for a quality reason.
- **Bump `analysis_cache.PIPELINE_VERSION` when the transcript changes.** The cache digest covers the audio bytes, the file suffix, the model directory, whether the speaker models are installed, and that version, and nothing else. A change in recognition or diarization that does not bump it returns the old transcript for the same audio.
- **The rule layer may only fill gaps.** `rules.fill_gaps` keeps the parts of a rule span the model did not cover. The layer used to run over the model, and on the redmadrobot benchmark it cost the card 6.2 F1 and the phone 2.2, because a rule span and a model span over the same number counted as a hit and a miss at once.
- **The NER windows are computed by hand.** `ner.window_starts` builds the sliding windows from the full token list. The tokenizer's own `return_overflowing_tokens` returned a short tail on transformers 5.19, and everything past about 1976 characters was never classified, so personal data reached the model in the clear.
- **A Russian case ending belongs inside the person span.** `masking._extend_over_ending` extends the span over the ending. Left alone, the token appears glued to it, as `[PERSON_6]у`, and the model copies the broken shape into the reply.
- **A word joins the turn it starts in.** `dialogue.assign_words_to_turns` assigns by the start of the word, not by its midpoint: the diarization boundaries and the ASR word times come from different models and jitter by tens of milliseconds.
- **The audio is cut at 20 seconds.** `stt.SEGMENT_MAX_SECONDS` is 20.0, and the cut lands on the quietest frame in the last 40% of the window. On a real interview, 120-second chunks recognised 904 words where 20-second chunks recognised 1051. Longer chunks lose speech without an error.
- **CoreML is off by default.** `config.USE_COREML` is `0`. On the three models of this project CoreML was 11% slower than the CPU provider, with 13% more CPU time and 33% more memory.
- **The segmentation windows need their speaker order matched before they are averaged.** onnx_asr's pyannote decoder defines a `reorder` and never calls it, so each 5-second seam mixed two speakers. `diarization._stitch` matches the order over the shared frames. On the AMI meetings this was the cause of the extra speakers: the count went from 6 of 8 right to 8 of 8.
- **The diarizer holds a lock for the whole call.** Two diarizations in parallel cost 2.09 times one, not twice. Split the embedding step from the clustering before anyone asks for parallel requests.
- **Empty means "keep" in the settings file, except for the extra requirements.** `settings.write_pair` keeps the stored value when an argument is empty, because the dialog sends an empty key when only the model changed. `LLM_EXTRA` is the one field where empty means "erase".
- **The port changes on every launch.** `desktop/main.js` takes a free port, and Chromium scopes localStorage to the origin including the port. That is why the history lives in `sessions.json` beside the settings file and not in the browser.
- **`ditto` into an existing bundle appends.** Installing over an old copy leaves files of the previous build inside, and the signature stops passing `codesign --verify`. Remove the old application first.
- **PyInstaller onedir, not onefile.** A one-file bundle unpacks about 200 MB of native libraries into a temporary directory on every launch.
- **Do not rename `await fetch(` to `await request(` in `web/src/api.ts`.** A bulk rename once made the wrapper call itself, every request failed, the errors were swallowed and the history came out empty.
- **The models are 696 MiB on disk.** gigaam 214 MB, rubert-pii 448 MB, diarization 33 MB. The figure of about 0.9 GB in `download_models.sh`, in the API Dockerfile and in `desktop/build.sh` is out of date.

## Style / safety rails

- **Personal data must not reach the provider, and must not leave the machine.** Mask first, send the masked text, restore the reply locally. Anything that would put a raw value on the wire is a defect, whatever it gains.
- **The safety prefix in `api/llm.py` is not editable.** The user's requirement is appended to it and never replaces it. The recording is framed as data inside `<transcript>` tags, so that a request inside the transcript is read as content.
- **A requirement that names personal data the recording does not hold is refused**, with the offending values named in the error. Two candidates for one name is a refusal, not a guess.
- **One outbound request, and it carries masked text only.** Transcription and masking work with the network off. The provider is asked not to keep the prompt, and the request says so on every call.
- **The interface is in Russian.** Copy, pluralisation and the speaker labels stay Russian. The documents in the repository are in English.
- **Comments explain why, never what.** The comments here carry the reasoning and the measurements, and they are the reason several of the traps above exist.
- **Where a rule and the model disagree about a number, the longer span wins.** Masking something harmless is safe; missing it is not.

## Where the product truth lives

`PRODUCT.md` holds the product record: the platform, the users, the constraints, the evidence and the principles. `docs/PRODUCT.md` holds the behaviour of the current build for the person who uses it, and `HYPOTHESES.md` holds the open questions with the measurements behind them. Read them before changing behaviour, and write the change there when the behaviour changes.
