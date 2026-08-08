#!/usr/bin/env bash
# Structure Gate v11 daily job → Futu OpenD paper (SIMULATE).
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
elif [[ -f /opt/qresearch/.venv/bin/activate ]]; then
  # shellcheck disable=SC1091
  source /opt/qresearch/.venv/bin/activate
fi

export PYTHONUNBUFFERED=1
export QRESEARCH_SG_PAPER_ONLY="${QRESEARCH_SG_PAPER_ONLY:-1}"
export FUTU_TRD_ENV="${FUTU_TRD_ENV:-SIMULATE}"
export QRESEARCH_SG_PAPER_OUT="${QRESEARCH_SG_PAPER_OUT:-$ROOT/examples/data/structure_gate_v11_paper}"

MODE="${1:-once}"
LOG_DIR="${QRESEARCH_SG_PAPER_OUT}/logs"
mkdir -p "$LOG_DIR"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG_FILE="$LOG_DIR/cron_${STAMP}.log"

{
  echo "=== qresearch SG v11 futu mode=$MODE submit=${QRESEARCH_SG_PAPER_SUBMIT:-0} utc=$STAMP ==="
  python3 "$ROOT/examples/run_structure_gate_v11_paper_daily.py" "$MODE"
} 2>&1 | tee -a "$LOG_FILE"
