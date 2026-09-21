# qresearch — Structure Gate **v13**

研究 → 驗證 → paper 的量化骨架。**main 唯一生產引擎是 Structure Gate v13**
（`StructureGateConfig.v13()`，袖口 **SPY 50% / QQQ 50%**）。v11 不再是預設；
v14–v17 只留在 `examples/` 當研究對照，paper / UI / 回測都走 v13。

## 安裝

```bash
python3 -m pip install -e ".[dev,futu,web]"
```

驗證引擎（必須印出 dataclass，不能再出現 `missing part0.b64`）：

```bash
PYTHONPATH=src python3 -c "from qresearch.strategy.structure_gate import StructureGateConfig; print(StructureGateConfig.v13())"
```

## Structure Gate v13 · 富途 paper

1. 本機／VPS 啟動 [Futu OpenD](https://openapi.futunn.com/)，行情＋交易 API，交易環境 **SIMULATE**，預設 `127.0.0.1:11111`
2. 複製 `.env.example` → `.env`，確認 `FUTU_*` 與 `QRESEARCH_SG_PAPER_*=…`
3. 先算訊號，再開送單

```bash
# 只算 v13 合併目標（不下單）
python3 examples/run_structure_gate_v13_paper_daily.py signal

# 送單到富途模擬盤（需 QRESEARCH_SG_PAPER_SUBMIT=1 且 OpenD 可連）
python3 examples/run_structure_gate_v13_paper_daily.py once

# 監控 UI（與引擎同一棵樹）
PYTHONPATH=src python3 -m uvicorn qresearch.web.paper_app:app --host 0.0.0.0 --port 8787
```

本機驗證回測：

```bash
python3 examples/run_structure_gate_v13_blend.py 2026-08-01 2026-09-06
python3 examples/run_structure_gate_v13_yearly.py
```

長 SSE 不要走 Cloudflare／Firebase rewrite；先打本機 UI。SSE 已加
`X-Accel-Buffering: no`，前端會 flush 最後一個 `phase=done`。

## 架構摘要

| 層 | 模組 |
|----|------|
| 回測 | `backtest/`、`validation/` |
| Structure Gate | `strategy/structure_gate.py`（**生產 = v13**） |
| Paper / Live | `paper/`、`live/` |
| 下單抽象 | `execution/`（`BrokerAdapter`） |
| 富途適配 | `brokers/futu/` |

每日 cron（美東）：**16:30 `signal`**（只算目標）→ **09:40 `once`**（送單）。
成交時點 **09:40 ET**。

## 研究紀律

1. 訊號與成交至少隔一根 bar
2. 回測 → paper（SIMULATE）→（確認後）才考慮 REAL
3. `QRESEARCH_FUTU_ALLOW_LIVE` 必須保持關閉，除非刻意實盤
4. OpenAPI 下單等同真實交易

> 這是研究框架，不是保證獲利的交易機器人。
