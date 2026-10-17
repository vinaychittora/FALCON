#!/usr/bin/env bash
WW_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="$WW_ROOT/.tools/node/bin:$WW_ROOT/.tools/ffmpeg/bin:$WW_ROOT/.venv/bin:$HOME/.local/bin:$PATH"
export PYTHONPATH="$WW_ROOT/backend${PYTHONPATH:+:$PYTHONPATH}"
export UV_PROJECT_ENVIRONMENT="$WW_ROOT/.venv"
export HF_HOME="$WW_ROOT/models/huggingface"
export TORCH_HOME="$WW_ROOT/models/torch"
export OMP_NUM_THREADS=4
