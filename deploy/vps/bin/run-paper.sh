#!/usr/bin/env bash
# Structure Gate v11 paper job. Usage: run-paper.sh signal|once
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"
VPS="$(cd "$HERE/.." && pwd)"
LOCAL="${QRESEARCH_VPS_SECRETS:-$VPS/secrets/local}"
MODE="${1:-signal}"

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

export PYTHONPATH="${ROOT}/src${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONUNBUFFERED=1
export QRESEARCH_SG_PAPER_ONLY="${QRESEARCH_SG_PAPER_ONLY:-1}"
export FUTU_TRD_ENV="${FUTU_TRD_ENV:-SIMULATE}"
export QRESEARCH_SG_PAPER_OUT="${QRESEARCH_SG_PAPER_OUT:-$ROOT/examples/data/structure_gate_v11_paper}"

if [[ "$MODE" == "once" || "$MODE" == "submit" ]]; then
  MODE="once"
  if [[ "${QRESEARCH_SG_PAPER_SUBMIT:-0}" != "1" ]]; then
    echo "WARN: submit mode but QRESEARCH_SG_PAPER_SUBMIT!=1 (dry plan only)" >&2
  fi
fi

LOG_DIR="${QRESEARCH_SG_PAPER_OUT}/logs"
mkdir -p "$LOG_DIR"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG_FILE="$LOG_DIR/vps_${MODE}_${STAMP}.log"

{
  echo "=== vps paper mode=$MODE submit=${QRESEARCH_SG_PAPER_SUBMIT:-0} utc=$STAMP ==="
  bash "$HERE/wait-opend.sh" "${FUTU_OPEND_HOST:-127.0.0.1}" "${FUTU_OPEND_PORT:-11111}" 30
  python3 "$ROOT/examples/run_structure_gate_v11_paper_daily.py" "$MODE"
} 2>&1 | tee -a "$LOG_FILE"
