#!/bin/bash
# Start the API for development.
#
# The interpreter is named explicitly rather than relying on `uvicorn` from PATH. A bare
# `uvicorn` resolves to whatever is first on PATH, which on this machine is a
# `~/.local/bin/uvicorn` whose shebang points at a system Python with none of this project's
# dependencies - so the server dies with `ModuleNotFoundError: No module named 'uvicorn'`
# while a working copy sits in `.venv`. Naming the venv makes the launch independent of PATH.
set -euo pipefail

cd "$(dirname "$0")"

PORT="${PORT:-8000}"

if [ -x .venv/bin/python ]; then
  PYTHON=.venv/bin/python
else
  # No venv: fall back to whatever `python3` is, and let the import error be the message.
  PYTHON=python3
fi

exec "$PYTHON" -m uvicorn backend.api.main:get_app \
  --factory \
  --reload \
  --reload-dir backend \
  --reload-dir context \
  --port "$PORT"
