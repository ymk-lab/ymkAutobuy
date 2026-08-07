#!/usr/bin/env bash
# Wrapper for Emerging RS G1 daily paper job.
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

export PYTHONUNBUFFERED=1
MODE="${1:-once}"
LOG_DIR="${QRESEARCH_PAPER_OUT:-$ROOT/examples/data/emerging_rs_g1_paper}/logs"
mkdir -p "$LOG_DIR"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG_FILE="$LOG_DIR/cron_${STAMP}.log"

{
  echo "=== qresearch paper job mode=$MODE utc=$STAMP ==="
  python3 "$ROOT/examples/run_emerging_rs_g1_paper_daily.py" "$MODE"
} 2>&1 | tee -a "$LOG_FILE"
