#!/usr/bin/env bash
# Bootstrap Ubuntu/Debian VPS: venv + secrets dirs + systemd units.
# Does NOT download Futu OpenD (place binary yourself) and does NOT write passwords.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VPS="$ROOT/deploy/vps"
LOCAL="$VPS/secrets/local"
REPO_USER="${SUDO_USER:-$USER}"
# Default: run services as the installing login user (simple single-admin VPS).
# Override: QRESEARCH_USER=qresearch ./install.sh
APP_USER="${QRESEARCH_USER:-$REPO_USER}"
INSTALL_SYSTEMD="${INSTALL_SYSTEMD:-1}"

cd "$ROOT"
echo "==> repo: $ROOT"

if [[ "$(uname -m)" != "x86_64" ]]; then
  echo "WARN: arch=$(uname -m) — official Futu OpenD is x86_64; ARM needs emulation." >&2
fi

if command -v apt-get >/dev/null 2>&1; then
  sudo apt-get update -y
  sudo apt-get install -y python3-venv python3-pip git curl ca-certificates netcat-openbsd || \
    sudo apt-get install -y python3-venv python3-pip git curl ca-certificates netcat-traditional || true
fi

if ! id "$APP_USER" >/dev/null 2>&1; then
  echo "Creating system user $APP_USER"
  sudo useradd --system --create-home --shell /usr/sbin/nologin "$APP_USER"
fi

python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -U pip wheel
pip install -e ".[futu,web]"

mkdir -p "$LOCAL" examples/data/structure_gate_v11_paper/logs "$VPS/logs"
chmod 700 "$LOCAL"
chmod +x "$VPS"/bin/*.sh "$VPS/install.sh" "$VPS/doctor.sh"

if [[ ! -f "$LOCAL/opend.env" ]]; then
  cp "$VPS/secrets/opend.env.example" "$LOCAL/opend.env"
  chmod 600 "$LOCAL/opend.env"
  echo "==> created $LOCAL/opend.env — FILL account + password MD5"
fi
if [[ ! -f "$LOCAL/app.env" ]]; then
  cp "$VPS/secrets/app.env.example" "$LOCAL/app.env"
  chmod 600 "$LOCAL/app.env"
  echo "==> created $LOCAL/app.env"
fi

if [[ ! -f "$ROOT/.env" ]]; then
  cp "$ROOT/.env.example" "$ROOT/.env"
  chmod 600 "$ROOT/.env"
fi
# Merge non-secret defaults from app.env into .env keys if missing
python3 - <<'PY' "$ROOT/.env" "$LOCAL/app.env"
from pathlib import Path
import sys
env_path, app_path = Path(sys.argv[1]), Path(sys.argv[2])
have = set()
lines = env_path.read_text().splitlines() if env_path.is_file() else []
for ln in lines:
    if "=" in ln and not ln.strip().startswith("#"):
        have.add(ln.split("=", 1)[0].strip())
extra = []
for ln in app_path.read_text().splitlines():
    s = ln.strip()
    if not s or s.startswith("#") or "=" not in s:
        continue
    k = s.split("=", 1)[0].strip()
    if k not in have:
        extra.append(s)
        have.add(k)
if extra:
    text = env_path.read_text() if env_path.is_file() else ""
    env_path.write_text(text.rstrip() + "\n" + "\n".join(extra) + "\n")
    print("==> merged into .env:", ", ".join(x.split("=", 1)[0] for x in extra))
PY

sudo mkdir -p /opt/futuopend /var/log/qresearch
sudo chown -R "$APP_USER:$APP_USER" /var/log/qresearch /opt/futuopend
# Repo readable by service user; secrets stay mode 600
if [[ "$APP_USER" != "$REPO_USER" ]]; then
  sudo chown -R "$REPO_USER:$APP_USER" "$ROOT" || true
  sudo chmod -R g+rX "$ROOT"
  sudo chown -R "$APP_USER:$APP_USER" "$LOCAL"
fi
sudo chmod 700 "$LOCAL"
sudo chmod 600 "$LOCAL"/* 2>/dev/null || true

# If repo is not already under /opt/qresearch, leave a note (units assume /opt/qresearch)
if [[ "$ROOT" != "/opt/qresearch" ]]; then
  echo "NOTE: systemd units assume /opt/qresearch"
  echo "      clone/move repo there, or edit deploy/vps/systemd/*.service paths"
fi

if [[ "$INSTALL_SYSTEMD" == "1" && -d /etc/systemd/system ]]; then
  # Rewrite WorkingDirectory if needed
  for unit in qresearch-opend.service qresearch-api.service; do
    src="$VPS/systemd/$unit"
    dst="/etc/systemd/system/$unit"
    sed -e "s|/opt/qresearch|$ROOT|g" -e "s|REPLACE_USER|$APP_USER|g" "$src" \
      | sudo tee "$dst" >/dev/null
  done
  sudo systemctl daemon-reload
  echo "==> systemd units installed (not started until secrets + OpenD binary ready)"
fi

cat <<EOF

============================================================
Next (manual — secrets never auto-filled):
============================================================
1) Download Linux x86_64 command-line OpenD from Futu OpenAPI docs
   place binary at:  /opt/futuopend/FutuOpenD
   sudo chmod +x /opt/futuopend/FutuOpenD
   sudo chown $APP_USER:$APP_USER /opt/futuopend/FutuOpenD

2) Edit secrets (chmod 600 already):
   $LOCAL/opend.env   # FUTU_LOGIN_ACCOUNT + FUTU_LOGIN_PWD_MD5
   $LOCAL/app.env     # keep QRESEARCH_SG_PAPER_SUBMIT=0 at first

   MD5 helper:
   python3 -c "import hashlib; print(hashlib.md5(b'YOUR_PASSWORD').hexdigest())"

3) Render OpenD XML + check:
   bash $VPS/bin/render-opend-xml.sh
   bash $VPS/doctor.sh

4) First login may require SMS / device trust on this VPS IP.
   sudo systemctl start qresearch-opend
   sudo journalctl -u qresearch-opend -f

5) Start API:
   sudo systemctl enable --now qresearch-opend qresearch-api

6) Cron (signal after close / submit near open):
   sudo crontab -u $APP_USER -e
   # paste $VPS/crontab.example (paths already /opt/qresearch — edit if needed)

7) Firebase: set API to your VPS HTTPS URL or Cloudflare named tunnel.
   Keep OpenD on 127.0.0.1 only.

Security: password lives only in $LOCAL (gitignored).
REFUSE start if secrets missing (require-secrets.sh).
EOF
