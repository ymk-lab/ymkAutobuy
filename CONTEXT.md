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

**Single-Name Slot**:
同一時間最多持有一檔個股；其餘符合條件者只當候補，不開第二倉。有空位（清倉後）才承接下一波。
_Avoid_: 多檔並行分散、未清倉就換倉或疊倉

**Staged Exit**:
持倉用多重因素兩階減倉：先出到半倉，再出清；因素為短窗超額轉負、跌破自身 SMA50、大盤閘門關閉、自高點回撤過深。
_Avoid_: 單一均線全進全出、無因素的隨意分批、第一版加時間停利

**Already-Strong Cap**:
60 日相對 QQQ 超額報酬已超過 +10% 者視為已是強勢股，禁止新開倉。
_Avoid_: 用宇宙排名當第一版過濾（對名單變更過敏感）

**Reserve Capital**:
未部署、半倉釋出、或清倉後的資金，保留掃描宇宙；但在 Single-Name Slot 仍被佔用時，不得用餘資開第二檔。
_Avoid_: 半倉期間用餘資疊第二標的、強制滿倉

**Evaluation Protocol**:
主賽評估：$50k 起始、自 2025-01-01 至資料末日、Futu+3bps、flat-start、next-bar、2% 調倉門檻；成敗對 QQQ 買進持有。
_Avoid_: 主賽窗內調參再報同一窗成績

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
