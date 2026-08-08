# 小型 VPS + cron：Emerging RS G1 Paper Trade

日頻策略，一台 1 vCPU / 1GB 的 Ubuntu VPS 即可。

## 1. 準備 VPS

```bash
# 例：把 repo 放到 /opt/qresearch
sudo mkdir -p /opt && sudo chown "$USER" /opt
git clone <your-repo-url> /opt/qresearch
cd /opt/qresearch
./deploy/vps-cron/install.sh
```

編輯 `/opt/qresearch/.env`：

```bash
LONGBRIDGE_APP_KEY=...
LONGBRIDGE_APP_SECRET=...
LONGBRIDGE_ACCESS_TOKEN=...
QRESEARCH_LB_CURRENCY=USD

# 先保持 0：只產出訊號、不下單
QRESEARCH_LB_SUBMIT=0

# 確認無誤後改 1：對長橋「模擬盤」下市價單
# QRESEARCH_LB_SUBMIT=1

# 建議：只用 5 萬美金袖口下單（帳戶可以有更多現金）
QRESEARCH_SLEEVE_USD=50000
```

## 2. 手動試跑

```bash
cd /opt/qresearch
source .venv/bin/activate
./deploy/vps-cron/run.sh once
cat examples/data/emerging_rs_g1_paper/latest_signal.json
```

看 `target`、`preview_orders` 是否合理。

## 3. 裝 cron

```bash
crontab -e
# 貼上 deploy/vps-cron/crontab.example 內容，路徑改成你的 clone
```

預設：**美東 16:30（週一至五）** 跑一次（美股現金收盤後）。

## 4. 開啟自動下單（模擬盤）

1. 連續幾天確認 `latest_signal.json`  
2. `.env` 設 `QRESEARCH_LB_SUBMIT=1`  
3. 翌日 cron 會對長橋 paper 帳戶送單  
4. 同一 `asof` 日預設不重複下單（`state.json`）；緊急則 `QRESEARCH_FORCE=1`

## 5. 產物

| 路徑 | 說明 |
|---|---|
| `examples/data/emerging_rs_g1_paper/latest_signal.json` | 最新目標持倉 |
| `examples/data/emerging_rs_g1_paper/latest_run.json` | 最近一次實際下單 |
| `examples/data/emerging_rs_g1_paper/logs/` | cron / run 日誌 |
| `examples/data/emerging_rs_g1_paper/state.json` | 防重複下單 |

## 注意

- 回測是「訊號日收盤 → 次日開盤」；cron 收盤後立刻市價單，與回測略有時差（paper 可接受）。
- 憑證權限：`chmod 600 .env`
- 本流程**不會**把 Cursor Agent 當常駐程序；VPS cron 才是執行者。


## Paper UI（可選）

```bash
cd /opt/qresearch
source .venv/bin/activate
pip install -e ".[web]"
./deploy/vps-cron/run-ui.sh
# 瀏覽 http://<VPS-IP>:8787
```

首頁為 **Structure Gate paper monitor**（本金／目標／掛單／盈虧優先；其後才是回測與規則）。  
按鈕旁有操作說明；進度以 SSE 即時顯示。

---

## Structure Gate v8 自動 paper 掛單

與 G1 **分開**的開關，不會用到 `QRESEARCH_LB_SUBMIT`。

### `.env`

```bash
QRESEARCH_SG_PAPER_ONLY=1
QRESEARCH_SG_PAPER_SUBMIT=0   # 先 0 驗證訊號；確認後改 1
QRESEARCH_SG_BOOK=SPY         # 或 QQQ / SMH …
QRESEARCH_SLEEVE_USD=50000
# QRESEARCH_SG_PAPER_OUT=/opt/qresearch/examples/data/structure_gate_v8_paper
```

### 手動試跑 → 開自動

```bash
chmod +x deploy/vps-cron/run-sg.sh
./deploy/vps-cron/run-sg.sh once          # SUBMIT=0：只計畫
cat examples/data/structure_gate_v8_paper/latest_signal.json

# 確認 target / preview_orders 後：
# 把 QRESEARCH_SG_PAPER_SUBMIT=1 寫進 .env
crontab -e   # 貼上 crontab.example 裡 Structure Gate 那一行（美東 16:35）
```

之後每個美股交易日收盤後，cron 會：抓長橋日 K → 算 v8 mode → 對**模擬盤**市價調倉。  
同一 `asof` 不會重複下單（`state.json`）；要重送設 `QRESEARCH_FORCE=1`。

| 路徑 | 說明 |
|---|---|
| `examples/data/structure_gate_v8_paper/latest_signal.json` | 最新 mode / 目標 |
| `examples/data/structure_gate_v8_paper/latest_run.json` | 最近一次實際送單 |
| `examples/data/structure_gate_v8_paper/logs/` | cron 日誌 |
