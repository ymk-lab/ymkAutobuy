# qresearch — 研究取向量化回測框架

面向「研究 → 驗證 → 再談實盤」的單資產回測骨架，內建：

- **Next-bar execution**：訊號在 t 產生，在 t+1 open 成交，降低 look-ahead
- **成本模型**：手續費 + 滑價（bps）
- **Regime hook**：波動率市況標籤，策略可依市況降倉／空手
- **Walk-forward + 參數搜尋**：每折只在 train 調參，再用 OOS 驗收

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
python3 -m pytest -q
```

## CSV 資料接線

```python
from qresearch.data import load_ohlcv_csv, save_ohlcv_csv

data = load_ohlcv_csv("examples/data/sample_ohlcv.csv")
# 支援 Date/Open/... 別名，或 parse_index=True
```

把你的行情存成包含 `datetime,open,high,low,close,volume` 的 CSV 即可直接替換路徑。

## Walk-forward 參數搜尋

每折只在 **train** 上做 grid search（預設最大化 Sharpe），再用選出的參數跑 **OOS test**：

```python
from qresearch import BacktestEngine, CostModel
from qresearch.data import load_ohlcv_csv
from qresearch.strategy.examples import RegimeAwareTrendStrategy
from qresearch.validation import walk_forward_grid_search

data = load_ohlcv_csv("examples/data/sample_ohlcv.csv")
engine = BacktestEngine(cost_model=CostModel(fee_bps=1, slippage_bps=3))

wf, selections = walk_forward_grid_search(
    data,
    strategy_builder=lambda p: RegimeAwareTrendStrategy(
        fast=p["fast"], slow=p["slow"], high_vol_weight=p["high_vol_weight"]
    ),
    engine=engine,
    param_grid={"fast": [5, 10], "slow": [30, 40], "high_vol_weight": [0.0, 0.25]},
    train_size=252,
    test_size=63,
)
print(selections)          # 每折選到的參數
print(wf.combined_stats)   # 串接後的 OOS 績效
```

## 專案結構

```
src/qresearch/
  data/          # OHLCV 載入／存檔、合成資料
  strategy/      # Strategy 介面與範例
  regime/        # 市況偵測
  backtest/      # 引擎與成本
  metrics/       # Sharpe / MDD / turnover 等
  validation/    # walk-forward、grid search
```

## 研究紀律（刻意保留的限制）

1. 訊號必須 `shift(1)` 後才進倉，禁止同 bar 偷看未來
2. 先看 **扣成本後** 的績效，再談 alpha
3. 參數調優只在 train 窗，用 walk-forward 看 OOS
4. Regime 邏輯先做可解釋規則；模型之後再接

## 下一步

1. 加入多資產組合與風險預算
2. Paper trading 對齊同一套訊號／成本假設

> 這是研究框架，不是保證獲利的交易機器人。
