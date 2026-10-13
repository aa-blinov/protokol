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
- The pipeline stops before the LLM call and shows the masked text in full, with a pre-flight cost estimate, so the user reads exactly what would be sent and presses the button. Transcribing is slow and free; summarising is instant and billable — keeping them as separate steps is what makes both affordable to repeat. The analysed transcript is cached by a digest of the audio, so re-running the summary in another mode costs one model call and no re-transcription (measured: 0.025 s against 1.29 s on the same file).
- Entity types masked: names, phones, passports, emails, tax/insurance/medical numbers, cards, addresses, and similar (surfaced in the UI as `PERSON_1`, `PHONE_1`, `PASSPORT_1`, …).
- Speaker diarization (CPU, ONNX: pyannote segmentation + a 3D-Speaker CAM++ embedding, then cosine clustering) splits a multi-speaker recording into turns labelled `Спикер 1/2/…`, with no cap on the speaker count. Optional — a single-speaker recording, or a machine without the two small models, skips it.
- CPU-only inference; no GPU required.
- Delivered as a native desktop app (Electron shell wrapping a Python inference sidecar). Models (~0.7 GB) are bundled into the app for a self-contained, nomadic install.
- **Hard constraint — the only one that is non-negotiable: original PII must never reach the LLM or leave the machine.** Any future work that would break this is not a trade-off; it is disallowed.

## Evidence on Hand

- Ten UI screenshots of the real app in `docs/screenshots/`, all referenced from the README, including the pre-send review screen (`app-review.png`), shot from a real recording loaded through a real file input rather than a seeded session. Reshootable in one pass with `benchmarks/shoot_screenshots.py` plus `benchmarks/shoot_review_screen.py`; the theme is set and read back before every frame, because two consecutive shots came out byte-identical when the theme leaked from one into the next.
- Wire-level proof that raw PII never crossed to the LLM: a proxied end-to-end run logged the actual request body, which contained only tokens (`PERSON_1`, `PHONE_1`) and zero occurrences of the raw values; the reply was de-masked locally to the real values. Re-verified on a 10-minute meeting and on a diarized two-speaker recording (zero raw names/phones in the request body).
- Speaker diarization on the owner's real 12-minute call (ground truth from the owner: seven participants): the previous ERes2Net embedder merged voices into 4 labels; the CAM++ embedder returns all 7. On 16 in-the-wild VoxConverse recordings, CAM++ cuts mean DER from ~38% (ERes2Net) to ~18% while keeping the speaker count within ~2 on average.
- **Considered and rejected:** the NVIDIA Sortformer end-to-end ONNX diarizer is more accurate on VoxConverse (~12% DER, overlap-aware, no clustering threshold) but is hard-capped at **four** speakers, so it cannot represent a seven-person call. The embedding + clustering path was kept for that reason.
- 171 passing unit tests; end-to-end runs against the live LLM provider.
- The pre-send review screen is what makes principle 1 inspectable rather than merely asserted: the owner can read the complete masked text, and the tokens of the outgoing request, before anything is sent.
- **Absence to respect:** there are no customers, testimonials, benchmarks, pricing, or market claims. This is a private personal tool. Future work must not fabricate any of these.

## Product Principles

1. **Privacy is the product, not a feature.** It is the single mandatory constraint; anything that would send raw PII to a third party is a defect, whatever else it gains.
2. **The LLM is untrusted with identity.** It sees only opaque tokens; reconstruction of real values happens exclusively on the local machine.
3. **Local-first by default.** All processing runs on the owner's own device; no accounts, no data store, one narrowly-scoped outbound call.
4. **A daily tool must stay fast and low-friction** for someone with 8–10 meetings — but never at the cost of principle 1.
5. **Claims must be provable, not asserted.** The privacy guarantee is demonstrated at the wire, and future claims should meet the same bar.
