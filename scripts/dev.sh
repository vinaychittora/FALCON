#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/env.sh"
cd "$WW_ROOT"
setsid uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers &
backend=$!
frontend=""
cleanup() {
  kill -- -"$backend" ${frontend:+-"$frontend"} 2>/dev/null || true
  wait || true
}
trap cleanup EXIT INT TERM
for attempt in {1..60}; do
  kill -0 "$backend" 2>/dev/null || { echo "Backend failed to start"; exit 1; }
  if curl -fsS http://127.0.0.1:8000/api/health >/dev/null 2>&1; then break; fi
  if [[ "$attempt" == 60 ]]; then echo "Backend did not become ready within 30 seconds"; exit 1; fi
  sleep 0.5
done
setsid npm --prefix frontend run dev &
frontend=$!
wait -n "$backend" "$frontend"
