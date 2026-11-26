#!/usr/bin/env bash
# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
WW_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="$WW_ROOT/.tools/node/bin:$WW_ROOT/.tools/ffmpeg/bin:$WW_ROOT/.venv/bin:$HOME/.local/bin:$PATH"
export PYTHONPATH="$WW_ROOT/backend${PYTHONPATH:+:$PYTHONPATH}"
export UV_PROJECT_ENVIRONMENT="$WW_ROOT/.venv"
export HF_HOME="$WW_ROOT/models/huggingface"
export TORCH_HOME="$WW_ROOT/models/torch"
export OMP_NUM_THREADS=4
