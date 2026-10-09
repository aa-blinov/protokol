#!/usr/bin/env bash
# Download the ONNX models into ./models. ~0.9 GB total, run once.
set -euo pipefail

cd "$(dirname "$0")"
mkdir -p models/gigaam models/rubert-pii models/diarization/segmentation

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

# Speaker diarization (~33 MB): pyannote segmentation marks speaker changes and a
# 3D-Speaker CAM++ model embeds every turn; cosine clustering groups them. CAM++
# separates more speakers than the ERes2Net it replaced (7 on a real call vs 4),
# and roughly halves the error on in-the-wild recordings. Optional — the app runs
# without it, just without speaker labels.
SEG="https://huggingface.co/onnx-community/pyannote-segmentation-3.0/resolve/main"
EMB="https://huggingface.co/Luigi/campplus-zh-en-onnx/resolve/main"
fetch "$SEG/config.json"                models/diarization/segmentation/config.json
fetch "$SEG/onnx/model.onnx"            models/diarization/segmentation/model.onnx
fetch "$EMB/campplus_zh_en_fp32.onnx"   models/diarization/embedding.onnx

echo
echo "Done. Model files:"
du -sh models/gigaam models/rubert-pii models/diarization
