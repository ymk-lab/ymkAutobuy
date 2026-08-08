#!/usr/bin/env bash
# Build a tarball for copying this project to a local machine.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_DIR="${1:-$ROOT/deploy/local/dist}"
mkdir -p "$OUT_DIR"
NAME="qresearch-local-${STAMP}"
STAGE="$(mktemp -d)"
DEST="$STAGE/$NAME"
mkdir -p "$DEST"

rsync -a \
  --exclude '.venv' \
  --exclude '.git' \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  --exclude '.pytest_cache' \
  --exclude '.agents' \
  --exclude 'deploy/local/dist' \
  --exclude 'examples/data/qqq100b' \
  --exclude 'examples/data/qqq100b_b' \
  --exclude 'examples/data/structure_gate_v8_vs_*' \
  --exclude 'examples/data/structure_gate_vol_reentry_ab' \
  --exclude 'examples/data/structure_gate_v8_paper/backtest*' \
  --exclude 'examples/data/structure_gate_v8_paper/walkforward*' \
  --exclude 'examples/data/*/logs' \
  ./ "$DEST/"

# Never ship secrets
rm -f "$DEST/.env"

ARCHIVE="$OUT_DIR/${NAME}.tar.gz"
tar -C "$STAGE" -czf "$ARCHIVE" "$NAME"
rm -rf "$STAGE"
ls -lh "$ARCHIVE"
echo "ARCHIVE=$ARCHIVE"
