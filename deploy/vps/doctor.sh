#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
LOCAL="${QRESEARCH_VPS_SECRETS:-$HERE/secrets/local}"

echo "== repo $ROOT"
echo "== secrets $LOCAL"
bash "$HERE/bin/require-secrets.sh" || true

if [[ -f "$ROOT/.venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source "$ROOT/.venv/bin/activate"
fi
export PYTHONPATH="$ROOT/src"
python3 - <<'PY'
from qresearch.brokers.futu import has_futu_opend
print("has_futu_opend=", has_futu_opend())
PY

echo "== systemd (if installed)"
systemctl is-active qresearch-opend.service 2>/dev/null || echo "opend: not installed/active"
systemctl is-active qresearch-api.service 2>/dev/null || echo "api: not installed/active"

echo "== ports"
ss -ltn 2>/dev/null | grep -E ':11111|:8787' || netstat -ltn 2>/dev/null | grep -E ':11111|:8787' || true
