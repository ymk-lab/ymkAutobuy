#!/usr/bin/env bash
# Start Structure Gate paper UI/API (uvicorn). Requires OpenD secrets + port.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"
VPS="$(cd "$HERE/.." && pwd)"
LOCAL="${QRESEARCH_VPS_SECRETS:-$VPS/secrets/local}"

bash "$HERE/require-secrets.sh"

cd "$ROOT"
if [[ -f "$ROOT/.venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source "$ROOT/.venv/bin/activate"
fi

if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi
if [[ -f "${LOCAL}/app.env" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${LOCAL}/app.env"
  set +a
fi

HOST="${QRESEARCH_UI_HOST:-0.0.0.0}"
PORT="${QRESEARCH_UI_PORT:-8787}"
OPEND_HOST="${FUTU_OPEND_HOST:-127.0.0.1}"
OPEND_PORT="${FUTU_OPEND_PORT:-11111}"

bash "$HERE/wait-opend.sh" "$OPEND_HOST" "$OPEND_PORT" 30

export PYTHONPATH="${ROOT}/src${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONUNBUFFERED=1
export FUTU_TRD_ENV="${FUTU_TRD_ENV:-SIMULATE}"
export QRESEARCH_FUTU_ALLOW_LIVE="${QRESEARCH_FUTU_ALLOW_LIVE:-0}"

exec python3 -m uvicorn qresearch.web.paper_app:app --host "$HOST" --port "$PORT"
