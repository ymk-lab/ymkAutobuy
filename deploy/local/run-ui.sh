#!/usr/bin/env bash
# Start Structure Gate v11 UI against local Futu OpenD.
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

export PYTHONPATH="${ROOT}/src${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONUNBUFFERED=1
HOST="${QRESEARCH_UI_HOST:-127.0.0.1}"
PORT="${QRESEARCH_UI_PORT:-8787}"

echo "UI → http://${HOST}:${PORT}  (OpenD ${FUTU_OPEND_HOST:-127.0.0.1}:${FUTU_OPEND_PORT:-11111})"
exec python -m uvicorn qresearch.web.paper_app:app --host "$HOST" --port "$PORT"
