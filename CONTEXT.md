# Quant Research Trading

研究與可實盤對齊的量化交易決策。研究詞彙（下方 Language）仍描述 QQQ 成分輪動書；**可送單的生產帳本只有 Structure Gate v13**。

## Production Language

**Production Book**:
唯一准產生可送單目標的帳本：Structure Gate v13。袖口基準固定 QQQ 50% / SPY 50%。
_Avoid_: 把 v11／v14–v17／Emerging RS／舊 Core-Sat 當可送單

**Sleeve Benchmark**:
無個股時的基準配比；生產鎖定 QQQ 50% / SPY 50%。人手不可改配比，只可改名義。
_Avoid_: 權重、倉位、策略參數、Mode Overlay

**Sleeve Notional**:
這本帳用來計算目標股數的美元名義。預設為 Notional Cap 與帳戶權益的較小值。變更只作用於下一轉 Signal。
_Avoid_: 用整戶權益自動加碼、把名義當成即時現倉、改完名義就改已鎖定的 Locked Plan

**Notional Cap**:
操作者設定的名義上限（例如 2 萬或 5 萬）。MAX 表示「用當前規則算到的最大名義」，不是購買力。
_Avoid_: MAX = 購買力、MAX = 現金

**Buying-Power Cap**:
經確認後，用購買力代替權益代入 min(Cap, …) 的可選名義規則。預設關閉。開啟是下一轉 Signal，並不自行下融資單型。
_Avoid_: 靜默用購買力、把戶口已開融資當成系統已開 Buying-Power Cap

**Mode Overlay**:
v13 在 ers／strong 時對領導股與 ETF 的分配。由 Production Book 輸出，不是網頁滑桿。
_Avoid_: 與 Sleeve Benchmark 混稱、人手改 Overlay 卻叫改基準

**Signal**:
收市後按當前 Sleeve 輸入跑 v13、寫出 Locked Plan 的步驟。生產定在美東 16:30。
_Avoid_: 與 Once 混稱、盤中重算當 Signal

**Locked Plan**:
Signal 寫下、Once 唯一可送的目標檔。寫好之後不可用新名義或新 mode 重算。
_Avoid_: ৴0 現場重算、把網頁上看到的權重當成已鎖定

**Once**:
把 Locked Plan 送去券商的執行窗；生產定在美東 09:40。
_Avoid_: 開盤、09:30、盤中再平衡、現場重跑 v13

**Next-Signal**:
Sleeve Notional、Notional Cap、Buying-Power Cap 的變更只進下一轉 Signal，再由那份新 Locked Plan 的 Once 執行。
_Avoid_: 改完名義朝早就按新名義加減倉

**Next-Once**:
Trading Environment 與 Submit Gate 的變更影響下一轉 Once，不改已鎖定的目標內容，也不重打當前窗已在飛的單。
_Avoid_: 即開 REAL 就重打今日單、盤中按新名義加倉

**Submit Gate**:
是否允許 Once 送單的開關。關閘仍可算 Signal。網頁可關；開 REAL 另見 Trading Environment。
_Avoid_: 用「切換送單」兼指改策略

**Trading Environment**:
富途 SIMULATE 或 REAL。預設 SIMULATE。REAL 需要伺服器 ALLOW_LIVE 鎖加上網頁確認；網頁不能自己打開 ALLOW_LIVE。
_Avoid_: paper／示範盤／內部 PaperBroker 互代

**Confirm Action**:
改 REAL、Flatten、開 Submit Gate、開 Buying-Power Cap 時，要在已有 token 之外再確認一次。
_Avoid_: 單一 token 就能做危險動作

**Alert Channel**:
Freeze 與 Once 失敗的通知走 email。
_Avoid_: 只寫 log 當已通知、與 Telegram 混稱

**Freeze**:
執行或營運失敗後停止再送單，不自動補腳去貼近目標。解除要人手。觸發：OpenD 斷或登入失效；Once 任一腳失敗或超時；預覽與成交對帳不符；單筆滑價超過 50bps；Signal asof 不是上一完整美股交易日；REAL 但 ALLOW_LIVE 關著。
_Avoid_: 重試到成交完、把部分成交當成功

**Flatten**:
撤未完成單，把 Production Book 出現過的標的收到現金，並關 Submit Gate。一鍵只清本書；清整戶美股要第二次確認。
_Avoid_: 當成 v13 的 cash mode、當成只改名義

**Rebalance Band**:
目標權重與現倉權重偏離未滿 2% 時，Once 不出單。進場、清倉、Flatten 不受此限。
_Avoid_: 用 1 股或 1 美元當門檻、把價格漂移當成新訊號

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
與代號無關的日頻主路由。每日輸出一個 Mode，決定持倉袖套；同一規則套用所有宇宙。
_Avoid_: 為每個 ETF 代號寫死不同閾值、用未來報酬標註當天、同一概念混用舊名（hold_bench／Index Thrust／黏著期等）

**Structure Priority**:
Mode 裁決由高到低：`harsh_ret` → `thrust` → `sticky` → `harsh_dd` → `mild` → `index_lean` → `stock_led`+`crowded` → `stock_led`／中性 `ers` → `cash`。高優先級覆蓋低優先級。
_Avoid_: 用舊 mask 直覺推斷、讓 `index_lean` 蓋過 Mild、Sticky ON 卻出現 `cash`

**Structure Universal Tune**:
在同一評估窗對多宇宙做參數搜尋時，以軟過關數為主、硬過關與 vs B&H 穩健統計為輔；入選預設須標明「窗內探索、非鎖定 OOS」。研究預設曾為 v8；生產帳本是 v13。
_Avoid_: 窗內調參後宣稱樣本外已驗證、為單一 ETF 單獨閾值、稱 v8 仍是可送單預設

**Book Peak DD Stop**:
帳本權益相對高峰回撤觸及門檻（變體常用 12%）→ 次日開盤清倉並暫停，直到非 cash 訊號連續確認日數後才允許再進場。因 next-open 執行，實現最大回撤可能略差於門檻（隔夜缺口）。
_Avoid_: 當成同根 K 線內保證回撤上限、與個股 peak_dd_stop 混稱

**Structure Mode**:
四種日頻持倉模式（程式字串＝文件名）：`cash`＝空手防守；`ers`＝新興轉強；`strong`＝已強領導；`bench`＝基準滿倉。
_Avoid_: 寫 hold_bench／hold_strong、中英混稱而不標 mode 名

**Structure Locus**:
領導位置（短窗 trail20）：`stock_led`＝個股領漲→偏 `ers`／`strong`；`index_lean`＝指數偏強→僅在非 Mild／非 Harsh 時偏 `bench`；其餘中性→risk_on 時走 `ers`。
_Avoid_: 與 Sticky／Thrust 混稱、破線仍因 index_lean 滿倉 ETF

**Sticky**（指數黏著）:
長窗領導股落後基準的狀態機袖套。ON 時鎖定 `bench`，忽略 Mild 與滯後 `harsh_dd`；`harsh_ret` 當日立刻結束 Sticky 並 `cash`。領導追上或 `harsh_dd` 持續確認後退出。
_Avoid_: Sticky ON 與 `cash` 並存、稱 Sticky Index-Strong／index_regime

**Thrust**（指數衝刺）:
基準絕對大漲／復蘇袖套（短窗報酬、自近低反彈、站回 SMA50），與 Sticky 正交。觸發時鎖定 `bench`，可覆蓋滯後 `harsh_dd`；`harsh_ret` 仍為空手。
_Avoid_: 用推力取代 Locus、在 ret20 仍急跌時當 Thrust

**Crowded** *(Structure)*（集中領漲）:
Structure Gate 內集中結構旗標；在 `stock_led` 且 risk_on 時把 mode 從 `ers` 升級為 `strong`。不同於五類標籤的 CrowdedTrend。
_Avoid_: 與 CrowdedTrend Label 混稱

**Mild / Harsh**（輕度／重度防守）:
`mild`＝破 SMA50 或溫和轉弱→在 Sticky／Thrust 鎖之外偏 `cash`（也擋 `index_lean`）。`harsh_dd`＝深回撤→鎖外 `cash`；鎖內（Sticky／Thrust）可被覆蓋。`harsh_ret`＝ret20 急跌→最高優先 `cash`，並立刻打斷 Sticky。
_Avoid_: 與五類 Defense Label 混稱、Mild 被 index_lean 靜默蓋過

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
預設名義規則下，本書按權益而非購買力計曝險，淨曝險目標介於 0% 到 100%。Buying-Power Cap 是經確認的例外，不是預設。
_Avoid_: 未確認就用購買力加碼、用機桿硬追買進持有報酬

**Execution Cost**:
交易成本按富途牛牛美股固定式收費估算，外加 3 bps 滑價；權重變動設 2% 調倉門檻（進場／清倉除外）。
_Avoid_: 零成本、無視最低收費的每日微調

**Rebalance Cadence**:
收盤決策、次日開盤執行（next-bar）。生產成交窗是 Once（09:40 ET），不是 09:30。
_Avoid_: 同根 K 線成交、無成本假設、稱開盤即 Once

## Legacy (superseded defaults)

**Legacy BeatBench / SevereTrim / HoldHighDip / CoreSat**:
舊單標的進攻／防禦書，僅作對照，不再作為本輪成功路徑。
_Avoid_: 把舊書參數直接當成新多標的波段書的預設
