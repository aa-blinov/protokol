#!/usr/bin/env bash
# Check a built desktop app actually works: bundle, models, inference, provider.
# Run on the platform you built for, after ./desktop/build.sh.
#
#   ./desktop/verify.sh
#
# Exits non-zero if anything is broken. Written for macOS's stock bash 3.2.
set -u

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP_NAME="Протокол"

PASS=0
FAIL=0
ok()   { printf '  \033[32mPASS\033[0m %s\n' "$*"; PASS=$((PASS + 1)); }
bad()  { printf '  \033[31mFAIL\033[0m %s\n' "$*"; FAIL=$((FAIL + 1)); }
note() { printf '       %s\n' "$*"; }
section() { printf '\n\033[1m== %s\033[0m\n' "$*"; }

# ---------------------------------------------------------------- platform
section "Платформа"
OS="$(uname -s)"
ARCH="$(uname -m)"
if [ "$OS" = "Darwin" ]; then
  ok "macOS $(sw_vers -productVersion 2>/dev/null)"
  APP_DIR="${APP_DIR:-$ROOT/desktop/release/$APP_NAME.app}"
  RESOURCES="$APP_DIR/Contents/Resources"
  # Models ship inside the bundle now, so the app's own Resources is the default.
  MODELS_DIR="${MODELS_DIR:-$RESOURCES/models}"
  EXE="$RESOURCES/sidecar/sttshka-api/sttshka-api"
  if [ "$ARCH" = "arm64" ]; then ok "Apple Silicon ($ARCH)"; else bad "Ожидался arm64, сейчас $ARCH."; fi
elif [ "$OS" = "Linux" ]; then
  ok "Linux ($ARCH)"
  APP_DIR="${APP_DIR:-$ROOT/desktop/release/linux-unpacked}"
  RESOURCES="$APP_DIR/resources"
  # Models ship inside the bundle now, so the app's own resources dir is the default.
  MODELS_DIR="${MODELS_DIR:-$RESOURCES/models}"
  EXE="$RESOURCES/sidecar/sttshka-api/sttshka-api"
  # CoreML exists only on Apple Silicon; on Linux CPU is the expected provider.
  if [ "$ARCH" = "x86_64" ] || [ "$ARCH" = "aarch64" ]; then ok "поддерживаемая архитектура ($ARCH)"; fi
else
  bad "Неподдерживаемая ОС: $OS"
fi

# ------------------------------------------------------------------ bundle
section "Сборка приложения"
if [ -d "$APP_DIR" ]; then ok "найдено: $APP_DIR"; else bad "нет сборки: $APP_DIR (запустите ./desktop/build.sh)"; fi
if [ -x "$EXE" ]; then ok "sidecar: $EXE"; else bad "sidecar не найден: $EXE"; EXE=""; fi
if [ -f "$RESOURCES/web/index.html" ]; then ok "веб-интерфейс упакован"; else bad "нет $RESOURCES/web/index.html"; fi

# ------------------------------------------------------------------ models
section "Модели ($MODELS_DIR)"
MISSING=0
for f in \
  "gigaam/v3_e2e_ctc.int8.onnx" \
  "gigaam/v3_e2e_ctc_vocab.txt" \
  "gigaam/config.json" \
  "rubert-pii/model.optimized.fp32.onnx" \
  "rubert-pii/config.json" \
  "rubert-pii/tokenizer.json"
do
  if [ -s "$MODELS_DIR/$f" ]; then ok "$f"; else bad "не хватает $f"; MISSING=1; fi
done
if [ "$MISSING" -eq 1 ]; then
  note "модели вшиваются при сборке: выполните ./download_models.sh и пересоберите ./desktop/build.sh"
fi

# Diarization ships as two small (~33 MB) optional models. Missing them is not
# fatal — the app just cannot label speakers — so this is a note, not a failure.
if [ -s "$MODELS_DIR/diarization/segmentation/model.onnx" ] && [ -s "$MODELS_DIR/diarization/embedding.onnx" ]; then
  ok "модели диаризации на месте"
else
  note "модели диаризации не вшиты: разбивка по говорящим будет недоступна (./download_models.sh)"
fi

# ------------------------------------------- launch sidecar and probe it
section "Запуск sidecar и инференс"
if [ -z "$EXE" ]; then
  echo "  Пропущено: sidecar недоступен. $PASS ok, $FAIL ошибок."
  exit 1
fi

PORT="$(python3 -c 'import socket;s=socket.socket();s.bind(("127.0.0.1",0));print(s.getsockname()[1]);s.close()')"
LOG="$(mktemp -t sttshka-verify.XXXXXX)"

HOST=127.0.0.1 PORT="$PORT" MODELS_DIR="$MODELS_DIR" \
  WEB_DIST_DIR="$RESOURCES/web" \
  "$EXE" >"$LOG" 2>&1 &
SRV=$!
trap 'kill "$SRV" 2>/dev/null' EXIT

HEALTH=""
i=0
while [ $i -lt 60 ]; do
  HEALTH="$(curl -sS -m 3 "http://127.0.0.1:$PORT/api/health" 2>/dev/null)"
  [ -n "$HEALTH" ] && break
  i=$((i + 1))
  sleep 1
done

if [ -z "$HEALTH" ]; then
  bad "sidecar не ответил на /api/health за 60 с"
  note "лог: $LOG"
  tail -n 15 "$LOG" | sed 's/^/       /'
  exit 1
fi
ok "sidecar поднялся на http://127.0.0.1:$PORT"

if printf '%s' "$HEALTH" | grep -q '"stt":true' && printf '%s' "$HEALTH" | grep -q '"ner":true'; then
  ok "модели загружаются"
else
  bad "health сообщает, что модели недоступны: $HEALTH"
fi

if printf '%s' "$HEALTH" | grep -q '"diarization":true'; then
  ok "диаризация доступна"
else
  note "диаризация недоступна в этой сборке (модели не вшиты) — остальное работает"
fi

# Real inference: loads the NER model and reveals which provider it actually uses.
MASK="$(curl -sS -m 120 -X POST -H 'Content-Type: application/json' \
  -d '{"text":"Мой номер телефона 8 900 123-45-67, а имя Иван Петров."}' \
  "http://127.0.0.1:$PORT/api/mask" 2>/dev/null)"

if printf '%s' "$MASK" | grep -q '"masked_text":".*\[PERSON_1\]' && printf '%s' "$MASK" | grep -q '\[PHONE_1\]'; then
  ok "маскирование работает: Иван Петров -> [PERSON_1], номер -> [PHONE_1]"
else
  bad "маскирование не сработало: $MASK"
fi

# The rule layer covers the structured identifiers the model misses (IP, INN,
# SNILS, card). Check them by their tokens so a regression is caught here.
STRUCT="$(curl -sS -m 120 -X POST -H 'Content-Type: application/json' \
  -d '{"text":"ИНН 7707083893, СНИЛС 123-456-789 64, IP 192.168.0.1, карта 4111 1111 1111 1111."}' \
  "http://127.0.0.1:$PORT/api/mask" 2>/dev/null)"
if printf '%s' "$STRUCT" | grep -q '\[INN_1\]' && printf '%s' "$STRUCT" | grep -q '\[SNILS_1\]' \
  && printf '%s' "$STRUCT" | grep -q '\[IP_1\]' && printf '%s' "$STRUCT" | grep -q '\[CARD_1\]'; then
  ok "правила ловят структурные ПДн: ИНН, СНИЛС, IP, карта"
else
  bad "правила не сработали: $STRUCT"
fi

HEALTH2="$(curl -sS -m 10 "http://127.0.0.1:$PORT/api/health" 2>/dev/null)"
ACTIVE="$(printf '%s' "$HEALTH2" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("ner_provider") or "")' 2>/dev/null)"
if [ -z "$ACTIVE" ]; then
  bad "ner_provider пуст после инференса — модель не поднялась"
elif printf '%s' "$ACTIVE" | grep -q CoreML; then
  ok "инференс идёт на CoreML ($ACTIVE)"
elif [ "$OS" = "Darwin" ]; then
  note "внимание: инференс на CPU ($ACTIVE), CoreML не подключился"
  note "приложение будет работать, но медленнее. Переключение: USE_COREML=0|1"
else
  ok "инференс на CPU ($ACTIVE) — на Linux это ожидаемо, CoreML тут недоступен"
fi

START=$(python3 -c 'import time;print(time.time())')
curl -sS -m 300 -X POST -H 'Content-Type: application/json' \
  -d '{"text":"Здравствуйте, меня зовут Иван Петров. Мой номер телефона 8 912 345 67 89. Паспорт 45 11 123456, ИНН 770123456789. Адрес: Москва, улица Тверская, дом 12."}' \
  "http://127.0.0.1:$PORT/api/mask" > /dev/null 2>&1
END=$(python3 -c 'import time;print(time.time())')
note "маскирование длинного текста: $(python3 -c "print(f'{$END-$START:.2f}')") с"

# --------------------------------------------------------------------- SPA
if curl -sS -m 10 "http://127.0.0.1:$PORT/" 2>/dev/null | grep -q '<div id="root">'; then
  ok "интерфейс отдаётся sidecar'ом"
else
  bad "sidecar не отдаёт интерфейс"
fi

kill "$SRV" 2>/dev/null

section "Итог"
echo "  $PASS проверок прошло, $FAIL ошибок."
if [ "$FAIL" -gt 0 ]; then
  echo "  Лог sidecar: $LOG"
  exit 1
fi
echo "  Всё в порядке. Приложение готово к использованию."
