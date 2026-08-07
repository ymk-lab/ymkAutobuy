# Quant Research Trading

研究與可實盤對齊的量化交易決策：在 QQQ 成分宇宙中，於大盤上升時買入「剛轉強」個股，分批出場，並用餘資承接下一波；整本帳要勝過 QQQ 買進持有。

## Language

**Success Criterion**:
整本組合權益在評估窗的總報酬，必須高於同一期間 QQQ 買進持有；在打贏（或最接近打贏）的前提下，再比較最大回撤。
_Avoid_: 單檔打贏自己的買進持有卻整本輸給 QQQ、只優化 Sharpe、防禦型少虧就算成功

**Buy and Hold**:
對 QQQ 全程滿倉持有、作為組合成敗比較基準的被動策略。
_Avoid_: 換成不同標的當基準卻聲稱打敗大盤、用單檔個股 B&H 取代組合基準

**Priority Metric**:
排序時先看 `portfolio_return - qqq_buy_hold_return`（越大越好，目標 > 0）；同分或同層再看最大回撤（越淺越好）。
_Avoid_: 先看 Sharpe／先看回撤再看報酬、用平均單檔超額假裝打贏大盤

**Primary Universe**:
可交易標的為 QQQ 成分（Nasdaq-100）全日曆可交易名單；QQQ 本身是基準與大盤閘門，不是唯一持倉。
_Avoid_: 只交易 QQQ 本體、一開始就上無關寬基全集

**Market Regime Gate**:
允許新開倉的大盤狀態過濾器；具體定義（均線／報酬／新高等）保留為多版本，之後以同一規則其餘部分做比賽選定。
_Avoid_: 未開閘仍四處抄底、把閘門參數和選股參數混在同一輪亂調

**Emerging Relative Strength**:
進場標的必須是「剛剛相對 QQQ 轉強」：短窗（20 日）超額報酬由非正轉正，且長窗（60 日）尚未呈現長期大幅領先（避免已是強勢股）。
_Avoid_: 追已經長期領先的霸榜股、只看單日相對強度尖刺

**Persistence Confirm**:
進場前必須通過抗噪音確認：連續 3 個交易日短窗超額 > 0，且 10 日超額亦 > 0。
_Avoid_: 單日轉強立刻買、只用一個視窗

**Staged Exit**:
持倉用多重因素分批減倉／清倉，而不是一次全出或單一指標砍光。
_Avoid_: 單一均線全進全出、無因素權重的隨意分批

**Reserve Capital**:
未部署或出場釋放的資金，保留用來物色並承接下一波符合進場條件的標的。
_Avoid_: 強制滿倉、把餘資閒置卻不再掃描宇宙

**Research-Live Parity**:
回測規則必須能原樣用於實盤：無未來函數、有明確再平衡與成本假設。
_Avoid_: 純紙上優化、看著未來調參

**No Leverage**:
組合淨曝險介於 0% 到 100%，不使用槓桿。
_Avoid_: 用槓桿硬追買進持有報酬

**Execution Cost**:
交易成本按富途牛牛美股固定式收費估算，外加 3 bps 滑價；權重變動設 2% 調倉門檻（進場／清倉除外）。
_Avoid_: 零成本、無視最低收費的每日微調

**Rebalance Cadence**:
收盤決策、次日開盤執行（next-bar）。
_Avoid_: 同根 K 線成交、無成本假設

## Legacy (superseded defaults)

**Legacy BeatBench / SevereTrim / HoldHighDip / CoreSat**:
舊單標的進攻／防禦書，僅作對照，不再作為本輪成功路徑。
_Avoid_: 把舊書參數直接當成新多標的波段書的預設
