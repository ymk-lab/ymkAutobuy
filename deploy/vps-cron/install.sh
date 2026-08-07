#!/usr/bin/env bash
# Bootstrap qresearch on a small Ubuntu/Debian VPS for cron paper trading.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

echo "==> repo: $ROOT"

if ! command -v python3 >/dev/null; then
  echo "python3 required"; exit 1
fi

sudo apt-get update -y
sudo apt-get install -y python3-venv python3-pip git

python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -U pip
pip install -e ".[longbridge]"

chmod +x deploy/vps-cron/run.sh deploy/vps-cron/install.sh

if [[ ! -f .env ]]; then
  cp .env.example .env
  chmod 600 .env
  echo "Created .env from .env.example — fill LONGBRIDGE_* keys before enabling SUBMIT=1"
else
  chmod 600 .env || true
fi

mkdir -p examples/data/emerging_rs_g1_paper/{cache_ohlcv,logs}

echo
echo "==> Dry plan (no orders):"
QRESEARCH_LB_SUBMIT=0 QRESEARCH_REFRESH_CACHE=0 \
  python3 examples/run_emerging_rs_g1_paper_daily.py once || true

echo
echo "==> Install crontab entry? (prints example; edit path/user as needed)"
echo "    crontab -e"
echo "    # After US cash close (Mon-Fri 16:30 America/New_York):"
echo "    CRON_TZ=America/New_York"
echo "    30 16 * * 1-5 $ROOT/deploy/vps-cron/run.sh once"
echo
echo "Keep QRESEARCH_LB_SUBMIT=0 until you verify latest_signal.json."
echo "Then set QRESEARCH_LB_SUBMIT=1 in .env for Longbridge paper orders."
echo "Optional sleeve cap: QRESEARCH_SLEEVE_USD=50000"
echo "Done."
