# Architecture

How Protokol is put together.

One pipeline, split in two, running on the user's own machine. The
transcription, the speaker turns and the masking happen locally and cost
nothing. The summary is one call to a provider, and it is the only thing
that leaves the computer.

The desktop app is one process tree: an Electron window loads a page from a
Python sidecar listening on `127.0.0.1`, and the sidecar serves the built
interface and the API from the same origin, so there is no proxy and no
CORS. Under Docker the same sidecar sits behind nginx, with the interface
in a container of its own.

## The shape

| Module | What it is responsible for |
| --- | --- |
| `api/main.py` | The FastAPI app and every route. It mounts the built interface at the root, last, so the API routes win. |
| `api/stt.py` | The audio decoding and the speech recognition with GigaAM v3. It knows about the model and nothing about masking. |
| `api/diarization.py` | The speaker turns: segmentation, the voice embeddings and the clustering. |
| `api/dialogue.py` | Assigning the recognised words to the turns. |
| `api/ner.py` | The PII model and the sliding windows it runs in. |
| `api/rules.py` | The deterministic recognizers for the identifiers whose format can be checked. |
| `api/masking.py` | The tokens, the reverse map and the binding of the user's requirement. |
| `api/names.py` | Russian person names: one person, one token, whatever the case. |
| `api/llm.py` | The provider client, the prompts and the cost estimate. |
| `api/settings.py` | The key, the model, the address and the settings file itself. |
| `api/policy.py` | The organisation's policy file, read once at start. |
| `api/licensing.py`, `api/ed25519.py` | The trial, the licence file and its signature. |
| `api/analysis_cache.py` | The eight cached analyses and the digest that keys them. |
| `api/storage.py` | The files written 0600, and the FileVault check. |
| `api/config.py`, `api/schemas.py` | The environment with its defaults, and the request and response models. |
| `web/src/` | The Svelte interface. `App.svelte` holds the shell and the document, `Review.svelte` the pre-send screen, `Transcript.svelte` the transcript and the search, `components/` the app's own primitives. The kit comes from `@monos/ui`; the app adds only what the kit does not cover. |
| `web/e2e/` | The browser checks against a stub provider, and the screenshot script. |
| `desktop/main.js` | The shell: a free port, the sidecar and the window. |
| `desktop/build.sh`, `desktop/verify.sh` | The bundle for this platform, and the check that runs on it. |
| `benchmarks/` | The measurement scripts and the corpus builders. The corpora are downloaded, not committed. |
| `tools/license_tool.py` | The vendor-side tool that issues the licence files. The signing key never goes into the repository. |

## The data flow

```
recording
   |
   v
/api/transcribe            /api/analyse
   |                            |
   v                            v
PyAV: decode to 16 kHz mono
   |
   v
GigaAM v3, chunks of at most 20 s     (local, CPU)
   |
   v
transcript
   |
   +--> pyannote segmentation + CAM++ embedding + clustering   (local)
   |         |
   |         v
   |    speaker turns
   |
   v
ruBERT PII, windows of 512 tokens, overlap 128, threshold 0.3     (local)
   |
   v
rule layer fills the gaps the model left      (local)
   |
   v
masked text  +  reverse map
   |
   |   the reader sees the whole masked text and the cost estimate
   v
/api/summarize --> one provider call --> the protocol with the tokens in it
   |
   v
the tokens are replaced by the original values, with the case the model asked for
   |
   v
the document on screen
```

The restored text never goes back to the provider. The model returns the
tokens it was given, and the substitution happens on the machine that holds
the map.

## Decisions worth knowing about

### The pipeline is split in two

`/api/analyse` produces the transcript, the speakers and the masked text.
/api/summarize` produces the summary over an already analysed recording.
The reason is the money: the transcription takes about 30 seconds for a
20-minute recording and costs nothing, because nothing leaves the machine,
and the summary is one call that costs money. A second mode therefore costs
one call and no transcription, 0.025 s against 1.29 s on the same file.

### The rules may only fill the gaps

`rules.fill_gaps` keeps the parts of a rule span that the model did not
cover. The layer used to run over the model, and on the redmadrobot
benchmark it cost the card 6.2 F1 and the phone 2.2, because a rule span
and a model span over the same number counted as a hit and a miss at once.
Where a rule and the model disagree about a number, the longer span wins:
masking something harmless is safe, and missing it is not.

### The transcript is cached under a digest

The analysed transcript is cached under a digest of the audio bytes, the
file suffix, the model directory and `analysis_cache.PIPELINE_VERSION`, and
the cache holds the eight most recent recordings. The version is part of
the key on purpose: a change in the recognition or in the diarization that
does not bump it returns the old transcript for the same audio.

### The e2e head of the recogniser is a privacy requirement

`api/stt.py` loads `gigaam-v3-e2e-rnnt`. The plain head writes dictated
digits as words, the PII model does not read "восемь девятьсот" as a phone
number, and the number reaches the provider unmasked. The head is not a
quality choice.

### The words are cut at twenty seconds

`stt.SEGMENT_MAX_SECONDS` is 20.0, and the cut lands on the quietest frame
in the last 40% of the window, so a cut rarely falls inside a word. On a
real interview, 120-second chunks recognised 904 words where 20-second
chunks recognised 1051: the longer chunks lose speech without an error.

### The interface and the API share one origin

The sidecar serves the built interface at the root and the API under
`/api`, from the same process on the same port. There is no proxy in
between, no CORS header and no second origin to keep in step.

### The history lives in a file, not in the browser

The desktop shell takes a free port on every launch, and Chromium scopes
`localStorage` to the origin including the port. The history therefore
lives in `sessions.json` beside the settings file, and the browser holds
nothing that matters.

### The port is free and the interface is built

`desktop/main.js` starts the sidecar on a port it has just found free, and
the window loads `http://127.0.0.1:<port>`. The port changes on every
launch, which is why nothing in the interface may depend on a fixed one.

## Boundaries

- **Nothing but the masked text goes to the provider.** The transcription,
  the diarization and the masking run locally, and the request to the
  provider is made only when the reader asks for a summary.
- **`api/stt.py` knows about the model and nothing about masking.** The
  recogniser returns a transcript with the words in it; what becomes a
  token is decided further along, in `masking.py`.
- **The rule layer cannot widen the model's decision.** It fills the gaps
  and it does not argue.
- **The web interface never talks to the provider.** It talks to the
  sidecar, and the sidecar is the only thing that holds the key.
- **The signing key never enters the repository.** `tools/license_tool.py`
  keeps it in `~/.config/protokol/` with 0600, and the application only
  ever verifies a signature.
- **The licence check bounds the trial and nothing else.** A missing
  licence stops the summary after fourteen days and nothing more.
