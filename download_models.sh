#!/usr/bin/env bash
# Download the ONNX models into ./models. ~1.4 GB total, run once.
set -euo pipefail

cd "$(dirname "$0")"
mkdir -p models/gigaam models/rubert-pii models/diarization

fetch() {
  local url="$1" out="$2"
  if [ -s "$out" ]; then
    echo "skip  $out (already present)"
  else
    echo "get   $out"
    curl -sSL --fail --retry 3 -o "$out" "$url"
  fi
}

GIGAAM="https://huggingface.co/istupakov/gigaam-v3-onnx/resolve/main"
PII="https://huggingface.co/lockR/rubert-base-pii-ner-onnx/resolve/main"

# GigaAM v3 E2E CTC. The e2e variant is required: it normalises dictated digits
# so the PII model can recognise phone/passport/INN numbers at all. The plain
# v3_ctc model leaves them as words and they leak unmasked. The int8 export is
# used: same accuracy on our tests, ~0.5 GB lighter to load.
fetch "$GIGAAM/v3_e2e_ctc.int8.onnx"    models/gigaam/v3_e2e_ctc.int8.onnx
fetch "$GIGAAM/v3_e2e_ctc_vocab.txt"    models/gigaam/v3_e2e_ctc_vocab.txt
fetch "$GIGAAM/config.json"             models/gigaam/config.json

# ruBERT PII NER. Runs on CPU with the FP32 graph; the shipped upstream wrapper
# is CUDA-only, so the API brings its own CPU runtime.
fetch "$PII/model.optimized.fp32.onnx"  models/rubert-pii/model.optimized.fp32.onnx
fetch "$PII/config.json"                models/rubert-pii/config.json
fetch "$PII/tokenizer.json"             models/rubert-pii/tokenizer.json
fetch "$PII/tokenizer_config.json"      models/rubert-pii/tokenizer_config.json

# Speaker diarization: NVIDIA Sortformer v2.1 (end-to-end, overlap-aware, up to
# four speakers). One model replaces the old segmentation + embedding pair; it
# needs no clustering threshold, which is what kept getting the speaker count
# wrong on real calls. Optional — the app runs without it, just without labels.
SF="https://huggingface.co/cgus/diar_streaming_sortformer_4spk-v2.1-onnx/resolve/main"
fetch "$SF/diar_streaming_sortformer_4spk-v2.1.onnx"  models/diarization/sortformer.onnx

echo
echo "Done. Model files:"
du -sh models/gigaam models/rubert-pii models/diarization
