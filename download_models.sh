#!/usr/bin/env bash
# Download the ONNX models into ./models. ~1.6 GB total, run once.
set -euo pipefail

cd "$(dirname "$0")"
mkdir -p models/gigaam models/rubert-pii

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
# v3_ctc model leaves them as words and they leak unmasked.
fetch "$GIGAAM/v3_e2e_ctc.onnx"         models/gigaam/v3_e2e_ctc.onnx
fetch "$GIGAAM/v3_e2e_ctc_vocab.txt"    models/gigaam/v3_e2e_ctc_vocab.txt
fetch "$GIGAAM/config.json"             models/gigaam/config.json

# ruBERT PII NER. Runs on CPU with the FP32 graph; the shipped upstream wrapper
# is CUDA-only, so the API brings its own CPU runtime.
fetch "$PII/model.optimized.fp32.onnx"  models/rubert-pii/model.optimized.fp32.onnx
fetch "$PII/config.json"                models/rubert-pii/config.json
fetch "$PII/tokenizer.json"             models/rubert-pii/tokenizer.json
fetch "$PII/tokenizer_config.json"      models/rubert-pii/tokenizer_config.json

echo
echo "Done. Model files:"
du -sh models/gigaam models/rubert-pii
