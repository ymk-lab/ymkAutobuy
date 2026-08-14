# Linux VPS：OpenD + Structure Gate v13（24×7）

便宜小機（建議 **Ubuntu 22.04/24.04 x86_64、≥2GB RAM**）上常駐：

```
Firebase UI → HTTPS API :8787（VPS）
                 ↓
            OpenD 127.0.0.1:11111（同機，不對外）
                 ↓
            cron：收盤後 16:30 signal / 次日 09:40 once
```

**成交時點（已定案）**：美東 **09:40**（不是 09:30）。  
UI「自動送單」會寫 `/opt/qresearch/.env`；cron／systemd 以 `.env` 覆蓋 `app.env`。

帳密**不會**寫進 git；只放在 `deploy/vps/secrets/local/`（已 gitignore）。缺密則拒絕啟動。

## 0. 風險（先讀）

| 項目 | 說明 |
|------|------|
| VPS 被入侵 | 等於可能拿到富途登入能力 |
| OpenD 對公網 | **禁止**；腳本拒絕非 `127.0.0.1` |
| 真倉 | 預設 `SIMULATE`；`QRESEARCH_FUTU_ALLOW_LIVE` 保持 `0` |
| 首次登入 | 新 IP 常要簡訊／信任裝置 |

建議：先只跑模擬盤；密碼用 MD5 寫入 XML；`opend.env` 權限 `600`。

## 1. 買 VPS 後

```bash
sudo mkdir -p /opt && sudo chown "$USER" /opt
git clone https://github.com/ymk-lab/ymkAutobuy.git /opt/qresearch
cd /opt/qresearch
git checkout main   # 或含本目錄的分支
bash deploy/vps/install.sh
```

## 2. 安裝 Linux OpenD

從富途 OpenAPI 文件下載 **Command Line OpenD（Linux x86_64）**，放到：

```bash
sudo mkdir -p /opt/futuopend
# 解壓後把執行檔命名／連結為：
sudo cp /path/to/FutuOpenD /opt/futuopend/FutuOpenD
sudo chmod +x /opt/futuopend/FutuOpenD
```

（官方下載頁會更新；不要把二進位 commit 進 repo。）

## 3. 填密（只在伺服器上）

```bash
nano deploy/vps/secrets/local/opend.env
# FUTU_LOGIN_ACCOUNT=你的牛牛號或電郵
# FUTU_LOGIN_PWD_MD5=...(32 hex)

python3 -c "import hashlib; print(hashlib.md5(b'你的密碼').hexdigest())"

# 或暫時寫 FUTU_LOGIN_PWD=... 再渲染（會自動改成 MD5 並刪明文）：
bash deploy/vps/bin/render-opend-xml.sh

nano deploy/vps/secrets/local/app.env
# 先保持 QRESEARCH_SG_PAPER_SUBMIT=0
```

## 4. 啟動

```bash
bash deploy/vps/doctor.sh
sudo systemctl enable --now qresearch-opend qresearch-api
sudo systemctl status qresearch-opend qresearch-api
```

本機測 API：`curl -s http://127.0.0.1:8787/api/sg/health`（若有此路由）或開瀏覽器 `http://VPS_IP:8787`。

對外建議：Cloudflare Named Tunnel / reverse proxy，**不要**把 `11111` 開到防火牆。

## 5. 排程（收盤算訊號 → 次日 09:40 送單）

**主排程改用 systemd timer**（比 crontab 可靠；機器當機也能 Persistent 補跑 signal）：

```bash
sudo QRESEARCH_USER=root bash deploy/vps/bin/sync-systemd.sh
systemctl list-timers 'qresearch-paper-*' --no-pager
```

| 時間（美東） | unit | 動作 |
|--------------|------|------|
| 16:30 Mon–Fri | `qresearch-paper-signal.timer` | `run-paper.sh signal`（可 Persistent 補跑） |
| 09:40 Mon–Fri | `qresearch-paper-once.timer` | `run-paper.sh once`（不補跑，避免錯時送單） |

`sync-systemd.sh` 也會順便寫入 `crontab.example` 當備份；**以 timer 為準**。

確認：

```bash
bash deploy/vps/doctor.sh
journalctl -u qresearch-paper-signal.service -n 50 --no-pager
```

UI「自動送單」仍寫 `/opt/qresearch/.env`；once 會讀 `.env` 的 `QRESEARCH_SG_PAPER_SUBMIT`。

### 更新 systemd（勿 raw-cp）

```bash
# 會把 REPLACE_USER 換成實際使用者（預設目前 sudo 使用者）
sudo QRESEARCH_USER=root bash deploy/vps/bin/sync-systemd.sh
sudo systemctl restart qresearch-api
```

## 檔案一覽

| 路徑 | 用途 |
|------|------|
| `install.sh` | venv、目錄、systemd |
| `bin/sync-systemd.sh` | **正確**安裝/更新 unit（取代手動 cp） |
| `secrets/*.example` | 範本（可進 git） |
| `secrets/local/*` | **真密**（gitignore） |
| `bin/require-secrets.sh` | 缺密則失敗 |
| `bin/render-opend-xml.sh` | 產生 `FutuOpenD.xml` |
| `bin/start-opend.sh` / `start-api.sh` | 常駐程序 |
| `bin/run-paper.sh` | 日更 |
| `crontab.example` | 美東 cron |
| `doctor.sh` | 健康檢查 |

舊的 `deploy/vps-cron/` 仍可用於長橋 G1；**Futu v13 請用本目錄**。
