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
某一本策略書內部的「可否新開倉」過濾器（如 Emerging RS 書的 G1=QQQ>SMA50）；不是整帳的形勢分類本身。
_Avoid_: 把 Gate 當成唯一的大盤形勢、未開閘仍四處抄底、把閘門參數和選股參數混在同一輪亂調

**Market Regime Label**:
每日（收盤）賦予大盤／宇宙的形勢標籤，用來選擇要啟用哪一本策略書；v1 先在 QQQ 主書上運作，標籤數採較完整集合（約五類）。
_Avoid_: 與 Market Regime Gate 混稱、用盤中即時標籤做回測未來函數

**Strategy Playbook**:
某一形勢下啟用的完整進出場規則集合。形勢切換時換的是 Playbook，不是只改一個參數。
_Avoid_: 同一套 Emerging RS 參數硬跑所有形勢、把「換宇宙」和「換形勢」混為一談

**Rotation Playbook**:
輪動形勢下使用的策略書：Emerging Relative Strength + 其 Market Regime Gate（預設 G1）。僅在標籤判定為輪動時啟用。
_Avoid_: 集中強勢或防守期仍強制跑 Emerging RS

**Defense / Range / Rotation / CrowdedTrend / PanicRebound**:
v1 五個 Market Regime Label。Defense=風險關閉；Range=震盪區間；Rotation=領導輪動；CrowdedTrend=少數龍頭集中領漲；PanicRebound=急跌後的恐慌反彈。
_Avoid_: 把 CrowdedTrend 叫成「強勢股選股」、把 PanicRebound 直接當成新牛市

**Playbook Assignment (provisional)**:
標籤到策略書的暫時對應，必須經 Bake-Off 驗證後才可落實：Defense→Cash；Range→停新開、舊倉按原書出場後歸 Cash；Rotation→Rotation Playbook；CrowdedTrend→QQQ 買進持有／趨勢滿倉；PanicRebound→最多 30% QQQ 短反彈。
_Avoid_: 未比較績效就上實盤、測試窗內調參再報同一窗為成功、恐慌期滿倉搶反彈

**Regime Scorecard**:
以多因子打分選當日最高分標籤；若 Bake-Off 顯示打分效果明顯差於「先風險再型態」層級法，應提示改回層級法。
_Avoid_: 無對照就堅持打分、把分數當未來函數用未完成日資料

**Regime Hysteresis**:
進入 Defense 可立即切換；離開 Defense 須連續確認 5 個交易日；攻擊標籤（Range／Rotation／CrowdedTrend／PanicRebound）之間切換須連續確認 3 個交易日。
_Avoid_: 每日無遲滯亂跳標籤導致過度交易

**CrowdedTrend Test**:
判定集中強勢須同時滿足：領導榜穩定（近20日與近60日 Top-K 重疊高）且已強股占比高（60日超額>Already-Strong Cap 的家數占比高）。
_Avoid_: 只看指數漲得快就當 CrowdedTrend

**Playbook Bake-Off**:
在同一評估協議下，形勢切換帳必須同時打贏 QQQ 買進持有與純 Emerging RS（Rotation-only），才可晉升為預設；並比較最大回撤。
_Avoid_: 只贏其中一個就上線、只看單一形勢片段、沒有對照組就宣稱較優

**Structure Gate**:
與代號無關的日頻主路由：用領導股相對基準的落後／超額判斷個股強或指數強。若出現「指數強勢期」關鍵特徵（60 日領導股明顯落後、指數在均線上且動能為正，並經確認日），則在期內持續做多基準 ETF，直到領導股追上或跌破均線／重度防守才退出。另有「指數推力」復甦套筒（見下）。非黏著期：個股強→買個股（Crowded 用 already-strong，否則 ERS）；短暫指數偏強也可持 ETF。同一規則套用所有宇宙。
_Avoid_: 為每個 ETF 代號寫死不同閾值、指數強勢期日頻進出指數、用未來報酬標註當天

**Index Thrust**:
基準本身的絕對大漲／復甦訊號（短窗報酬、自近低反彈、站回 SMA50），與「領導股相對落後」的 Sticky 正交。觸發時強制 hold_bench，並可覆蓋仍滯後的 dd60 harsh，避免防守後錯過指數補漲。
_Avoid_: 用推力取代領導位置判斷、在 ret20 仍急跌時當推力、為單一 ETF 寫死閾值

**Stock-Led / Index-Led**:
領導位置：Stock-Led＝強勢個股近期贏過基準→偏買個股；Index-Led／Sticky Index-Strong＝基準更強、領導股相對落後→偏買／黏著做多大盤 ETF；Index Thrust＝基準絕對急漲時也可偏 ETF。
_Avoid_: 用未來報酬標註當天、把「指數漲得快」誤當成 CrowdedTrend

**Structure Soft Pass**:
通用規則可接受略輸「該宇宙專用最優」：須打贏較差的那條基線（B&H 與純 ERS 之較差者），且落後較優基線不超過約定差距（預設 35pp）；硬過關仍是同時打贏兩者。
_Avoid_: 用軟過關取代硬過關卻不標明、差距門檻在測試窗內事後放寬再宣稱成功

**Emerging Relative Strength**:
進場標的必須是「剛剛相對 QQQ 轉強」：短窗（20 日）超額報酬由非正轉正，且長窗（60 日）尚未呈現長期大幅領先（避免已是強勢股）。
_Avoid_: 追已經長期領先的霸榜股、只看單日相對強度尖刺

**Persistence Confirm**:
進場前必須通過抗噪音確認：連續 3 個交易日短窗超額 > 0，且 10 日超額亦 > 0。
_Avoid_: 單日轉強立刻買、只用一個視窗

**Single-Name Slot**:
同一時間最多持有一檔個股；進場目標權重 100%；其餘符合條件者只當候補。席位被佔用（含半倉）時不得開第二檔；清倉後才承接下一波。
_Avoid_: 多檔並行、半倉用餘資疊第二標的、未清倉就換倉

**Slot Tie-Break**:
同一日多檔通過進場條件時，選 20 日相對 QQQ 超額報酬最高者進入唯一席位。
_Avoid_: 按字母序、先看成交額（第二版再議）

**Staged Exit**:
兩階減倉。滿倉時：20 日超額轉負或收盤跌破 SMA50 → 減半；自進場高點回撤 ≥10% 或大盤閘門關閉 → 清倉。已半倉時：超額轉負或破 SMA50 或回撤≥10% 或閘門關 → 清倉。
_Avoid_: 閘門關閉只減半、破線直接跳過半倉階、第一版加時間停利

**Already-Strong Cap**:
60 日相對 QQQ 超額報酬已超過 +10% 者視為已是強勢股，禁止新開倉。
_Avoid_: 用宇宙排名當第一版過濾（對名單變更過敏感）

**Reserve Capital**:
未部署或半倉／清倉釋出的資金保留掃描；席位佔用期間不得開第二檔。
_Avoid_: 強制滿倉、半倉疊倉

**Market Gate Contest**:
主賽在其餘規則固定下比較閘門 G1–G4：G1=QQQ>SMA50；G2=G1且SMA50>SMA200；G3=QQQ 20日報酬>0；G4=G1且G3。
_Avoid_: 第一輪加入過嚴的 55 日新高閘門、一邊改選股一邊改閘門

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
