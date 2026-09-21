#!/usr/bin/env bash
# Build secrets/local/FutuOpenD.xml from opend.env (chmod 600).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VPS="$(cd "$HERE/.." && pwd)"
LOCAL="${QRESEARCH_VPS_SECRETS:-$VPS/secrets/local}"
OPEND_ENV="${LOCAL}/opend.env"
OUT="${LOCAL}/FutuOpenD.xml"

mkdir -p "$LOCAL"
chmod 700 "$LOCAL"
[[ -f "$OPEND_ENV" ]] || {
  echo "missing $OPEND_ENV — copy deploy/vps/secrets/opend.env.example" >&2
  exit 1
}
chmod 600 "$OPEND_ENV" || true

# shellcheck disable=SC1090
set -a; source "$OPEND_ENV"; set +a

ACCOUNT="${FUTU_LOGIN_ACCOUNT:-}"
IP="${FUTU_OPEND_IP:-127.0.0.1}"
PORT="${FUTU_OPEND_PORT:-11111}"
MD5="${FUTU_LOGIN_PWD_MD5:-}"

if [[ -z "$ACCOUNT" ]]; then
  echo "FUTU_LOGIN_ACCOUNT required" >&2
  exit 1
fi

if [[ -z "$MD5" && -n "${FUTU_LOGIN_PWD:-}" ]]; then
  MD5="$(python3 -c "import hashlib,os; print(hashlib.md5(os.environ['FUTU_LOGIN_PWD'].encode()).hexdigest())")"
  echo "Computed FUTU_LOGIN_PWD_MD5 from FUTU_LOGIN_PWD (remove plaintext from opend.env after this)"
fi

if [[ -z "$MD5" || ! "$MD5" =~ ^[0-9a-fA-F]{32}$ ]]; then
  echo "Need valid FUTU_LOGIN_PWD_MD5 or FUTU_LOGIN_PWD" >&2
  exit 1
fi

RSA_LINE=""
if [[ -n "${FUTU_RSA_PRIVATE_KEY:-}" ]]; then
  RSA_LINE="  <rsa_private_key>${FUTU_RSA_PRIVATE_KEY}</rsa_private_key>"
fi

umask 077
cat >"$OUT" <<XML
<?xml version="1.0" encoding="UTF-8"?>
<futu_opend>
  <ip>${IP}</ip>
  <api_port>${PORT}</api_port>
  <login_account>${ACCOUNT}</login_account>
  <login_pwd_md5>${MD5}</login_pwd_md5>
  <log_level>info</log_level>
${RSA_LINE}
</futu_opend>
XML
chmod 600 "$OUT"

# Persist MD5 into opend.env if we just computed it; strip plaintext pwd line.
if [[ -n "${FUTU_LOGIN_PWD:-}" ]]; then
  python3 - <<'PY' "$OPEND_ENV" "$MD5"
import pathlib, re, sys
path = pathlib.Path(sys.argv[1])
md5 = sys.argv[2]
text = path.read_text(encoding="utf-8")
lines = []
have_md5 = False
for ln in text.splitlines():
    if ln.startswith("FUTU_LOGIN_PWD=") or ln.startswith("# FUTU_LOGIN_PWD="):
        continue
    if ln.startswith("FUTU_LOGIN_PWD_MD5="):
        lines.append(f"FUTU_LOGIN_PWD_MD5={md5}")
        have_md5 = True
        continue
    lines.append(ln)
if not have_md5:
    lines.append(f"FUTU_LOGIN_PWD_MD5={md5}")
path.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("Updated opend.env: wrote MD5, removed FUTU_LOGIN_PWD")
PY
  chmod 600 "$OPEND_ENV"
fi

echo "Wrote $OUT (mode 600) ip=${IP} port=${PORT}"
