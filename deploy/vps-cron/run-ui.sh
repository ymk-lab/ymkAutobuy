#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi
if [[ -f "$ROOT/.venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source "$ROOT/.venv/bin/activate"
fi
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
export QRESEARCH_UI_HOST="${QRESEARCH_UI_HOST:-0.0.0.0}"
export QRESEARCH_UI_PORT="${QRESEARCH_UI_PORT:-8787}"
exec python -m uvicorn qresearch.web.paper_app:app --host "$QRESEARCH_UI_HOST" --port "$QRESEARCH_UI_PORT"
