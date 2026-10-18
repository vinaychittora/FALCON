#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
skip_setup=false
desktop=false
enable_service=false
for argument in "$@"; do
  case "$argument" in
    --skip-setup) skip_setup=true ;;
    --desktop) desktop=true ;;
    --enable-service) enable_service=true ;;
    *) echo "Usage: bash scripts/install.sh [--skip-setup] [--desktop] [--enable-service]"; exit 2 ;;
  esac
done
if [[ "$(uname -s)" != Linux || "$(uname -m)" != x86_64 ]]; then
  echo "The locked installer supports Linux x86-64. See docs/INSTALL.md for Jetson status."
  exit 1
fi
if ! "$skip_setup"; then
  if curl -fsS --max-time 2 http://127.0.0.1:8000/api/health >/dev/null 2>&1; then
    echo "A server is running on port 8000. Stop it before updating dependencies, or use --skip-setup to build only."
    exit 1
  fi
  bash scripts/bootstrap.sh
fi
source scripts/env.sh
if [[ ! -x .venv/bin/python || ! -d frontend/node_modules ]]; then
  echo "Dependencies are missing. Run make setup first."
  exit 1
fi
npm --prefix frontend run build
if "$desktop"; then
  python - <<'PY'
import os
from pathlib import Path
root = Path.cwd()
def desktop_quote(text):
    if '\n' in text or '\r' in text:
        raise ValueError('Installation paths cannot contain line breaks')
    return '"' + text.replace('\\', '\\\\').replace('"', '\\"').replace('$', '\\$').replace('`', '\\`').replace('%', '%%') + '"'
destination = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share')) / 'applications'
destination.mkdir(parents=True, exist_ok=True)
entry = destination / 'falcon.desktop'
entry.write_text('[Desktop Entry]\nType=Application\nName=FALCON\nComment=Wildlife observation\n'
                 + 'Exec=bash ' + desktop_quote(str(root / 'scripts/serve.sh')) + ' open\n'
                 + 'Icon=' + str(root / 'frontend/public/icons/falcon-192.png') + '\n'
                 + 'Terminal=false\nCategories=Science;Education;\n')
entry.chmod(0o644)
print('FALCON added to your application menu.')
PY
fi
if "$enable_service"; then
  python scripts/systemd_service.py install --enable
fi
printf '\nInstalled. Run make taxa once, then make start. Open http://127.0.0.1:8000\n'
printf 'Existing recordings, settings, model caches and running services were left in place.\n'
