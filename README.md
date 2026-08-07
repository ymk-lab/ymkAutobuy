# qresearch — 研究取向量化回測框架

面向「研究 → 驗證 → paper → live loop → 再接實盤」的量化研究骨架：

- **Next-bar execution** / **成本模型** / **Regime hook**
- **Walk-forward + 參數搜尋**
- **多資產風險預算**（反向波動、毛曝險、波動目標）
- **PaperBroker** 與回測對齊
- **BrokerAdapter 下單抽象** + **SimBroker**
- **LiveTradingLoop**：行情餵流 → 訊號 → 風控 → 下單

## 安裝

```bash
python3 -m pip install -e ".[dev]"
```

## 快速開始

```bash
python3 examples/run_sma_backtest.py
python3 examples/run_regime_backtest.py
python3 examples/prepare_sample_csv.py
python3 examples/run_csv_param_search.py
python3 examples/run_multi_asset.py
python3 examples/run_live_loop.py
python3 -m pytest -q
```

## 下單抽象 + Live loop

```python
from qresearch.backtest.costs import CostModel
from qresearch.data import generate_synthetic_panel
from qresearch.execution import SimBrokerAdapter, TargetWeightExecutor
from qresearch.live import HistoricalReplayFeed, LiveConfig, LiveTradingLoop
from qresearch.portfolio import RiskBudgetConfig
from qresearch.strategy.multi import CrossSectionalMomentumStrategy

panel = generate_synthetic_panel(("AAA", "BBB", "CCC"), n=320)
broker = SimBrokerAdapter(initial_cash=100_000, cost_model=CostModel(1, 3))
result = LiveTradingLoop(
    feed=HistoricalReplayFeed(panel),
    strategy=CrossSectionalMomentumStrategy(lookback=15),
    broker=broker,
    risk_config=RiskBudgetConfig(invert_vol=True, max_weight=0.5),
    config=LiveConfig(min_history=40, max_drawdown=0.25),
).run()
print(result.summary())
```

接真實券商時：實作 `BrokerAdapter.submit_order / get_positions / get_cash / get_equity`，live loop 不用改。

## 專案結構

```
src/qresearch/
  data/          # OHLCV、panel
  strategy/      # 單／多資產策略
  regime/        # 市況偵測
  portfolio/     # 風險預算
  backtest/      # 單／多資產回測
  paper/         # Paper 對齊
  execution/     # Order / BrokerAdapter / SimBroker
  live/          # MarketDataFeed / LiveTradingLoop
  metrics/
  validation/
```

## 研究紀律

1. 訊號決策與成交至少隔一根 bar
2. 先對齊回測 ↔ paper ↔ sim live，再接實盤
3. 參數只在 train 窗搜尋
4. Live 必備殺傷開關（最大回撤平坦倉）

> 這是研究框架，不是保證獲利的交易機器人。
