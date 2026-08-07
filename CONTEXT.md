# Quant Research Trading

研究與可實盤對齊的量化交易決策：在可控風險下，爭取優於單純買進持有的結果。

## Language

**Success Criterion**:
在相近風險（尤其最大回撤或波動）下，報酬優於同一標的的買進持有；較低回撤若伴隨明顯少賺且無法用加碼補回，不算成功。
_Avoid_: 只看最大回撤變小、只看勝率、只看單一空頭月表現

**Buy and Hold**:
對同一標的全程滿倉持有、作為比較基準的被動策略。
_Avoid_: 基準、大盤（除非已指明指數本身）

**Risk-Adjusted Outperformance**:
策略在回撤或波動與買進持有相近時，仍有更高報酬；或報酬略低但風險大幅下降且可透過提高曝險追上。
_Avoid_: 單純降曝險、防禦型、少虧就算贏

**Primary Universe**:
第一版只交易單一寬基股指 ETF，用來驗證規則是否優於該 ETF 的買進持有。
_Avoid_: 一開始就上個股籃子、多資產全集

**Research-Live Parity**:
回測規則必須能原樣用於實盤：無未來函數、有明確再平衡與成本假設；允許先研究，但不接受「事後才改成長抱」的規則。
_Avoid_: 純紙上優化、看著未來調參

**Primary Instrument**:
第一版唯一交易標的為 QQQ。
_Avoid_: 第一版混用個股或多 ETF

**Core-Satellite Book**:
總資金拆成核心帳本與衛星帳本；核心以參與長期上漲為主，衛星負責擇時或風險調節。
_Avoid_: 全倉單一訊號策略、純择時取代長抱

**Soft Vol Overlay**:
對核心倉位做輕量波動縮放：高波動時降低但不歸零，低波動時回到核心目標權重。
_Avoid_: 高波動強制空手、0/1 開關式避險

**Priority Metric**:
評估時先看 Sharpe；在 Sharpe 可接受的前提下，再盡力壓低最大回撤。
_Avoid_: 只優化最大回撤、只優化絕對報酬

**No Leverage**:
第一版目標權重介於 0% 到 100%，不使用槓桿。
_Avoid_: 用槓桿硬追買進持有報酬

**Core Weight**:
核心帳本目標佔總資金 70%。
_Avoid_: 核心低於一半（那會變成擇時主導）

**Satellite Weight**:
衛星帳本目標佔總資金 30%；可由其自身規則降到 0。
_Avoid_: 衛星與核心共用同一進出開關

**Core Floor**:
Soft Vol Overlay 作用下，核心曝險不得低於核心目標的 50%（即總資金約 35% 的市場曝險下限來自核心）。
_Avoid_: 核心歸零

**Satellite Strategy**:
衛星使用 S12 全倉規則（regime交叉，訊號開=衛星滿倉，不加 RS；因為標的即 QQQ）。
_Avoid_: 對 QQQ 使用以 QQQ 為基準的 RS 過濾

**Rebalance Cadence**:
帳本目標權重依收盤計算，於下一交易日開盤執行（next-bar）；衛星 S12 每日決策，核心 Soft Vol 縮放預設週調（見 Soft Vol Cadence）。
_Avoid_: 同根 K 線成交、無成本假設

**Soft Vol Cadence**:
核心 Soft Vol 縮放係數預設每週重算一次（週五為界），週內持有該週首值；衛星訊號仍可每日翻轉。
_Avoid_: 無證據地把 Soft Vol 改回日頻、為降交易成本而改動衛星決策頻率

**Soft Vol Target**:
核心 Soft Vol Overlay 使用近 20 日年化實現波動，目標波動 15%；縮放係數限制在 [0.5, 1.0]。
_Avoid_: 目標波動設與 QQQ 長期中位相同導致幾乎不降倉

**Execution Cost**:
交易成本按富途牛牛美股固定式收費估算，外加 3 bps 滑價；不使用「免佣」假設。權重變動另設 2% 調倉門檻（進場／清倉除外），以降低最低收費侵蝕。
_Avoid_: 零成本、只計 1bps 示意費用、無視最低收費的每日微調
