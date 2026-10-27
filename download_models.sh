#!/usr/bin/env bash
# Download the ONNX models into ./models for a development run. ~0.6 GB, run once.
# The app fetches the same files itself on first launch (api/model_store.py); the
# repository revisions below are the ones that file pins, so both read identical bytes.
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

GIGAAM="https://huggingface.co/istupakov/gigaam-v3-onnx/resolve/322c3b29492673eb7d0b434bfa9dfb8653e34d02"
PII="https://huggingface.co/lockR/rubert-base-pii-ner-onnx/resolve/ea7610b22808c509c0c8b7c7b0f6639c19684d08"

# GigaAM v3 E2E RNN-T. The e2e variant is required: it normalises dictated digits
# so the PII model can recognise phone/passport/INN numbers at all. The plain
# v3_rnnt model leaves them as words and they leak unmasked. The int8 export is
# used. Against the e2e CTC head at the same chunk length, RNN-T has slightly fewer
# word errors (FLEURS 3.84% vs 4.09%, a labelled dialogue 4.00% vs 4.35%) at the
# same speed, and both write the same share of numbers as digits.
fetch "$GIGAAM/v3_e2e_rnnt_encoder.int8.onnx"  models/gigaam/v3_e2e_rnnt_encoder.int8.onnx
fetch "$GIGAAM/v3_e2e_rnnt_decoder.int8.onnx"  models/gigaam/v3_e2e_rnnt_decoder.int8.onnx
fetch "$GIGAAM/v3_e2e_rnnt_joint.int8.onnx"    models/gigaam/v3_e2e_rnnt_joint.int8.onnx
fetch "$GIGAAM/v3_e2e_rnnt_vocab.txt"          models/gigaam/v3_e2e_rnnt_vocab.txt
fetch "$GIGAAM/config.json"             models/gigaam/config.json

# ruBERT PII NER. Runs on CPU with the FP16 graph (same benchmark F1 as FP32, half
# the size); the shipped upstream wrapper is CUDA-only, so the API brings its own CPU runtime.
fetch "$PII/model.optimized.fp16.onnx"  models/rubert-pii/model.optimized.fp16.onnx
fetch "$PII/config.json"                models/rubert-pii/config.json
fetch "$PII/tokenizer.json"             models/rubert-pii/tokenizer.json
fetch "$PII/tokenizer_config.json"      models/rubert-pii/tokenizer_config.json

# Speaker diarization (~33 MB): pyannote segmentation marks speaker changes and a
# 3D-Speaker CAM++ model embeds every turn; cosine clustering groups them. CAM++
# separates more speakers than the ERes2Net it replaced (7 on a real call vs 4),
# and roughly halves the error on in-the-wild recordings. Optional — the app runs
# without it, just without speaker labels.
SEG="https://huggingface.co/onnx-community/pyannote-segmentation-3.0/resolve/733a93b6473d019a773298e08cefa686894b1854"
EMB="https://huggingface.co/Luigi/campplus-zh-en-onnx/resolve/aa79cf9b8628a46ca362bf9bf7cde226a470a282"
fetch "$SEG/config.json"                models/diarization/segmentation/config.json
fetch "$SEG/onnx/model.onnx"            models/diarization/segmentation/model.onnx
fetch "$EMB/campplus_zh_en_fp32.onnx"   models/diarization/embedding.onnx

echo
echo "Done. Model files:"
du -sh models/gigaam models/rubert-pii models/diarization
