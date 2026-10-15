#!/usr/bin/env bash
# Build the desktop app for the current platform (macOS or Linux).
#
#   ./desktop/build.sh          # auto-detect the platform
#   ./desktop/build.sh --mac    # force macOS targets (must run on a Mac)
#   ./desktop/build.sh --linux  # force Linux targets
#
# Models ARE bundled into the app (~0.6 GB), so it is self-contained and
# relocatable. They must therefore be present at build time — see the check in
# preflight and download_models.sh.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP_NAME="Протокол"

say()  { printf '\n\033[1m== %s\033[0m\n' "$*"; }
fail() { printf '\033[31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

# --------------------------------------------------------------------- target
case "${1:-auto}" in
  auto)      case "$(uname -s)" in
               Darwin) TARGET=mac ;;
               Linux)  TARGET=linux ;;
               *) fail "Неподдерживаемая ОС: $(uname -s)" ;;
             esac ;;
  --mac|mac) TARGET=mac ;;
  --linux|linux) TARGET=linux ;;
  *) fail "Неизвестная цель: $1 (ожидается --mac, --linux или ничего)" ;;
esac

# ------------------------------------------------------------------ preflight
say "Preflight ($TARGET)"
command -v node >/dev/null || fail "Нужен Node.js: brew install node"
command -v npm  >/dev/null || fail "Нужен npm"
command -v python3 >/dev/null || fail "Нужен Python 3.11+"

# Prefer an explicit interpreter (STTSHKA_PYTHON). Otherwise probe versioned
# names first, newest ahead: on macOS `python3` is Xcode's 3.9/3.10, while
# `brew install python@3.12` installs `python3.12` — so taking bare `python3`
# would pick a Python that is too old. And pip into system/Homebrew Python fails
# with PEP 668 "externally-managed-environment", which is why we always build
# inside a venv.
pick_python() {
  for candidate in "$@"; do
    # Probe stdout is discarded on purpose: anything the candidate prints would
    # otherwise be captured into PYTHON along with its name.
    if command -v "$candidate" >/dev/null 2>&1 \
      && "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

if [ -n "${STTSHKA_PYTHON:-}" ]; then
  PYTHON="$STTSHKA_PYTHON"
  command -v "$PYTHON" >/dev/null 2>&1 \
    || fail "STTSHKA_PYTHON=$PYTHON не найден — проверьте путь к интерпретатору."
  "$PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1 \
    || fail "STTSHKA_PYTHON=$PYTHON слишком старый: нужен Python 3.11+, а там $("$PYTHON" -V 2>&1 | head -1)"
else
  PYTHON="$(pick_python python3.14 python3.13 python3.12 python3.11 python3)" \
    || fail "Не найден Python 3.11+. Под macOS поставьте Homebrew-питон и повторите:
    brew install python@3.12
Сборка сама найдёт python3.12. Либо укажите интерпретатор явно:
    STTSHKA_PYTHON=/путь/к/python ./desktop/build.sh"
fi

VENV="$ROOT/api/.venv"
if [ ! -x "$VENV/bin/python" ]; then
  echo "создаю venv: $VENV (через $PYTHON)"
  "$PYTHON" -m venv "$VENV"
fi
PYTHON="$VENV/bin/python"
# Guards a pre-existing api/.venv built by an older interpreter (for instance by
# earlier manual instructions, before this script picked the version itself).
# Reusing it would fail later with an obscure error deep inside the build.
"$PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1 \
  || fail "api/.venv собран на слишком старом питоне: $("$PYTHON" -V 2>&1 | head -1)
Удалите его и повторите — скрипт создаст venv заново:
    rm -rf $VENV"

if [ "$TARGET" = mac ]; then
  [ "$(uname -s)" = "Darwin" ] \
    || fail "Цель mac собирается только на macOS: PyInstaller и electron-builder не кросс-компилируются."
  [ "$(uname -m)" = "arm64" ] \
    || fail "Ожидался Apple Silicon (arm64), сейчас $(uname -m). Для Intel соберите с --arch x64."
fi

echo "node:   $(node -v)"
echo "python: $("$PYTHON" -V 2>&1)"
echo "arch:   $(uname -m)"

# Models are bundled into the app, so they must exist before the bundle step —
# otherwise electron-builder happily ships an app that cannot transcribe.
MODELS_SRC="$ROOT/models"
for model_file in \
  "gigaam/v3_e2e_rnnt_encoder.int8.onnx" \
  "gigaam/v3_e2e_rnnt_decoder.int8.onnx" \
  "gigaam/v3_e2e_rnnt_joint.int8.onnx" \
  "gigaam/v3_e2e_rnnt_vocab.txt" \
  "gigaam/config.json" \
  "rubert-pii/model.optimized.fp16.onnx" \
  "rubert-pii/config.json" \
  "rubert-pii/tokenizer.json"
do
  [ -s "$MODELS_SRC/$model_file" ] \
    || fail "Нет модели $model_file в $MODELS_SRC
Модели вшиваются в приложение, поэтому их нужно скачать ДО сборки:
    ./download_models.sh"
done
echo "модели: $(du -sh "$MODELS_SRC" | cut -f1) в $MODELS_SRC (будут вшиты)"

# ------------------------------------------------------------- web frontend
say "1/4  Веб-интерфейс"
cd "$ROOT/web"
[ -d node_modules ] || npm install --no-audit --no-fund
npm run build

# ------------------------------------------------------------ python sidecar
say "2/4  Python sidecar (PyInstaller)"
cd "$ROOT/api"
# Installing on the target machine is what puts the right onnxruntime there — on
# Apple Silicon that is what makes the CoreML execution provider available.
"$PYTHON" -m pip install -q -r requirements.txt
"$PYTHON" -c 'import PyInstaller' 2>/dev/null || "$PYTHON" -m pip install -q pyinstaller

rm -rf dist build
"$PYTHON" -m PyInstaller --noconfirm --clean sttshka-api.spec
[ -x "dist/sttshka-api/sttshka-api" ] || fail "PyInstaller не собрал бинарь sidecar"

# ----------------------------------------------------------- desktop bundle
say "3/4  Сборка приложения (electron-builder)"
cd "$ROOT/desktop"
# fpm/xz stages the whole ~2.2G payload inside TMPDIR while packing the deb.
# Where /tmp is a small tmpfs that fails with a cryptic `tar failed (exit code
# 2)`. Point staging at disk so the deb build never depends on tmpfs size.
BUILD_TMPDIR="${XDG_CACHE_HOME:-$HOME/.cache}/sttshka-build-tmp"
mkdir -p "$BUILD_TMPDIR"
export TMPDIR="$BUILD_TMPDIR"
[ -d node_modules ] || npm install --no-audit --no-fund
if [ "$TARGET" = mac ]; then
  # Do not let electron-builder pick up whatever certificate happens to sit in the
  # keychain: osx-sign then walks the whole 1.4 GB bundle (the ONNX models are
  # hundreds of MB each) and dies with "RangeError: Invalid array length" inside
  # isbinaryfile, leaving a half-signed .app behind. Auto-discovery stays off; the
  # identity is named explicitly below, so nothing is picked up by accident.
  export CSC_IDENTITY_AUTO_DISCOVERY=false
  # A distributable build names a Developer ID Application certificate and a notarytool
  # keychain profile (see DESKTOP.md). Without them the build is ad-hoc signed and runs
  # on this Mac only. The notarisation password never passes through this script.
  IDENTITY="${PROTOKOL_SIGN_IDENTITY:-}"
  NOTARY_PROFILE="${PROTOKOL_NOTARY_PROFILE:-}"
  if [ -n "$IDENTITY" ]; then
    export CSC_NAME="$IDENTITY"
    say "подпись: $IDENTITY, hardened runtime"
  fi
  # The unpacked app is built first. The DMG and ZIP are cut from it only after it is
  # signed below: packing all three at once put an unsigned bundle inside the images,
  # and the checks that followed looked only at the unpacked copy.
  npx electron-builder --mac dir --arm64

  APP_DIR="$ROOT/desktop/release/mac-arm64/sttshka.app"
  [ -d "$APP_DIR" ] || fail "electron-builder не собрал $APP_DIR"
  if [ -n "$IDENTITY" ]; then
    # electron-builder signed the unpacked app with the identity above. Check it independently.
    codesign --verify --deep --strict "$APP_DIR" || fail "подпись $IDENTITY не проходит проверку"
    echo "подпись $IDENTITY на месте"
  else
    say "подпись приложения (ad-hoc)"
    # Skipping signing entirely is not enough: Apple Silicon refuses to execute an
    # unsigned bundle. Signing ad-hoc is what a local build needs, and it also
    # replaces any stale signature left by an earlier interrupted run.
    codesign --remove-signature "$APP_DIR" 2>/dev/null || true
    find "$APP_DIR" -name "._*" -delete 2>/dev/null || true
    codesign --force --deep --sign - "$APP_DIR" \
      || fail "не удалось подписать приложение ad-hoc"
    # Never trust the build's exit status alone here: a bundle can carry a stale or
    # partial signature and still "succeed". Verify it independently.
    codesign --verify --deep --strict "$APP_DIR" \
      || fail "подпись приложения не проходит проверку"
    echo "подпись ad-hoc на месте и проходит проверку"
  fi

  # electron-builder does not repack a prepackaged app, so the signature survives into the images.
  npx electron-builder --mac dmg zip --arm64 --prepackaged "$APP_DIR"

  DMG="$(ls -t "$ROOT"/desktop/release/*.dmg | head -n 1)"
  if [ -n "$IDENTITY" ] && [ -n "$NOTARY_PROFILE" ]; then
    say "нотаризация у Apple (несколько минут)"
    xcrun notarytool submit "$DMG" --keychain-profile "$NOTARY_PROFILE" --wait \
      || fail "нотаризация не прошла: xcrun notarytool log <id> --keychain-profile $NOTARY_PROFILE"
    xcrun stapler staple "$DMG" || fail "stapler не приклеил билет нотаризации"
    spctl --assess --type open --context context:primary-signature -vv "$DMG" \
      || fail "Gatekeeper не принимает DMG"
    echo "DMG нотаризован и принимается Gatekeeper"
  elif [ -n "$IDENTITY" ]; then
    echo "нотаризация пропущена: задайте PROTOKOL_NOTARY_PROFILE (см. DESKTOP.md)"
  fi

  # Check the image itself: the signature above was made on the unpacked copy only.
  MNT="$(mktemp -d)"
  hdiutil attach -nobrowse -readonly -mountpoint "$MNT" "$DMG" >/dev/null || fail "не смонтировался $DMG"
  SIGNED=0
  codesign --verify --deep --strict "$MNT/$(basename "$APP_DIR")" >/dev/null 2>&1 && SIGNED=1
  hdiutil detach "$MNT" >/dev/null || true
  rmdir "$MNT" 2>/dev/null || true
  [ "$SIGNED" -eq 1 ] || fail "подпись приложения внутри $(basename "$DMG") не проходит проверку"
  echo "подпись приложения внутри DMG проходит проверку"
else
  npx electron-builder --linux AppImage deb
fi

# ---------------------------------------------------------------------- done
say "4/4  Готово"
ls -la release/*.dmg release/*.AppImage release/*.deb 2>/dev/null || ls -la release/

echo
echo "Установка:"
if [ "$TARGET" = mac ]; then
  echo "  1. Откройте release/*.dmg и перетащите '$APP_NAME' в Applications."
else
  echo "  1. Установите release/*.deb (или запустите release/*.AppImage)."
fi
echo "  2. Модели уже вшиты в приложение — ничего копировать не нужно."
echo "  3. Проверка: ./desktop/verify.sh"
if [ "$TARGET" = mac ]; then
  echo "  4. При первом запуске macOS может попросить подтвердить приложение,"
  echo "     если оно не нотариально заверено (см. DESKTOP.md)."
fi
