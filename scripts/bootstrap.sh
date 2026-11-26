#!/usr/bin/env bash
# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ "$(uname -s)" != Linux || "$(uname -m)" != x86_64 ]]; then
  echo "This locked runtime supports Linux x86-64. See docs/INSTALL.md for Jetson status."
  exit 1
fi
export PATH="$HOME/.local/bin:$PATH"
if ! command -v uv >/dev/null; then
  mkdir -p .tools
  curl -LsSf https://astral.sh/uv/0.13.1/install.sh -o .tools/install-uv.sh
  sh .tools/install-uv.sh
fi
uv python install 3.11
uv run --no-project --python 3.11 python scripts/install_tools.py
source scripts/env.sh
uv sync --project backend --locked
UV_PROJECT_ENVIRONMENT="$WW_ROOT/.birdnet-venv" uv sync --project birdnet --locked
python scripts/link_birdnet_cache.py
(cd frontend && npm ci --no-audit --no-fund)
mkdir -p data/{samples,logs,cache,taxa,temp,jobs}
printf 'Setup complete. Run make dev inside Ubuntu.\n'
