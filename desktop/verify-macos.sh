#!/usr/bin/env bash
# macOS entry point. The shared implementation lives in verify.sh and resolves
# bundle/model paths from the platform; this wrapper only pins the platform so a
# macOS build is checked against macOS expectations.
set -euo pipefail
exec "$(dirname "$0")/verify.sh" "$@"
