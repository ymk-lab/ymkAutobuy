#!/usr/bin/env bash
# Exit non-zero if VPS secrets are missing / incomplete.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VPS="$(cd "$HERE/.." && pwd)"
LOCAL="${QRESEARCH_VPS_SECRETS:-$VPS/secrets/local}"
OPEND_ENV="${LOCAL}/opend.env"
APP_ENV="${LOCAL}/app.env"
XML="${LOCAL}/FutuOpenD.xml"

fail() { echo "ERROR: $*" >&2; exit 1; }

[[ -d "$LOCAL" ]] || fail "missing $LOCAL — copy examples from deploy/vps/secrets/*.example"
[[ -f "$OPEND_ENV" ]] || fail "missing $OPEND_ENV (from opend.env.example)"
[[ -f "$APP_ENV" ]] || fail "missing $APP_ENV (from app.env.example)"

# shellcheck disable=SC1090
set -a; source "$OPEND_ENV"; set +a

[[ -n "${FUTU_LOGIN_ACCOUNT:-}" ]] || fail "FUTU_LOGIN_ACCOUNT empty in opend.env"
if [[ -z "${FUTU_LOGIN_PWD_MD5:-}" && -z "${FUTU_LOGIN_PWD:-}" ]]; then
  fail "set FUTU_LOGIN_PWD_MD5 (preferred) or FUTU_LOGIN_PWD in opend.env"
fi
if [[ -n "${FUTU_LOGIN_PWD_MD5:-}" && ! "${FUTU_LOGIN_PWD_MD5}" =~ ^[0-9a-fA-F]{32}$ ]]; then
  fail "FUTU_LOGIN_PWD_MD5 must be 32 hex chars"
fi

BIN="${FUTU_OPEND_BIN:-/opt/futuopend/FutuOpenD}"
[[ -x "$BIN" ]] || fail "OpenD binary not executable: $BIN (download Linux OpenD first)"

[[ -f "$XML" ]] || fail "missing $XML — run: bash deploy/vps/bin/render-opend-xml.sh"

perm="$(stat -c '%a' "$OPEND_ENV" 2>/dev/null || stat -f '%Lp' "$OPEND_ENV")"
if [[ "$perm" != "600" && "$perm" != "400" ]]; then
  echo "WARN: $OPEND_ENV mode=$perm (recommend chmod 600)" >&2
fi

echo "OK secrets local=$LOCAL account=${FUTU_LOGIN_ACCOUNT:0:3}*** bin=$BIN"
