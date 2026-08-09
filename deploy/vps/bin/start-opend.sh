#!/usr/bin/env bash
# Start Linux command-line OpenD from its install dir (needs AppData.dat + libs).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VPS="$(cd "$HERE/.." && pwd)"
LOCAL="${QRESEARCH_VPS_SECRETS:-$VPS/secrets/local}"

if [[ -f "${LOCAL}/opend.env" ]]; then
  # shellcheck disable=SC1090
  set -a; source "${LOCAL}/opend.env"; set +a
fi

BIN="${FUTU_OPEND_BIN:-/opt/futuopend/FutuOpenD}"
DIR="$(cd "$(dirname "$BIN")" && pwd)"
# Prefer official XML next to the binary (patched with login). Fallback to secrets XML.
XML="${FUTU_OPEND_XML:-}"
if [[ -z "$XML" ]]; then
  if [[ -f "${DIR}/FutuOpenD.xml" ]]; then
    XML="${DIR}/FutuOpenD.xml"
  else
    XML="${LOCAL}/FutuOpenD.xml"
  fi
fi

LOG_DIR="${QRESEARCH_OPEND_LOG:-/var/log/qresearch}"
mkdir -p "$LOG_DIR" 2>/dev/null || LOG_DIR="${VPS}/logs"
mkdir -p "$LOG_DIR"

[[ -x "$BIN" ]] || { echo "OpenD binary missing: $BIN" >&2; exit 1; }
[[ -f "$XML" ]] || { echo "OpenD XML missing: $XML" >&2; exit 1; }

# Safety: refuse non-loopback listen if we can read ip from xml
if grep -qE '<ip>\s*0\.0\.0\.0\s*</ip>' "$XML"; then
  echo "REFUSE: OpenD xml listens on 0.0.0.0 — use 127.0.0.1" >&2
  exit 1
fi

cd "$DIR"
# Run in foreground for systemd Type=simple
exec "$BIN" -cfg_file="$XML" >>"${LOG_DIR}/opend.out.log" 2>>"${LOG_DIR}/opend.err.log"
