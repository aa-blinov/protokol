#!/usr/bin/env bash
# macOS entry point. The shared implementation lives in build.sh and picks its
# targets from the platform; this wrapper only pins the target and refuses to
# run elsewhere, since a .app cannot be built off a Mac.
set -euo pipefail
exec "$(dirname "$0")/build.sh" --mac "$@"
