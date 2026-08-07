# qresearch — 研究取向量化回測框架

面向「研究 → 驗證 → paper → live loop → 長橋實盤適配」的量化研究骨架。

## 安裝

```bash
python3 -m pip install -e ".[dev,longbridge]"
```

## 快速開始

```bash
python3 examples/run_sma_backtest.py
python3 examples/run_multi_asset.py
python3 examples/run_live_loop.py
python3 examples/run_longbridge_dry_run.py
python3 -m pytest -q
```

## 長橋（Longbridge）接線

1. 到 [open.longbridge.com](https://open.longbridge.com/) 建立應用，取得 App Key / Secret / Access Token  
2. 複製 `.env.example` 為 `.env` 並填入憑證  
3. **先 dry-run，再考慮真實下單**

```bash
# 不需金鑰：驗證 live loop ↔ LongbridgeBrokerAdapter 下單路徑
python3 examples/run_longbridge_dry_run.py

# 有金鑰：只讀帳戶／報價／歷史 K 線（不會下單）
python3 examples/run_longbridge_account.py
```

```python
from qresearch.brokers.longbridge import LongbridgeBrokerAdapter

# dry_run=True（預設）不會打到 submit_order
broker = LongbridgeBrokerAdapter.from_env(dry_run=True, currency="HKD")
print(broker.get_cash(), broker.get_positions())

# ⚠️ 真實下單：確認策略／風控後才可改
# broker = LongbridgeBrokerAdapter.from_env(dry_run=False, currency="HKD")
```

標的格式必須是 `TICKER.MARKET`（如 `700.HK`、`AAPL.US`）。

## 架構摘要

| 層 | 模組 |
|----|------|
| 回測 | `backtest/`、`validation/` |
| 風險預算 | `portfolio/` |
| Paper / Live | `paper/`、`live/` |
| 下單抽象 | `execution/`（`BrokerAdapter`） |
| 長橋適配 | `brokers/longbridge/` |

## 研究紀律

1. 訊號與成交至少隔一根 bar  
2. 回測 → paper → dry-run live →（確認後）實盤  
3. `dry_run=False` 前務必確認殺傷開關與標的／幣別  
4. OpenAPI 下單等同真實交易，測試時小心參數  

> 這是研究框架，不是保證獲利的交易機器人。
