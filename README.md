# qresearch — 研究取向量化回測框架

面向「研究 → 驗證 → 再談實盤」的單資產回測骨架，內建：

- **Next-bar execution**：訊號在 t 產生，在 t+1 open 成交，降低 look-ahead
- **成本模型**：手續費 + 滑價（bps）
- **Regime hook**：波動率市況標籤，策略可依市況降倉／空手
- **Walk-forward**：樣本外折疊驗證，避免只看 in-sample 曲線

## 安裝

```bash
python3 -m pip install -e ".[dev]"
```

## 快速開始

```bash
python examples/run_sma_backtest.py
python examples/run_regime_backtest.py
pytest -q
```

## 最小程式碼

```python
from qresearch import BacktestEngine, CostModel
from qresearch.data.synthetic import generate_synthetic_ohlcv
from qresearch.strategy.examples import RegimeAwareTrendStrategy

data = generate_synthetic_ohlcv(n=750)
engine = BacktestEngine(cost_model=CostModel(fee_bps=1, slippage_bps=2))
result = engine.run(data, RegimeAwareTrendStrategy(fast=10, slow=40))
print(result.summary())
```

## 專案結構

```
src/qresearch/
  data/          # OHLCV 載入、合成資料
  strategy/      # Strategy 介面與範例
  regime/        # 市況偵測
  backtest/      # 引擎與成本
  metrics/       # Sharpe / MDD / turnover 等
  validation/    # walk-forward
```

## 研究紀律（刻意保留的限制）

1. 訊號必須 `shift(1)` 後才進倉，禁止同 bar 偷看未來
2. 先看 **扣成本後** 的績效，再談 alpha
3. 參數調優只在 train 窗，用 walk-forward 看 OOS
4. Regime 邏輯先做可解釋規則；模型之後再接

## 下一步（建議順序）

1. 接真實 CSV／交易所資料（`load_ohlcv_csv`）
2. 在 walk-forward 的 `strategy_factory` 做 train 集參數搜尋
3. 加入多資產組合與風險預算
4. Paper trading 對齊同一套訊號／成本假設

> 這是研究框架，不是保證獲利的交易機器人。
