#!/usr/bin/env bash
# Local setup: venv + futu/web deps + .env
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

PY="${PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "需要 python3（建議 3.10+）"
  exit 1
fi

echo "==> 建立 .venv"
"$PY" -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install -U pip wheel
python -m pip install -e ".[futu,web,dev]"

if [[ ! -f .env ]]; then
  cp .env.example .env
  chmod 600 .env
  echo "==> 已建立 .env（來自 .env.example）"
else
  echo "==> 保留既有 .env"
fi

# Ensure Futu keys exist
python - <<'PY'
from pathlib import Path
p = Path(".env")
text = p.read_text() if p.is_file() else ""
need = {
    "FUTU_OPEND_HOST": "127.0.0.1",
    "FUTU_OPEND_PORT": "11111",
    "FUTU_TRD_ENV": "SIMULATE",
    "QRESEARCH_FUTU_ALLOW_LIVE": "0",
    "QRESEARCH_SG_PAPER_ONLY": "1",
    "QRESEARCH_SG_PAPER_SUBMIT": "0",
    "QRESEARCH_SG_BOOK": "V11",
    "QRESEARCH_SLEEVE_USD": "50000",
    "QRESEARCH_UI_HOST": "127.0.0.1",
    "QRESEARCH_UI_PORT": "8787",
}
lines = text.splitlines()
have = {ln.split("=", 1)[0] for ln in lines if "=" in ln and not ln.strip().startswith("#")}
extra = [f"{k}={v}" for k, v in need.items() if k not in have]
if extra:
    p.write_text((text.rstrip() + "\n" if text.strip() else "") + "\n".join(extra) + "\n")
    print("==> 補齊 .env 鍵：", ", ".join(k.split("=")[0] for k in extra))
PY

mkdir -p examples/data/structure_gate_v11_paper/logs

echo
echo "完成。下一步："
echo "  1) 確認 OpenD 已登入（11111）"
echo "  2) source .venv/bin/activate"
echo "  3) PYTHONPATH=src python -c \"from qresearch.brokers.futu import has_futu_opend; print(has_futu_opend())\""
echo "  4) bash deploy/local/run-ui.sh"
echo "詳見 deploy/local/README.md"
