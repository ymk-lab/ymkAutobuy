# 預設進攻規則：SevereTrim + FastReentry（並保留 hysteresis 對照）

在「先贏基準、再談回撤」優先序下，鎖定可實作預設：

- 類別：`SevereTrimFastReentryStrategy`
- 滿倉為常態
- 風險：高波動且跌破 MA100，或收盤連續 2 日跌破 MA200 → 降到 50%
- 回滿倉：站回 MA50

Walk-forward（QQQ，先前 2 年調參 → 次年 OOS）顯示：每年重選參數容易過擬合；**固定預設**在 2021–2026 各年扁平複利上略優於買進持有，主要超額來自 2022 避險年。主窗 2025 仍可能小輸基準，但回撤較淺。

另保留 `BeatBench hysteresis(MA200 出 / MA50 進)`：2020→今窗曾明顯勝過基準，作並行候選，不因單一主窗小輸就丟棄。

**Status**: accepted
