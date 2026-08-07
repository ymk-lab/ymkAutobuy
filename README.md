# qresearch — 研究取向量化回測框架

面向「研究 → 驗證 → paper → 再談實盤」的量化研究骨架：

- **Next-bar execution**：訊號在 t 產生，在 t+1 成交，降低 look-ahead
- **成本模型**：手續費 + 滑價（bps）
- **Regime hook**：波動率市況標籤
- **Walk-forward + 參數搜尋**：train 調參、OOS 驗收
- **多資產風險預算**：反向波動加權、毛曝險、波動目標
- **PaperBroker**：與回測同一套權重／成本假設，可對齊驗證

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
python3 -m pytest -q
```

## 多資產 + 風險預算 + Paper 對齊

```python
from qresearch import MultiBacktestEngine, CostModel, RiskBudgetConfig
from qresearch.data import generate_synthetic_panel, panel_close
from qresearch.strategy.multi import CrossSectionalMomentumStrategy
from qresearch.paper import replay_paper_from_weights

panel = generate_synthetic_panel(("AAA", "BBB", "CCC"), n=750)
engine = MultiBacktestEngine(
    cost_model=CostModel(fee_bps=1, slippage_bps=3),
    risk_config=RiskBudgetConfig(
        invert_vol=True, target_gross=1.0, target_vol=0.12, max_weight=0.45
    ),
)
result = engine.run(panel, CrossSectionalMomentumStrategy(lookback=20))
paper_eq = replay_paper_from_weights(
    result.weights, panel_close(panel),
    initial_capital=engine.initial_capital, cost_model=engine.cost_model,
)
```

多資產 CSV：把每個標的存成 `examples/data/panel/AAA.csv` 等形式，再用 `load_panel_csv_dir(...)`。

## CSV / Walk-forward

單資產 CSV 與參數搜尋見 `examples/run_csv_param_search.py`。

## 專案結構

```
src/qresearch/
  data/          # OHLCV、panel 載入／合成
  strategy/      # 單／多資產策略
  regime/        # 市況偵測
  portfolio/     # 風險預算配置
  backtest/      # 單／多資產引擎
  paper/         # Paper trading 對齊
  metrics/       # 績效指標
  validation/    # walk-forward、grid search
```

## 研究紀律

1. 訊號 `shift(1)` 後才進倉
2. 先看扣成本後績效
3. 參數只在 train 窗搜尋
4. Paper 與回測共用權重／成本假設，先對齊再接實盤

> 這是研究框架，不是保證獲利的交易機器人。
