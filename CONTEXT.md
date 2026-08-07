# Quant Research Trading

研究與可實盤對齊的量化交易決策：先爭取報酬勝過同一標的買進持有，再壓低回撤。

## Language

**Success Criterion**:
第一優先：評估窗總報酬高於同一標的買進持有；第二優先：在勝過（或最接近勝過）基準的前提下，最大回撤盡量淺。
_Avoid_: 回撤好看但明顯少賺、只優化 Sharpe、防禦型少虧就算成功

**Buy and Hold**:
對同一標的全程滿倉持有、作為比較基準的被動策略（大盤／標的本身）。
_Avoid_: 換成不同標的當基準卻聲稱打敗大盤

**Priority Metric**:
排序時先看 `total_return - buy_hold_return`（越大越好，目標 > 0）；同分或同層再看最大回撤（越淺越好）。
_Avoid_: 先看 Sharpe／先看回撤再看報酬

**Primary Universe**:
第一版以單一寬基股指 ETF（QQQ）驗證能否勝過其買進持有；個股／產業 ETF 作外樣壓力測試。
_Avoid_: 一開始就上多資產全集

**Research-Live Parity**:
回測規則必須能原樣用於實盤：無未來函數、有明確再平衡與成本假設。
_Avoid_: 純紙上優化、看著未來調參

**Primary Instrument**:
第一版主要交易標的為 QQQ。
_Avoid_: 第一版混用多標的共用同一套未驗證參數

**BeatBench Book**:
預設滿倉參與上漲；只在高置信度風險訊號出現時減倉或空手；風險解除後盡快回到滿倉。
_Avoid_: 常態 Soft Vol 縮倉、核心地板強制留倉、以少虧為主的 CoreSat 預設

**Risk-Off Trigger**:
減倉條件必須同時具備「趨勢破壞」色彩（例如跌破長期均線）或「嚴重波動＋中期均線破壞」；禁止僅因短窗波動升高就大幅降倉。
_Avoid_: 單一高波動開關反覆砍倉、MA20 過於敏感的日常進出

**Fast Re-Entry**:
空手或減倉後，用比出場更快的條件回到滿倉（例如站回中期均線），避免踏空反彈。
_Avoid_: 出場與進場用同一條慢均線導致晚進

**No Leverage**:
目標權重介於 0% 到 100%，不使用槓桿。若無槓桿仍長期無法勝過基準，應檢討進出場而非加槓桿掩蓋。
_Avoid_: 用槓桿硬追買進持有報酬

**Legacy Core-Satellite**:
70/30 Soft Vol CoreSat／RegimeCoreSat 保留作對照與防禦研究，不再作為預設成功路徑。
_Avoid_: 把舊防禦書的 Sharpe 優勢當成已達成新成功標準

**Execution Cost**:
交易成本按富途牛牛美股固定式收費估算，外加 3 bps 滑價；權重變動設 2% 調倉門檻（進場／清倉除外）。
_Avoid_: 零成本、無視最低收費的每日微調

**Rebalance Cadence**:
收盤決策、次日開盤執行（next-bar）。
_Avoid_: 同根 K 線成交、無成本假設
