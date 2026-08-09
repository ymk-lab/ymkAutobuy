#!/usr/bin/env bash
# Start Linux command-line OpenD with generated XML (loopback only).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
bash "$HERE/require-secrets.sh"

VPS="$(cd "$HERE/.." && pwd)"
LOCAL="${QRESEARCH_VPS_SECRETS:-$VPS/secrets/local}"
# shellcheck disable=SC1090
set -a; source "${LOCAL}/opend.env"; set +a

BIN="${FUTU_OPEND_BIN:-/opt/futuopend/FutuOpenD}"
XML="${LOCAL}/FutuOpenD.xml"
LOG_DIR="${QRESEARCH_OPEND_LOG:-/var/log/qresearch}"
mkdir -p "$LOG_DIR" 2>/dev/null || LOG_DIR="${VPS}/logs"
mkdir -p "$LOG_DIR"

IP="${FUTU_OPEND_IP:-127.0.0.1}"
if [[ "$IP" != "127.0.0.1" && "$IP" != "::1" ]]; then
  echo "REFUSE: FUTU_OPEND_IP=$IP — must be 127.0.0.1 on a public VPS" >&2
  exit 1
fi

cd "$(dirname "$BIN")"
# Official CLI: -cfg_file=...
exec "$BIN" -cfg_file="$XML" >>"${LOG_DIR}/opend.out.log" 2>>"${LOG_DIR}/opend.err.log"
