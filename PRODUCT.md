# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

The interface is a React application. It ships as a native desktop app for macOS on Apple Silicon, with Linux as the second target, and it also runs as a web deployment behind nginx in Docker. The desktop app is one process tree: an Electron window loads a page from a Python sidecar that serves both the interface and the API from one origin on `127.0.0.1`.

## Users

The owner, personally, on their own laptop. A banking manager with 8 to 10 calls a day, each leaving behind audio full of names, phone numbers, passport and tax numbers, addresses and card details. The job: turn that audio into a usable transcript and a summary, without any of it reaching the model or the network in the clear.

A second audience exists now and it is small: an administrator who installs the app on a team's Macs, fixes the provider address and the retention period with a policy file, and issues licence files. The repository and the app are private and the builds are unsigned, so there is no download count to report.

## Product Purpose

Transcribe call and meeting audio, detect and mask personal data locally, send only the masked text to a language model, then restore the original values in the reply, on the owner's own machine.

It exists so that a person can put sensitive call content through a strong model and get a real protocol back, with a guarantee that the underlying personal data never crossed the network. Success for the user is a protocol worth reading. Success for the product is a request body that holds tokens and no raw values, and a person who has read the whole outgoing text before it was sent.

## Positioning

The mechanism a neighbouring tool could not honestly copy: personal data never reaches the model. The masking happens before the request, the substitution map stays in the machine's memory, the model only ever sees opaque tokens, and the reply is restored locally. That is a property of the traffic, not a policy statement. A tool that sends raw text to any model, even one that promises not to keep it, cannot make the same claim.

The second difference is the inspection step. The whole masked text and the cost of the call are on screen before the button, and the pipeline is split in two, so a second summary in another mode costs one model call and no transcription.

The third is the rules layer under the model. The identifiers whose format can be checked mechanically are covered by checksums and patterns, so a number the model splits in half is still masked whole.

## Operating Context

The app sits on one Mac and is used through a day of calls. A recording is dragged into the window, the transcript is read, the summary is copied or printed, and the person moves on. One outbound request happens, and only when the summary button is pressed.

The sidecar listens on `127.0.0.1` and nothing is exposed to the network. The desktop shell takes a random free port on every launch, so the settings, the history and the licence live in files under the user's application support folder rather than in the browser's storage.

In an organisation, an administrator drops one JSON file at `/Library/Application Support/Protokol/policy.json`. The app reads it at start and applies it after a restart, and a bad value in it is reported in the interface rather than stopping the app.

The recording itself is read into memory, decoded into a temporary folder and deleted after recognition. The app does not keep the audio.

## Capabilities and Constraints

Confirmed by the code:

- The pipeline is: audio, decode, transcript, speaker turns, masking, provider, restore.
- Recognition is GigaAM v3, the `e2e` RNN-T head in the int8 export, on the CPU through `onnx-asr`. The audio is cut into chunks of at most 20 seconds at the quietest frame near the limit.
- The PII model is ruBERT-base-pii-ner in its fp16 ONNX export, run in windows of 512 tokens that overlap by 128, with a confidence threshold of 0.3.
- A rule layer covers the identifiers the model missed: tax id, social insurance number, card number by the Luhn algorithm, passport, phone, insurance policy number, one-time codes, access tokens, company registration numbers and addresses.
- Seventeen display types reach the interface: person, address, card, phone, email, url, ip, passport, tax id, social insurance number, insurance policy number, driving licence, military id, birth certificate, secret, sole proprietor number and company id. A number that is none of those is masked as a generic number.
- A person is one token whatever the case, and the reply is restored in the case the model asks for, using the Russian morphology dictionaries.
- Speaker labels are relative. Diarization is optional: pyannote segmentation finds the turn boundaries, a CAM++ embedding says who spoke, and the turns are clustered at 0.46. Without those two models the app runs without speaker labels.
- The transcript is recognised in one pass over the whole recording, and every word is attached to the turn it started in.
- The pipeline is split. `/api/analyse` produces the transcript, the speakers and the masked text, `/api/summarize` produces the summary over an already analysed recording.
- The analysed transcript is cached under a digest of the audio bytes, the format, the model directory and a pipeline version, and the cache holds eight recordings.
- The pre-flight estimate counts the requests the pipeline will really make: a transcript over 24,000 characters is compressed in chunks of 8,000 first, and the estimate says how many requests that is.
- The request carries `data_collection: deny` by default, and it can be restricted to endpoints with a zero data retention policy.
- Three summary modes. A free-text requirement is masked like the transcript, and a requirement that names personal data the recording does not hold is refused before the request goes out.
- A 14-day trial from the first launch, then a licence file signed with Ed25519 and checked offline against a public key in the binary.
- The provider key lives in the settings file next to the application data, or in `.env` in the repository, and it is never bundled into the artefact.
- The history keeps up to 50 recordings, the analysis cache keeps 8, and the retention period is set by the user or by the policy file.

Deliberately not true, and worth knowing before a change:

- The app is not signed with a Developer ID and not notarised. A local build is signed ad hoc and runs on the machine that built it.
- There is no automatic update and no log of the requests that were made.
- The files on disk hold the transcript with the names in the clear. They are written 0600, the app warns when FileVault is off, and it does not encrypt them itself.
- The speaker labels carry no names, and on noisy recordings the number of labels can be off by one or two.
- Overlapped speech is not separated. A word belongs to one turn.
- A licence protects the terms between the vendor and the customer, not the binary.

## Brand Commitments

**Name:** Protokol. The wordmark in the interface reads «Протокол», and the mark is a page with one line redacted.

**Tone:** plain and technical, in Russian. The interface reports the state of the pipeline rather than reassuring the person using it.

The result is a document, not a dashboard: one column of running text, sections separated by hairline rules and small monospace labels, in the order the data flows.

Colour means personal data. The only saturated colour on screen belongs to the entity chips, and the single accent marks the primary action, the live progress or the focus ring.

The privacy promise has one home per moment, chosen by when it becomes true: the empty state says what happens next, the review band says what was hidden, the document shows the masked copy instead of describing it.

The summary is a draft. The interface says so and asks for a check.

## Evidence on Hand

- `docs/screenshots/` holds ten screenshots of the real interface, taken from the current build by `benchmarks/shoot_screenshots.py` and `benchmarks/shoot_review_screen.py`. The meeting in them is invented.
- Word error rate 4.77% on the whole FLEURS ru test split: 774 clips, 149.8 minutes of speech, 15,085 words, measured in `HYPOTHESES.md`.
- Masking on PII-Bench (ru, 1,810 synthetic examples): token F1 96.8, precision 98.2, recall 95.5. The set is synthetic and the rules were written against its misses, so the number is an upper bound rather than a promise.
- The redmadrobot benchmark, 2,839 sentences over 21 types: F1 94.8% for the model alone and 94.8% for the model with the rule layer, with recall rising from 92.9% to 93.6%.
- Speaker labels on the owner's real 12-minute call with seven participants: the CAM++ embedder returned seven, the one it replaced returned four. Mean diarization error on 43 VoxConverse dev recordings at the current threshold is 22.8%.
- A wire-level check of a proxied end-to-end run recorded a request body with tokens and no raw values, repeated on a 10-minute meeting and on a two-speaker recording.
- 361 test functions in `api/tests/`, and a browser check in `web/e2e/run.mjs` that drives the real interface against a stub provider.
- Absent, and not to be invented: no customers, no testimonials, no download counts, no pricing, no comparison with other transcription tools.

## Product Principles

1. **Personal data never reaches the provider.** Masking happens before the request and the restoration happens on the machine. Anything that would send a raw value out is a defect, whatever it gains.
2. **The model is untrusted with identity.** It sees opaque tokens, it may be asked to keep them, and it may fail. An invented token is shown to the person instead of being quietly left in the text.
3. **Local first.** Recognition, detection, masking and restoration run on the device. One outbound call, carrying masked text only, and it happens when a button is pressed.
4. **Show before you spend.** The whole outgoing text and the cost of the call are on screen first. A transcript with no summary is a legitimate outcome and costs nothing.
5. **Claims must be provable.** The privacy property is demonstrated at the wire and the numbers come from measurements kept in the repository. A claim that cannot be measured does not go into the documents.

## Accessibility & Inclusion

- The review screen is the safety step, and it is readable in full: the whole outgoing text, the count of hidden values, and the cost of the call.
- Search works from the keyboard. Enter and Shift+Enter step through the matches from anywhere on the page, and the counter says how many there are.
- Contrast is measured rather than assumed. `benchmarks/ui_audit.py` applies WCAG 1.4.3 to every text-on-surface pair in both themes, and `desktop/verify.sh` runs it.
- The layout holds at 375 px in one column with no horizontal scroll, and at 200% zoom.
- Forced colours mode is handled explicitly: the focus ring is redrawn against the system canvas colour and the tinted status band keeps a visible background.
- Motion is turned off when the system asks for it.
- The interface is in Russian, and the speaker labels are numbered rather than coloured, so identity never depends on a hue.
- Not decided: nothing in the repository records who else the interface should serve, and no screen-reader testing is recorded. The contrast audit covers the screen; the printed page and the exported `.txt` are not checked.
