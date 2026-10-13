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

# Where the build actually lands. electron-builder names the bundle after the
# package name (sttshka.app) and puts it in an arch folder; the "Протокол.app"
# name only appears inside the .dmg, once a person drags it out. Checking
# release/Протокол.app -- which is what this script used to do -- therefore
# never found anything, and every check below it reported FAIL against a
# perfectly good build.
resolve_macos_app() {
  for candidate in \
    "$ROOT/desktop/release/mac-arm64/sttshka.app" \
    "$ROOT/desktop/release/mac-arm64/$APP_NAME.app" \
    "$ROOT/desktop/release/$APP_NAME.app" \
    "/Applications/$APP_NAME.app"; do
    if [ -d "$candidate" ]; then printf '%s' "$candidate"; return 0; fi
  done
  # Last resort: whatever the newest .app in the release tree is.
  local found
  found="$(find "$ROOT/desktop/release" -maxdepth 2 -name '*.app' -type d 2>/dev/null | head -1)"
  [ -n "$found" ] && printf '%s' "$found"
}

if [ "$OS" = "Darwin" ]; then
  ok "macOS $(sw_vers -productVersion 2>/dev/null)"
  APP_DIR="${APP_DIR:-$(resolve_macos_app)}"
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

# The sidecar reads its settings — and with them sessions.json — from whatever
# STTSHKA_ENV_FILE points at. Launched bare it falls back to a path inside the
# bundle, so the interface checks below used to run against an empty app: 94 text
# pairs instead of ~790, and the document screen had no document to measure. The
# packaged app points this at the user's own file, and so does verify.sh — that
# is the state actually worth auditing. On a machine with no such file the
# checks fall back to seeding a session of their own.
USER_ENV="$HOME/Library/Application Support/sttshka-desktop/.env"
if [ -f "$USER_ENV" ]; then
  note "данные приложения: $USER_ENV"
  STTSHKA_ENV_FILE="$USER_ENV"
  export STTSHKA_ENV_FILE
fi

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

# The rule layer is applied through fill_gaps: it only contributes where the NER
# model left a hole. Check the identifiers that the model handles worst on
# dictated text, which is exactly where the rules have to take over.
STRUCT="$(curl -sS -m 120 -X POST -H 'Content-Type: application/json' \
  -d '{"text":"ИНН 100000000074, карта 4276380012345679, СНИЛС 112-334-556 78, IP 192.168.0.1, серия 4508 номер 123456."}' \
  "http://127.0.0.1:$PORT/api/mask" 2>/dev/null)"
# Only masked_text is checked for leftovers. entity_map is supposed to hold the
# originals -- that is what makes the unmasking step work -- so grepping the
# whole response flagged every identifier that masking had correctly replaced.
MASKED="$(printf '%s' "$STRUCT" | /usr/bin/python3 -c 'import json,sys; print(json.load(sys.stdin).get("masked_text",""))' 2>/dev/null)"
LEAKED="$(printf '%s' "$MASKED" | /usr/bin/python3 -c '
import re, sys
text = sys.stdin.read()
wanted = ["100000000074", "4276380012345679", "112-334-556", "192.168.0.1", "4508", "123456"]
print(",".join(v for v in wanted if v in text))' 2>/dev/null)"
MISSING=""
for token in INN CARD SNILS IP PASSPORT; do
  case "$MASKED" in *"[$token"*) ;; *) MISSING="$MISSING $token" ;; esac
done
if [ -z "$LEAKED" ] && [ -z "$MISSING" ]; then
  ok "ИНН, карта, СНИЛС, IP и паспорт замаскированы полностью"
else
  [ -n "$MISSING" ] && bad "не замаскированы:$MISSING"
  [ -n "$LEAKED" ] && bad "в замаскированном тексте остались:$LEAKED"
  note "маскированный текст: $MASKED"
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

# ------------------------------------------------- интерфейс: контраст и вид
# The sidecar is still up here, which is the point: contrast and layout can
# only be judged against a real render, and every check above it is about the
# API. This is the only part that would have caught the dark-theme preset
# sitting unreadable, or the primary button wearing the library's indigo.
section "Интерфейс"
if [ -x "$EXE" ] && [ -f "$ROOT/benchmarks/ui_audit.py" ]; then
  AUDIT_OUT="$(python3 "$ROOT/benchmarks/ui_audit.py" "$PORT" 2>&1)"
  AUDIT_RC=$?
  echo "$AUDIT_OUT" | sed 's/^/  /'
  if [ "$AUDIT_RC" -eq 0 ]; then
    ok "контраст, ширины, зум и печать в порядке"
  else
    bad "аудит интерфейса: $AUDIT_RC провалов (подробности выше)"
  fi
else
  note "аудит интерфейса пропущен: нет $ROOT/benchmarks/ui_audit.py"
fi

# Сворачивание разделов. Отдельная проверка, а не часть аудита: аудит смотрит
# контраст и геометрию у экранов в покое, а здесь нужно свернуть и развернуть
# раздел настоящим кликом и сверить надпись на кнопке с тем, что на экране.
# Раньше кнопка считала ключи в объекте, а не значения, и после одного цикла
# «свернуть-развернуть» врала, что всё свёрнуто.
if [ -x "$EXE" ] && [ -f "$ROOT/benchmarks/check_fold_button.py" ]; then
  FOLD_OUT="$(python3 "$ROOT/benchmarks/check_fold_button.py" "http://127.0.0.1:$PORT" verify 2>&1)"
  FOLD_RC=$?
  echo "$FOLD_OUT" | sed 's/^/  /'
  if [ "$FOLD_RC" -eq 0 ]; then
    ok "разделы сворачиваются, надпись совпадает с состоянием"
  else
    bad "сворачивание разделов: надпись на кнопке разошлась с экраном"
  fi
else
  note "проверка сворачивания пропущена: нет $ROOT/benchmarks/check_fold_button.py"
fi

# Поиск по расшифровке. Отдельная проверка, потому что сворачивание раздела
# размонтирует всё, что внутри него, — поиск когда-то жил там и исчезал вместе
# с текстом, который искал. Здесь: свернуть расшифровку и искать в свёрнутом виде.
if [ -x "$EXE" ] && [ -f "$ROOT/benchmarks/check_search_reachable.py" ]; then
  SEEK_OUT="$(python3 "$ROOT/benchmarks/check_search_reachable.py" "http://127.0.0.1:$PORT" 2>&1)"
  SEEK_RC=$?
  echo "$SEEK_OUT" | sed 's/^/  /'
  if [ "$SEEK_RC" -eq 0 ]; then
    ok "поиск переживает сворачивание и находит при свёрнутом разделе"
  else
    bad "поиск по расшифровке стал недоступен или не находит"
  fi
else
  note "проверка поиска пропущена: нет $ROOT/benchmarks/check_search_reachable.py"
fi

# Панель с поиском закреплена под шапкой. Sticky ломается тихо: переполнение
# у предка, слишком большой top или margin вместо отступа — и панель выглядит
# правильно наверху страницы и не закрепляется вовсе. Прокручиваем и меряем.
if [ -x "$EXE" ] && [ -f "$ROOT/benchmarks/check_toolbar_pinned.py" ]; then
  PIN_OUT="$(python3 "$ROOT/benchmarks/check_toolbar_pinned.py" "http://127.0.0.1:$PORT" 2>&1)"
  PIN_RC=$?
  echo "$PIN_OUT" | sed 's/^/  /'
  if [ "$PIN_RC" -eq 0 ]; then
    ok "панель с поиском закреплена под шапкой"
  else
    bad "панель с поиском не закрепляется при прокрутке"
  fi
else
  note "проверка закрепления пропущена: нет $ROOT/benchmarks/check_toolbar_pinned.py"
fi

# Одноразовые поля разной высоты. Отдельная проверка, потому что контраст и
# геометрия её не видят: поле на 30 px рядом с полем на 38 px проходит обе, но
# глазом это панель, собранная из разных деталей.
if [ -x "$EXE" ] && [ -f "$ROOT/benchmarks/check_controls.py" ]; then
  CTRL_OUT="$(python3 "$ROOT/benchmarks/check_controls.py" "$PORT" 2>&1)"
  CTRL_RC=$?
  echo "$CTRL_OUT" | grep -E '^(ПРОВАЛ|Поля одного вида)' | sed 's/^/  /'
  if [ "$CTRL_RC" -eq 0 ]; then
    ok "поля ввода одного вида"
  else
    bad "поля ввода разной высоты или с разным углом"
  fi
else
  note "проверка полей пропущена: нет $ROOT/benchmarks/check_controls.py"
fi

kill "$SRV" 2>/dev/null

section "Итог"
echo "  $PASS проверок прошло, $FAIL ошибок."
if [ "$FAIL" -gt 0 ]; then
  echo "  Лог sidecar: $LOG"
  exit 1
fi
echo "  Всё в порядке. Приложение готово к использованию."
