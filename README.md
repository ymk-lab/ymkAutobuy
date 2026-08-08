# qresearch — 研究取向量化回測框架

面向「研究 → 驗證 → paper → live」的量化研究骨架。目前 Structure Gate 預設為 **v11**（SPY40 / QQQ30 / SMH30 獨立袖口），paper 接 **富途 OpenD SIMULATE**。

## 安裝

```bash
python3 -m pip install -e ".[dev,futu,web]"
```

## Structure Gate v11 · 富途 paper

1. 本機／VPS 啟動 [Futu OpenD](https://openapi.futunn.com/)，開啟行情＋交易 API，交易環境設 **SIMULATE**，預設 `127.0.0.1:11111`
2. 複製 `.env.example` → `.env`，確認 `FUTU_*` 與 `QRESEARCH_SG_PAPER_*=…`
3. 先算訊號，再開送單

```bash
# 只算 v11 合併目標（不下單）
python3 examples/run_structure_gate_v11_paper_daily.py signal

# 送單到富途模擬盤（需 QRESEARCH_SG_PAPER_SUBMIT=1 且 OpenD 可連）
python3 examples/run_structure_gate_v11_paper_daily.py once

# 監控 UI
PYTHONPATH=src python3 -m uvicorn qresearch.web.paper_app:app --host 0.0.0.0 --port 8787
```

永久網址（二選一）：

1. **Firebase Hosting（前端）+ 隧道（API）** — 見 `deploy/firebase/README.md`
2. **Cloudflare Named Tunnel** 直出整站：hostname → `http://127.0.0.1:8787`，token 寫入 `.env` 的 `CLOUDFLARE_TUNNEL_TOKEN`：

```bash
bash deploy/cloudflare/run-named-tunnel.sh
```

每日 cron：`deploy/vps-cron/run-sg.sh`。

## 架構摘要

| 層 | 模組 |
|----|------|
| 回測 | `backtest/`、`validation/` |
| Structure Gate | `strategy/structure_gate.py`（v8/v10/v11） |
| Paper / Live | `paper/`、`live/` |
| 下單抽象 | `execution/`（`BrokerAdapter`） |
| 富途適配 | `brokers/futu/` |
| 長橋適配 | `brokers/longbridge/`（legacy） |

## 研究紀律

1. 訊號與成交至少隔一根 bar  
2. 回測 → paper（SIMULATE）→（確認後）才考慮 REAL  
3. `QRESEARCH_FUTU_ALLOW_LIVE` 必須保持關閉，除非刻意實盤  
4. OpenAPI 下單等同真實交易，測試時小心參數  

> 這是研究框架，不是保證獲利的交易機器人。
