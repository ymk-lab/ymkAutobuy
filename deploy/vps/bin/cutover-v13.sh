#!/usr/bin/env bash
# Cut over VPS paper trading from v11 (SPY/QQQ/SMH) → v13 (SPY50/QQQ50).
# Run on the VPS as the app user (or root if that owns /opt/qresearch).
set -euo pipefail

ROOT="${QRESEARCH_ROOT:-/opt/qresearch}"
BRANCH="${QRESEARCH_BRANCH:-cursor/structure-gate-v13-600b}"
LOCAL="${QRESEARCH_VPS_SECRETS:-$ROOT/deploy/vps/secrets/local}"

cd "$ROOT"

echo "==> fetch/checkout $BRANCH"
git fetch origin "$BRANCH"
git checkout "$BRANCH"
git pull --ff-only origin "$BRANCH"

echo "==> ensure paper out dir"
mkdir -p "$ROOT/examples/data/structure_gate_v13_paper/logs"

if [[ -f "$LOCAL/app.env" ]]; then
  echo "==> patch $LOCAL/app.env book → V13"
  if grep -q '^QRESEARCH_SG_BOOK=' "$LOCAL/app.env"; then
    sed -i 's/^QRESEARCH_SG_BOOK=.*/QRESEARCH_SG_BOOK=V13/' "$LOCAL/app.env"
  else
    echo 'QRESEARCH_SG_BOOK=V13' >> "$LOCAL/app.env"
  fi
  if grep -q '^QRESEARCH_SG_PAPER_OUT=' "$LOCAL/app.env"; then
    sed -i "s|^QRESEARCH_SG_PAPER_OUT=.*|QRESEARCH_SG_PAPER_OUT=$ROOT/examples/data/structure_gate_v13_paper|" "$LOCAL/app.env"
  else
    echo "QRESEARCH_SG_PAPER_OUT=$ROOT/examples/data/structure_gate_v13_paper" >> "$LOCAL/app.env"
  fi
fi

if [[ -f "$ROOT/.env" ]]; then
  echo "==> patch $ROOT/.env book → V13"
  if grep -q '^QRESEARCH_SG_BOOK=' "$ROOT/.env"; then
    sed -i 's/^QRESEARCH_SG_BOOK=.*/QRESEARCH_SG_BOOK=V13/' "$ROOT/.env"
  else
    echo 'QRESEARCH_SG_BOOK=V13' >> "$ROOT/.env"
  fi
  if grep -q '^QRESEARCH_SG_PAPER_OUT=' "$ROOT/.env"; then
    sed -i "s|^QRESEARCH_SG_PAPER_OUT=.*|QRESEARCH_SG_PAPER_OUT=$ROOT/examples/data/structure_gate_v13_paper|" "$ROOT/.env"
  else
    echo "QRESEARCH_SG_PAPER_OUT=$ROOT/examples/data/structure_gate_v13_paper" >> "$ROOT/.env"
  fi
fi

echo "==> refresh crontab to v13 log paths"
CRON_TMP="$(mktemp)"
crontab -l 2>/dev/null | sed 's|structure_gate_v11_paper|structure_gate_v13_paper|g' > "$CRON_TMP" || true
if grep -q 'run-paper.sh' "$CRON_TMP"; then
  crontab "$CRON_TMP"
  echo "crontab updated"
else
  echo "WARN: no run-paper.sh in crontab — installing example + systemd timers"
  if [[ -f "$ROOT/deploy/vps/crontab.example" ]]; then
    crontab "$ROOT/deploy/vps/crontab.example" || true
  fi
fi
rm -f "$CRON_TMP"

if [[ "$(id -u)" -eq 0 ]] || command -v sudo >/dev/null 2>&1; then
  echo "==> sync systemd units + enable paper timers"
  sudo QRESEARCH_USER="${QRESEARCH_USER:-${SUDO_USER:-$USER}}" \
    bash "$ROOT/deploy/vps/bin/sync-systemd.sh" || echo "WARN: sync-systemd failed"
fi

echo "==> restart API (pick up new static/UI + defaults)"
if systemctl is-active --quiet qresearch-api 2>/dev/null; then
  sudo systemctl restart qresearch-api
  sudo systemctl --no-pager --full status qresearch-api | head -20
else
  echo "WARN: qresearch-api not active via systemd"
fi

echo "==> smoke: paper signal (plan only)"
bash "$ROOT/deploy/vps/bin/run-paper.sh" signal

echo "==> done. Verify UI http://<VPS>:8787 shows v13 · SPY50/QQQ50"
echo "    Next once/submit will flatten leftover SMH sleeve names into new targets."
