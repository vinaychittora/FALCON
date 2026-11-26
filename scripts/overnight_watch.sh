#!/usr/bin/env bash
# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
# Light watch log for a later summary. Checks every minute and writes a line every
# 15 minutes to data/logs/watch-<date>.log (UTC date). Problems are written as
# WARNING lines (and to stdout) and the watch keeps going; a warning repeats at most
# every 30 minutes while the problem lasts, and a RECOVERED line marks its end.
# Warns when FALCON stops answering, the stream is down for more than 5 minutes,
# no sound window is analysed for 10 minutes, the sound windows per 15 minutes fall
# below half the normal ~100, or the node throttles. Read-only: never restarts anything.
#   bash scripts/overnight_watch.sh [until-UTC, default tomorrow 03:30]
set -u
cd "$(dirname "$0")/.."
UNTIL=$(date -u -d "${1:-tomorrow 03:30}" +%s)
mkdir -p data/diagnostics
log() { echo "$(date -u +%FT%TZ) $*" | tee -a "data/diagnostics/watch-$(date -u +%Y%m%d).log"; }
declare -A warned_at=()
warn() {  # warn <key> <message>
  local now; now=$(date +%s)
  if [ $(( now - ${warned_at[$1]:-0} )) -ge 1800 ]; then log "WARNING $2"; warned_at[$1]=$now; fi
}
clear_warning() {  # clear_warning <key> <message>
  if [ -n "${warned_at[$1]:-}" ]; then log "RECOVERED $2"; unset "warned_at[$1]"; fi
}
summary() {
  python3 - <<'EOF'
import json, sqlite3, shutil, urllib.request
def get(path):
    with urllib.request.urlopen("http://127.0.0.1:8000" + path, timeout=10) as r:
        return json.load(r)
node = (get("/api/nodes")["nodes"] or [{}])[0].get("status") or {}
live = get("/api/live/state")
m = live.get("metrics", {})
system = node.get("system", {})
thermal = node.get("thermal") or {}
db = sqlite3.connect("file:data/falcon.sqlite3?mode=ro", uri=True)
last = db.execute("SELECT MAX(recorded_at) FROM observations").fetchone()[0]
free = shutil.disk_usage("data").free / 1e9
power = system.get("power", {})
print(f"cpu {system.get('cpu_temperature_c')}C heat {thermal.get('state', '-')} "
      f"throttled {power.get('throttled_now', '-')} stream {live.get('status')} "
      f"sound windows {m.get('audio_chunks_analyzed')} level {m.get('audio_level_dbfs')} dBFS "
      f"shortfalls {m.get('audio_sample_shortfalls')} last obs {last} free {free:.0f}GB")
EOF
}
fail=0; down_since=0; tick=0; last_chunks=""; sound_since=$(date +%s); quarter_start=""
log "watch started (until $(date -u -d "@$UNTIL" +%FT%TZ))"
while [ "$(date -u +%s)" -lt "$UNTIL" ]; do
  state=$(curl -s -m 10 127.0.0.1:8000/api/live/state || true)
  if [ -z "$state" ]; then
    fail=$((fail + 1))
    [ $fail -ge 3 ] && warn falcon "FALCON not answering for $fail min"
  else
    [ $fail -ge 3 ] && clear_warning falcon "FALCON answering again"
    fail=0
    if echo "$state" | grep -q '"status":"live"'; then
      [ $down_since -ne 0 ] && clear_warning stream "stream live again"
      down_since=0
    elif [ $down_since -eq 0 ]; then down_since=$(date +%s)
    elif [ $(( $(date +%s) - down_since )) -gt 300 ]; then
      warn stream "stream down >5 min: $(echo "$state" | grep -oE '"status":"[^"]*"' | head -1)"
    fi
    chunks=$(echo "$state" | python3 -c 'import json,sys; print(int(json.load(sys.stdin)["metrics"].get("audio_chunks_analyzed") or 0))' 2>/dev/null || echo 0)
    if [ "$chunks" != "$last_chunks" ]; then
      [ -n "$last_chunks" ] && [ $(( $(date +%s) - sound_since )) -gt 600 ] && clear_warning sound "sound analysis running again"
      last_chunks=$chunks; sound_since=$(date +%s)
    elif [ $(( $(date +%s) - sound_since )) -gt 600 ]; then
      warn sound "no sound window analysed for $(( ($(date +%s) - sound_since) / 60 )) min (stuck at $chunks)"
    fi
    throttled=$(curl -s -m 10 127.0.0.1:8000/api/nodes | python3 -c 'import json,sys; s=(json.load(sys.stdin)["nodes"][0].get("status") or {}).get("system",{}).get("power",{}); print(int(bool(s.get("throttled_now") or s.get("under_voltage_now"))))' 2>/dev/null || echo 0)
    [ "$throttled" = 1 ] && warn throttle "node throttling or under-voltage"
  fi
  if [ $((tick % 15)) -eq 0 ]; then
    # Sound windows in the last 15 minutes: ~100 is normal (one per 9 s).
    if [ -n "$quarter_start" ] && [ -n "$last_chunks" ]; then
      per_quarter=$(( last_chunks - quarter_start ))
      if [ $per_quarter -ge 0 ] && [ $per_quarter -lt 50 ]; then warn rate "only $per_quarter sound windows in 15 min (normal ~100)"
      elif [ $per_quarter -ge 50 ]; then clear_warning rate "sound windows back to $per_quarter per 15 min"; fi
    fi
    quarter_start=${last_chunks:-0}
    log "$(summary 2>&1 | tail -1)"
  fi
  tick=$((tick + 1))
  sleep 60
done
log "watch finished"
