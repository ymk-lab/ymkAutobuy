# 本機部署（OpenD 已安裝）

把雲端上的 Structure Gate v11 拉到你本機，與富途 OpenD 同機跑。

## 1. 取得程式

### 方式 A：解壓 Agent 打包檔（最快）

從 Cursor Agent 下載 `qresearch-local-*.tar.gz`，然後：

```bash
mkdir -p ~/qresearch && cd ~/qresearch
tar -xzf ~/Downloads/qresearch-local-*.tar.gz
cd qresearch-local   # 或解壓後的資料夾名
```

### 方式 B：git（若你有遠端倉庫）

```bash
git clone <你的-repo-url> qresearch
cd qresearch
git checkout cursor/structure-gate-v11-futu-600b
```

## 2. 一鍵安裝

需要 Python 3.10+。

```bash
bash deploy/local/setup.sh
```

會建立 `.venv`、安裝 `futu-api`／web 依賴、從 `.env.example` 產生 `.env`。

## 3. 確認 OpenD

1. 本機 OpenD 已登入，埠 `11111`
2. 測連線：

```bash
source .venv/bin/activate
PYTHONPATH=src python -c "from qresearch.brokers.futu import has_futu_opend; print(has_futu_opend())"
# 應為 True
```

若 `False`：檢查 OpenD 是否聽 `127.0.0.1:11111`，或改 `.env` 的 `FUTU_OPEND_HOST`／`PORT`。

## 4. 算訊號 → 開 UI

```bash
# 不下單
PYTHONPATH=src python examples/run_structure_gate_v11_paper_daily.py signal

# 開監控頁
bash deploy/local/run-ui.sh
```

瀏覽器開：http://127.0.0.1:8787  
先按「同步帳戶」，確認模擬盤現金／持倉。

## 5. 再開 paper 送單

`.env` 設：

```bash
QRESEARCH_SG_PAPER_SUBMIT=1
```

UI 重新整理後，「執行一次」才會對 **SIMULATE** 下單。  
`QRESEARCH_FUTU_ALLOW_LIVE` 保持 `0`。

## 常見問題

| 狀況 | 處理 |
|------|------|
| `has_futu_opend() False` | OpenD 未開／埠不對／綁了別的 IP |
| 同步帳戶失敗 | 確認交易環境是模擬盤；OpenD 已登入 |
| 缺 K 線 | 開着 OpenD，設 `QRESEARCH_REFRESH_CACHE=1` 再跑 signal |
| 想關筆電仍跑 | 之後再搬到 VPS；本機方案必須電腦醒着 |
