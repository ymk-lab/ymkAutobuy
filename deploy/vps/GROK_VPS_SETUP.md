# VPS 實際設定說明（給 Grok / 其他 AI 看）

這份文件描述 **ymkAutobuy** 目前 **Linux VPS 上真正在跑的 paper 架構**，不是本機 Windows、也不是舊的長橋 G1 cron。

**讀這份時請當事實，不要發明另一套部署。**

- 策略預設：**Structure Gate v13**（`StructureGateConfig.v13()`）
- 權重：**SPY 50% / QQQ 50%**（`V13_BOOK_WEIGHTS`）
- 券商：**Futu OpenD SIMULATE**（模擬盤）
- 成交時點：美東 **09:40**（不是 09:30）
- 訊號時點：美東 **16:30**（收盤後只算目標、不下單）
- 程式碼根目錄：**`/opt/qresearch`**
- OpenD 二進位：**`/opt/futuopend/FutuOpenD`**
- v14–v17 只是研究對照，**不要改 production paper 預設**

舊路徑 `deploy/vps-cron/` 是長橋 Emerging RS G1 / 早期 Structure Gate v8，**Futu v13 不要用那套**。

---

## 1. 這台機器在幹嘛

```
瀏覽器
  → Firebase Hosting UI
       https://ymk-autobuy.web.app
       https://ymk-autobuy.firebaseapp.com
  → HTTPS（Cloudflare Named Tunnel）
  → VPS uvicorn :8787  （qresearch-api.service）
       ↓ 只連 loopback
  → OpenD 127.0.0.1:11111  （qresearch-opend.service）
       ↓
  systemd timer
       16:30 ET  signal（算訊號）
       每 15 分  watchdog（訊號過期就補跑）
       09:40 ET  once（送模擬盤）
```

規則：

1. OpenD **只聽 127.0.0.1:11111**。防火牆不要開 11111。腳本遇到 XML 寫 `0.0.0.0` 會拒絕啟動。
2. API 聽 `0.0.0.0:8787`，對外靠 Cloudflare tunnel / reverse proxy，不要裸奔公網 IP。
3. `QRESEARCH_FUTU_ALLOW_LIVE` 必須是 `0`。真倉開關不要打開。
4. 帳密只在伺服器上的 `deploy/vps/secrets/local/`（gitignore），**永不進 git**。

---

## 2. 機器假設（當初怎麼選）

| 項目 | 實際要求 |
|------|----------|
| OS | Ubuntu 22.04 或 24.04 |
| CPU 架構 | **x86_64**（官方 Linux OpenD 是 x86_64；ARM 要模擬，當初沒這樣做） |
| RAM | 建議 ≥ 2GB |
| 角色 | 單機 24×7：OpenD + API + paper timer |
| 時區 | 系統時區隨意；**排程一律 America/New_York**（timer `OnCalendar=... America/New_York`；crontab 用 `CRON_TZ=America/New_York`） |
| 執行使用者 | 這台後來常用 `QRESEARCH_USER=root` 裝 systemd（`sync-systemd.sh` 會把 unit 裡的 `REPLACE_USER` 換成這個使用者） |
| Repo | `https://github.com/ymk-lab/ymkAutobuy.git` → `/opt/qresearch` |
| 執行分支（paper） | 當初 cutover 用 `cursor/structure-gate-v13-600b`；`main` 文件可能仍寫 v11，**以 VPS checkout 的分支為準** |

---

## 3. 目錄與檔案地圖

```
/opt/qresearch/                          # git clone
  .venv/                                 # install.sh 建的 python venv
  .env                                   # UI「自動送單」會改這裡；覆蓋 app.env
  deploy/vps/
    install.sh                           # 第一次：套件、venv、secrets 目錄、粗裝 systemd
    doctor.sh                            # 健康檢查（OpenD / timer / asof）
    crontab.example                      # 備份 cron（主排程是 systemd timer）
    secrets/
      *.example                          # 可進 git 的範本
      local/                             # 真密（chmod 700；檔案 600）
        opend.env
        app.env
        FutuOpenD.xml                    # render-opend-xml.sh 產生
    bin/
      sync-systemd.sh                    # **更新 unit 一定走這支，禁止 raw-cp**
      render-opend-xml.sh
      require-secrets.sh
      start-opend.sh / start-api.sh
      wait-opend.sh
      run-paper.sh                       # signal | once
      ensure-paper-signal.sh             # watchdog：asof 過期才 systemctl start signal
      cutover-v13.sh                     # 舊 v11 → v13 一次性切換
    systemd/
      qresearch-opend.service
      qresearch-api.service
      qresearch-paper-signal.service + .timer
      qresearch-paper-signal-watchdog.service + .timer
      qresearch-paper-once.service + .timer
  examples/run_structure_gate_v13_paper_daily.py
  examples/data/structure_gate_v13_paper/
    latest_signal.json
    latest_run.json
    state.json
    cache_ohlcv/
    logs/

/opt/futuopend/
  FutuOpenD                              # 官方 Linux CLI 二進位（不要 commit）
  FutuOpenD.xml                          # 常駐時 start-opend.sh 優先用這份
  AppData.dat / 相關 lib                 # OpenD 工作目錄要在這裡

/var/log/qresearch/
  opend.out.log / opend.err.log
```

環境變數覆蓋順序（paper / API）：

1. systemd unit 內建 `Environment=`
2. `deploy/vps/secrets/local/app.env`
3. `/opt/qresearch/.env`（**最後贏**；UI 開關寫這裡）

---

## 4. 第一次從零裝（當初步驟）

### 4.1 買機、放 repo

```bash
sudo mkdir -p /opt && sudo chown "$USER" /opt
git clone https://github.com/ymk-lab/ymkAutobuy.git /opt/qresearch
cd /opt/qresearch
# paper 當初切到 v13 分支，不是 blindly checkout main
git checkout cursor/structure-gate-v13-600b
git pull --ff-only origin cursor/structure-gate-v13-600b
```

### 4.2 跑 bootstrap

```bash
cd /opt/qresearch
# 這台後來用 root 當 service user：
export QRESEARCH_USER=root
bash deploy/vps/install.sh
```

`install.sh` **會做**：

- `apt-get`：`python3-venv python3-pip git curl ca-certificates netcat`
- `python3 -m venv .venv`，`pip install -e ".[futu,web]"`
- 建 `deploy/vps/secrets/local/`（700）
- 從 example 複製 `opend.env` / `app.env`（若還沒有）
- 合併 app.env 缺的 key 到 repo `.env`
- 建 `/opt/futuopend`、`/var/log/qresearch`
- 粗裝 `qresearch-opend.service` + `qresearch-api.service`（**還不啟動**）

`install.sh` **不會做**：

- 不下載 Futu OpenD 二進位
- 不填帳密
- 不啟用 paper timer（後來用 `sync-systemd.sh`）

### 4.3 安裝 Linux OpenD

從富途 OpenAPI 文件下載 **Command Line OpenD（Linux x86_64）**，放到：

```bash
sudo mkdir -p /opt/futuopend
sudo cp /path/to/FutuOpenD /opt/futuopend/FutuOpenD
sudo chmod +x /opt/futuopend/FutuOpenD
sudo chown root:root /opt/futuopend/FutuOpenD   # 若 QRESEARCH_USER=root
```

不要把二進位 commit 進 repo。OpenD 必須在 `/opt/futuopend` 工作目錄跑（需要旁邊的 `AppData.dat` / libs）。

### 4.4 只在伺服器填密

```bash
cd /opt/qresearch
nano deploy/vps/secrets/local/opend.env
```

必要欄位：

```bash
FUTU_LOGIN_ACCOUNT=牛牛號或電郵
FUTU_LOGIN_PWD_MD5=32位hex
FUTU_OPEND_IP=127.0.0.1
FUTU_OPEND_PORT=11111
FUTU_OPEND_BIN=/opt/futuopend/FutuOpenD
```

算 MD5（UTF-8 密碼）：

```bash
python3 -c "import hashlib; print(hashlib.md5(b'你的密碼').hexdigest())"
```

或暫時寫 `FUTU_LOGIN_PWD=`，再渲染（腳本會改成 MD5 並刪明文）：

```bash
bash deploy/vps/bin/render-opend-xml.sh
# 產出 deploy/vps/secrets/local/FutuOpenD.xml（600）
# start-opend.sh 也會優先用 /opt/futuopend/FutuOpenD.xml
```

`app.env` 當初預設：

```bash
FUTU_OPEND_HOST=127.0.0.1
FUTU_OPEND_PORT=11111
FUTU_TRD_ENV=SIMULATE
QRESEARCH_FUTU_ALLOW_LIVE=0
QRESEARCH_SG_PAPER_ONLY=1
QRESEARCH_SG_PAPER_SUBMIT=0          # 先 0，訊號對了幾天才改 1
QRESEARCH_SG_BOOK=V13
QRESEARCH_SLEEVE_USD=50000
QRESEARCH_REFRESH_CACHE=1
QRESEARCH_UI_HOST=0.0.0.0
QRESEARCH_UI_PORT=8787
QRESEARCH_CORS_ORIGINS=https://ymk-autobuy.web.app,https://ymk-autobuy.firebaseapp.com
```

新 IP 第一次登入 OpenD，富途常要簡訊／信任裝置。看：

```bash
sudo journalctl -u qresearch-opend -f
```

### 4.5 啟動常駐 + 裝 timer

```bash
cd /opt/qresearch
bash deploy/vps/doctor.sh
sudo systemctl enable --now qresearch-opend qresearch-api
sudo QRESEARCH_USER=root bash deploy/vps/bin/sync-systemd.sh
sudo systemctl status qresearch-opend qresearch-api --no-pager
systemctl list-timers 'qresearch-paper-*' --no-pager
```

本機驗證：

```bash
curl -s http://127.0.0.1:8787/api/sg/health
# 或瀏覽器 http://127.0.0.1:8787
```

`sync-systemd.sh` 會：

- 把 `REPLACE_USER` → `QRESEARCH_USER`（這台是 `root`）
- 把路徑固定到 `/opt/qresearch`
- enable：`signal.timer` + `watchdog.timer` + `once.timer`
- 順便把 `crontab.example` 寫進該使用者 crontab（**備份**；以 timer 為準）
- 若 `asof` 過期，呼叫 `ensure-paper-signal.sh` 補跑 signal
- restart `qresearch-api`

**禁止** `cp deploy/vps/systemd/*.service /etc/systemd/system/`：會留下字面 `REPLACE_USER`。

---

## 5. 排程（這是 paper 的心臟）

| 美東時間 | systemd unit | 做什麼 | Persistent |
|----------|--------------|--------|------------|
| Mon–Fri 16:30 | `qresearch-paper-signal.timer` → `qresearch-paper-signal.service` | `run-paper.sh signal`：只算 v13 目標 | **true**（當機可補跑） |
| 開機 3 分後，之後每 15 分 | `qresearch-paper-signal-watchdog.timer` | `ensure-paper-signal.sh`：`latest_signal.asof` 若落後「上一完整美股交易日（16:30 後才算當天）」，就 `systemctl start qresearch-paper-signal.service` | true |
| Mon–Fri 09:40 | `qresearch-paper-once.timer` → `qresearch-paper-once.service` | `run-paper.sh once`：送 SIMULATE | **false**（錯過不要補送，避免錯時下單） |

對應 HKT（夏令 EDT = HKT−12）：16:30 ET → 04:30 HKT 翌日；09:40 ET → 21:40 HKT。冬令 EST 再加一小時時差。

### 為什麼需要 15 分鐘 watchdog

16:30 timer 若當下 OpenD 沒起來、或 calendar 漏觸發，`Persistent=` **不會**在 service 失敗後重試。週末若把「今天−3 天」當新鮮，`asof` 也會卡住。watchdog 只看 `latest_signal.json` 的 `asof` 是否覆蓋上一完整交易日。

`ensure-paper-signal.sh` **不直接跑 python**，只 `systemctl start` 同一支 signal service（有 flock）。

### crontab 備份（不要當主排程）

```
CRON_TZ=America/New_York
30 16 * * 1-5  .../run-paper.sh signal
40 9  * * 1-5  .../run-paper.sh once
```

沒有 `CRON_TZ=America/New_York` 時，`40 9` 會變成 **09:40 UTC**，送單時間全錯。

---

## 6. Paper 工作流（v13）

`run-paper.sh` 流程：

1. `wait-opend.sh 127.0.0.1 11111`
2. source `secrets/local/app.env`，再 source `/opt/qresearch/.env`
3. `python3 examples/run_structure_gate_v13_paper_daily.py signal|once`

| 模式 | 意義 |
|------|------|
| `signal` | 更新行情 cache、算 mode／目標、寫 `latest_signal.json`，**不下單** |
| `once` | 讀訊號、對 SIMULATE 調倉；需 `.env` 裡 `QRESEARCH_SG_PAPER_SUBMIT=1` |

同一 `asof` 預設不重複下單（`state.json`）。緊急重送才設 `QRESEARCH_FORCE=1`。

UI「自動送單」只改 `/opt/qresearch/.env` 的 `QRESEARCH_SG_PAPER_SUBMIT`。

產出：

| 檔 | 用途 |
|----|------|
| `examples/data/structure_gate_v13_paper/latest_signal.json` | 最新 asof / mode / target |
| `latest_run.json` | 最近一次實際送單 |
| `state.json` | 防重複 |
| `logs/vps_signal_*.log` / `vps_once_*.log` | 每次 timer 日誌 |

策略 knobs 以程式為準：`src/qresearch/strategy/structure_gate.py` 的 `StructureGateConfig.v13()`。長窗 trail **20/60**，不要擅自改成 20/50。

---

## 7. 對外網址（Firebase + Cloudflare）

### VPS 端 API

`qresearch-api.service`：

```text
/opt/qresearch/.venv/bin/python -m uvicorn qresearch.web.paper_app:app \
  --host 0.0.0.0 --port 8787
```

`ExecStartPre` 會等 OpenD `:11111` 最多 30 次。

CORS 預設允許：

- `https://ymk-autobuy.web.app`
- `https://ymk-autobuy.firebaseapp.com`

### Named Tunnel（建議）

1. Cloudflare Zero Trust → Networks → Tunnels
2. Public hostname → `http://127.0.0.1:8787`
3. token 寫進 `/opt/qresearch/.env`：

```bash
CLOUDFLARE_TUNNEL_TOKEN=eyJ...
# 可選
QRESEARCH_PUBLIC_API_BASE=https://你的固定hostname
```

4. 跑 `bash deploy/cloudflare/run-named-tunnel.sh`  
   （腳本會抓 `cloudflared-linux-amd64`）

Quick tunnel 每次 URL 會變，只適合測試。

### Firebase UI

`deploy/firebase/` 只託管前端。`QRESEARCH_API_BASE` 在 deploy 時寫進 `public/config.js`。換隧道網址要重 deploy。

**OpenD / 下單不能放 Firebase Functions 或 Cloud Run 單獨跑**——必須跟 VPS 上的 OpenD 同機（或至少能連 11111）。Cloud Run 直連筆電 OpenD 也不行。

---

## 8. 日常維護指令（這台實際在用的）

更新程式（VPS 上）：

```bash
cd /opt/qresearch
git pull --ff-only origin cursor/structure-gate-v13-600b
sudo QRESEARCH_USER=root bash deploy/vps/bin/sync-systemd.sh
bash deploy/vps/doctor.sh
```

看狀態：

```bash
systemctl status qresearch-opend qresearch-api --no-pager
systemctl list-timers 'qresearch-paper-*' --no-pager
journalctl -u qresearch-opend -n 80 --no-pager
journalctl -u qresearch-api -n 80 --no-pager
journalctl -u qresearch-paper-signal.service -n 50 --no-pager
journalctl -u qresearch-paper-signal-watchdog.service -n 20 --no-pager
journalctl -u qresearch-paper-once.service -n 50 --no-pager
ss -ltn | grep -E ':11111|:8787'
```

手動補訊號（不要手打 python，走同一支 service）：

```bash
sudo systemctl start qresearch-paper-signal.service
```

手動 dry-run：

```bash
cd /opt/qresearch
bash deploy/vps/bin/run-paper.sh signal
```

---

## 9. 從舊 v11 切到 v13（已經做過）

一次性腳本：`deploy/vps/bin/cutover-v13.sh`

它會：

- checkout `cursor/structure-gate-v13-600b`
- `QRESEARCH_SG_BOOK=V13`
- paper 目錄改成 `examples/data/structure_gate_v13_paper`
- crontab 路徑 `v11` → `v13`
- `sync-systemd.sh` + restart API
- 跑一次 `run-paper.sh signal`

之後 leftover SMH 袖口會在下一次 `once` 被 flatten 進新目標。不要再切回 v11 paper。

---

## 10. 安全紅線

| 不要做 | 為什麼 |
|--------|--------|
| 把 `opend.env` / XML / 密碼 commit | gitignore 就是為了這個 |
| OpenD 聽 `0.0.0.0` | `start-opend.sh` 會 REFUSE |
| 防火牆開 11111 | 等於公開富途 API |
| `QRESEARCH_FUTU_ALLOW_LIVE=1` | 真倉 |
| raw-cp systemd unit | `User=REPLACE_USER` 會壞掉 |
| 把 v15/v16/v17 設成 paper 預設 | 已回測過；paper 鎖定 v13 |
| once timer 開 Persistent=true | 錯過 09:40 補送會錯時成交 |
| watchdog 直接 `python paper_daily.py` | 必須走 `systemctl start` 同一支 signal |

VPS 被入侵 ≈ 拿到富途登入能力。先只跑 SIMULATE。

---

## 11. 給 Grok 改東西時的約束

1. **Paper 預設保持 v13。** 新 preset 可以加，不要改 `run_structure_gate_v13_paper_daily.py` / `paper_app.py` 去呼叫 v14+。
2. 改 systemd 後，文件要寫「VPS 上跑 `sudo QRESEARCH_USER=root bash deploy/vps/bin/sync-systemd.sh`」，不要叫人 `cp` unit。
3. 改訊號排程時，同時想 16:30 timer **和** 15 分 watchdog；`asof` 要用「上一完整美股交易日」，不要 `today-3`。
4. 送單時間只能是 **09:40 America/New_York**。
5. 密文路徑不要改出 `secrets/local/`；新 secret 加 example，不要加真值。
6. 舊 `deploy/vps-cron/` 不要接回 Futu v13。

---

## 12. 相關檔案（原始來源）

| 檔 | 內容 |
|----|------|
| `deploy/vps/README.md` | 短版操作手冊 |
| `deploy/vps/install.sh` | 初次安裝 |
| `deploy/vps/bin/sync-systemd.sh` | unit / timer 權威安裝 |
| `deploy/vps/doctor.sh` | 健康檢查 |
| `deploy/vps/crontab.example` | cron 備份 |
| `deploy/cloudflare/README.md` | named tunnel |
| `deploy/firebase/README.md` | 前端 Hosting |
| `src/qresearch/strategy/structure_gate.py` | `v13()` knobs |
| `src/qresearch/web/paper_app.py` | UI/API |
| `examples/run_structure_gate_v13_paper_daily.py` | 日更 job |
