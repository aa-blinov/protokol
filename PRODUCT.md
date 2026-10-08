# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Primary user: a banking top-manager, using it **personally** — the single user is the owner, on their own laptop. Their situation: 8–10 meetings/calls a day, each leaving behind audio that is full of personal data (names, phones, passport and tax numbers, addresses, card details). The job: turn that call audio into a usable transcript and an LLM-drawn summary/answer **without ever exposing anyone's personal data** to the model or to the network.

## Product Purpose

Transcribe call/meeting audio, detect and mask PII locally, send only the masked text to an LLM, then restore the original values in the reply — all on the person's own machine. It exists so a banking executive can put sensitive call content through a strong LLM and get real value from it, while raw personal data never reaches that LLM and never leaves the machine in identifiable form. Success = a genuinely useful summary/answer of a meeting, produced under a guarantee that the underlying PII was never transmitted.

## Positioning

The mechanism a neighbouring product could not truthfully copy: **PII never reaches the LLM.** Masking happens before the request; the substitution map (PERSON_1 → "Иван Петров", PHONE_1 → the real number) stays in local memory; the model only ever sees opaque tokens; the reply is de-masked locally. This is a verifiable property of the wire traffic, not a policy or a promise. A competitor who sends raw text to any LLM — even an "enterprise-private" one — cannot honestly make this claim.

## Operating Context

- Personal, single-user tool on the owner's own laptop. Primary target: native macOS `.app` for Apple Silicon (double-clicked, no terminal); Linux desktop is the secondary target. Docker is only the dev/verification path.
- Input: recorded call/meeting audio (wav, mp3, m4a), throughout a heavy meeting day.
- One outbound network step only — the LLM call — and it carries masked text exclusively. Everything else (STT, PII detection, masking, de-masking) runs locally on CPU.
- The OpenRouter API key lives in a gitignored `.env` (or `userData/.env` for the packaged app) and is never bundled into the artifact.
- Interface language is Russian (Russian UI copy and pluralization).

## Capabilities and Constraints

- Pipeline: audio → speech-to-text → speaker diarization (optional) → PII entity recognition → token-substitution masking → LLM → local reverse-substitution of the reply.
- Entity types masked: names, phones, passports, emails, tax/insurance/medical numbers, cards, addresses, and similar (surfaced in the UI as `PERSON_1`, `PHONE_1`, `PASSPORT_1`, …).
- Speaker diarization (CPU, ONNX: pyannote segmentation + 3D-Speaker embeddings) splits a multi-speaker recording into turns labelled `Спикер 1/2/…`. Optional — a single-speaker recording, or a machine without the two small models, skips it.
- CPU-only inference; no GPU required.
- Delivered as a native desktop app (Electron shell wrapping a Python inference sidecar). Models (~1.6 GB) are bundled into the app for a self-contained, nomadic install.
- **Hard constraint — the only one that is non-negotiable: original PII must never reach the LLM or leave the machine.** Any future work that would break this is not a trade-off; it is disallowed.

## Evidence on Hand

- Two UI screenshots of the real app (`docs/screenshots/app-results.png`, `docs/screenshots/app-empty.png`).
- Wire-level proof that raw PII never crossed to the LLM: a proxied end-to-end run logged the actual request body, which contained only tokens (`PERSON_1`, `PHONE_1`) and zero occurrences of the raw values; the reply was de-masked locally to the real values. Re-verified on a 10-minute meeting and on a diarized two-speaker recording (zero raw names/phones in the request body).
- Speaker diarization verified on a 75-second two-speaker recording built from real Common Voice ru voices: 2 speakers found, 0% speaker confusion (all residual DER is silence inside the reference turns).
- 37 passing unit/integration tests; end-to-end runs against the live LLM provider.
- **Absence to respect:** there are no customers, testimonials, benchmarks, pricing, or market claims. This is a private personal tool. Future work must not fabricate any of these.

## Product Principles

1. **Privacy is the product, not a feature.** It is the single mandatory constraint; anything that would send raw PII to a third party is a defect, whatever else it gains.
2. **The LLM is untrusted with identity.** It sees only opaque tokens; reconstruction of real values happens exclusively on the local machine.
3. **Local-first by default.** All processing runs on the owner's own device; no accounts, no data store, one narrowly-scoped outbound call.
4. **A daily tool must stay fast and low-friction** for someone with 8–10 meetings — but never at the cost of principle 1.
5. **Claims must be provable, not asserted.** The privacy guarantee is demonstrated at the wire, and future claims should meet the same bar.
