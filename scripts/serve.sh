#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/env.sh"
cd "$WW_ROOT"
exec python scripts/server.py "${@:-start}"
