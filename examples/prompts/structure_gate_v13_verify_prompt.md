# Structure Gate v13 — AI 驗證 Prompt

把下方「可複製區塊」整段貼給另一個 AI（或同一個新對話），請它獨立驗證參數合理性、風險與建議，**不要改 production 預設**，除非有多窗證據。

來源：`StructureGateConfig.v13()` + `V13_BOOK_WEIGHTS`  
機器可讀完整表：同目錄 `structure_gate_v13_params.json`

---

## 可複製區塊（從此處開始）

````markdown
# 任務：驗證 Structure Gate v13 參數（研究 / 紙上交易）

你是量化策略審稿人。請**獨立驗證**下列 v13 參數是否自洽、是否過度擬合、何處脆弱，並給出可執行的驗證計畫。  
不要因為「已經回測賺錢」就默認正確。不要改寫程式；先給審核結論。

## 1. 系統是什麼

Structure Gate 是 universe-agnostic 的日頻 regime 閘門，輸出四種 mode：

- `cash` | `ers` | `strong` | `bench`

**Locus**：`stock_led` | `index_lean` | `neutral`  
**Sleeves**：`sticky` | `thrust` | `crowded`  
**Defense**：`mild` | `harsh_dd` | `harsh_ret` | `mild_top`

**優先序（高者蓋過低者）**：
```
harsh_ret > thrust > sticky > harsh_dd > reentry > mild > index_lean
> stock_led+crowded > ers > cash
```

**Production 紙上交易預設**：
- Preset：`StructureGateConfig.v13()`
- 權重：`SPY 50% / QQQ 50%`（`V13_BOOK_WEIGHTS`）
- 成交假設：次日 open；研究成本 Futu fees + 約 3bps slippage
- 雙窗 trail：短 `leadership_trail_days=20`，長 `sticky_trail_days=60`（20/60）
- sticky 進場另要求 `above SMA50`（`sticky_require_above50=True`）——這是價格相對 SMA50，**不是**把長 trail 改成 50

## 2. v13 相對 v8 的「顯式覆寫」（調參結果）

36-trial random tune（seed=13），窗：
- 2023-01-01 → 2024-01-01
- 2025-08-07 → 2026-08-07

| knob | v8 default | **v13** | 角色 |
|--|--|--|--|
| `mode_hysteresis_enabled` | false | **true** | 軟切換用 trail 遲滯 |
| `mode_enter_trail` | 0.025 | **0.035** | bench/cash→ers/strong 需 trail≥+3.5% |
| `mode_exit_trail` | -0.01 | **-0.015** | ers/strong→bench 需 trail≤−1.5% |
| `mode_switch_cooldown_days` | 2 | **3** | 軟切換冷靜期（日） |
| `risk_override_enabled` | false | **true** | 允許風控穿透到 cash |
| `risk_override_stock_1d` | 0.08 | **0.08** | 持倉個股 1 日跌 ≥8% → 強平路徑 |
| `mild_defense_dd` | 0.06 | **0.06** | mild DD 門檻 |
| `mild_defense_ret20` | -0.04 | **-0.05** | mild 20d 報酬門檻（更鬆一點才觸發？注意符號：≤ −5%） |
| `harsh_defense_dd` | 0.18 | **0.20** | harsh DD（更深才 harsh） |
| `harsh_defense_ret20` | -0.12 | **-0.12** | harsh 20d |
| `stock_led_min_trail` | 0.025 | **0.03** | stock_led 門檻 |
| `index_lean_max_trail` | -0.025 | **-0.03** | index_lean 門檻 |
| `sma50_hysteresis` | 0.0 | **0.0** | 無 SMA50 帶寬 |
| `mode_enter_immediate` | false | **false** | 必須過 enter trail |
| `mode_min_hold_days` | 0 | **0** | 無最短持有 |

其餘 knob **繼承 v8 defaults**（完整表見第 4 節）。

## 3. 機制要點（審核時必須對齊）

1. **Mode 遲滯（主）**：`leader_vs_bench_trail`（預設 20 日累積超額）  
   - 進 ers/strong：`trail >= mode_enter_trail`  
   - 出到 bench：`trail <= mode_exit_trail`  
2. **冷靜期（輔）**：`mode_switch_cooldown_days` 約束 ers/strong ↔ bench 軟切換  
3. **風控穿透**：`harsh_ret` / `harsh_dd` 可立刻允許 cash；持倉 1d 崩跌穿透 stickiness  
4. **Sticky**：長 trail（60d）落後 +（可選）breadth beat 弱 → 鎖指數/禁個股袖口  
5. **Crowded / ers lag**：集中度、overlap、ERS 落後超額（60d 窗，觸發 −8%）可封鎖個股袖口  
6. **Strong**：已強勢領導（`strong_lookback=60`，`already_strong_cap=0.10`）

## 4. 完整 resolved 參數（v13 實際生效）

```json
{
  "book_weights": {"SPY": 0.50, "QQQ": 0.50},
  "top_k_conc": 3,
  "top3_conc_min": 0.35,
  "crowded_overlap_min": 0.45,
  "strong_share_min": 0.35,
  "strong_overlap_min": 0.45,
  "ers_lag_lookback": 60,
  "ers_lag_trigger": -0.08,
  "already_strong_cap": 0.10,
  "strong_lookback": 60,
  "leadership_trail_days": 20,
  "stock_led_min_trail": 0.03,
  "index_lean_max_trail": -0.03,
  "sticky_trail_days": 60,
  "sticky_enter_trail": -0.06,
  "sticky_enter_confirm": 2,
  "sticky_exit_trail": -0.02,
  "sticky_exit_confirm": 6,
  "sticky_require_above50": true,
  "sticky_require_ret20_pos": false,
  "sticky_breadth_max": 0.50,
  "sticky_breadth_trail": -0.12,
  "sticky_exit_on_below50": false,
  "sticky_forbid_stock_sleeves": true,
  "thrust_ret5_min": 0.04,
  "thrust_ret10_min": 0.07,
  "thrust_bounce20_min": 0.06,
  "thrust_ret20_min": 0.08,
  "thrust_require_above50": true,
  "thrust_confirm": 1,
  "thrust_overrides_dd_harsh": true,
  "thrust_force_bench": true,
  "mild_defense_dd": 0.06,
  "mild_defense_ret20": -0.05,
  "harsh_defense_dd": 0.20,
  "harsh_defense_ret20": -0.12,
  "sma50_hysteresis": 0.0,
  "mild_vol_adaptive": false,
  "mild_vol_lookback": 60,
  "mild_vol_dd_k": 2.5,
  "mild_vol_ret20_k": 2.0,
  "mild_top_enabled": false,
  "mild_top_breadth_max": 0.30,
  "mild_top_breadth_confirm": 3,
  "mild_top_down_vol_k": 1.0,
  "mild_top_down_confirm": 3,
  "mild_top_volume_ratio": 1.5,
  "reentry_force_bench": false,
  "reentry_ret5_min": 0.03,
  "reentry_ret10_min": 0.05,
  "reentry_bounce20_min": 0.05,
  "bench_slippage_bps": 3.0,
  "stock_slippage_bps": 3.0,
  "book_peak_dd_stop": null,
  "book_dd_reentry_confirm": 3,
  "mode_hysteresis_enabled": true,
  "mode_enter_trail": 0.035,
  "mode_exit_trail": -0.015,
  "mode_switch_cooldown_days": 3,
  "risk_override_enabled": true,
  "risk_override_stock_1d": 0.08,
  "mode_enter_immediate": false,
  "mode_min_hold_days": 0
}
```

## 5. 已知回測證據（供交叉檢查，非真理）

### A) v13 vs v11（調參窗；權重當時 SPY40/QQQ30/SMH30）
- 2023：v13 +73.5% vs v11 +27.9%（大幅改善）
- 2025-08→2026-08：v13 +113.4% vs v11 +98.1%

### B) Production 權重 SPY50/QQQ50，窗 2025-08-07→2026-08-13
| preset | 長窗 | Blend | 備註 |
|--|--|--|--|
| **v13** | **60** | **+102.6%** | paper 基準 |
| v14 | 60 + 立刻進場/最短持有 | +86.4% | −16pp |
| v15 | **50** | +44.2% | −58pp；QQQ sticky 減半、whipsaw |
| v16 | **70** | +106.8% | +4pp；SPY 大贏、QQQ 明顯變差 |

觀察假設（請你挑戰）：
- 把長窗貼近大眾 **MA50** 共識（v15）會破壞 sticky 濾波。
- 再拉長到 70（v16）blend 略好但袖口不穩，單一窗不能當升級依據。

## 6. 請你輸出的審核格式

請用繁體中文，嚴格按下列結構回答：

### A. 一句話判決
`通過 / 有條件通過 / 不通過` + 一句理由。

### B. 參數自洽性（逐組）
至少檢查：
1. 20/60 雙窗與 SMA50 sticky 是否角色重疊或衝突  
2. enter/exit trail 不對稱是否合理  
3. mild vs harsh 門檻間距是否過窄/過寬  
4. sticky enter/exit confirm（2 vs 6）是否偏「難進易出」或相反  
5. crowded / ers_lag / strong 門檻是否可能同時過鬆導致鎖死個股  
6. thrust 蓋過 harsh_dd 的優先序風險  
7. `book_peak_dd_stop=null` 是否可接受  
8. SPY50/QQQ50 是否放大 QQQ 特有失敗模式  

每組：`OK / 疑慮 / 高風險` + 一句機制理由。

### C. 過度擬合風險
- 哪些 knob 最像「對調參窗量身」？  
- 哪些該凍結為結構常數、哪些才允許再搜？

### D. 必做驗證實驗（最多 5 個，按優先）
每個實驗寫：目標、改哪個參數/窗、成功/失敗判準、預期失效模式。  
禁止空想；要能用現有 bakeoff 腳本思路落地。

### E. 若只能改 0～2 個 knob
你會改什麼？或不改？為什麼？  
明確寫：**不要為了單一窗小幅勝出而換掉 v13 production。**

### F. 紅旗清單
列出若實盤/紙上出現哪些現象，應立刻回滾或停用相關 sleeve。
````

## 可複製區塊（到此結束）

---

## 本機用法

```bash
# 把 prompt 印到剪貼簿流程（自行複製檔案）
less examples/prompts/structure_gate_v13_verify_prompt.md

# 參數 JSON
cat examples/prompts/structure_gate_v13_params.json
```

從程式匯出（環境有 pandas 時）：

```bash
PYTHONPATH=src python3 - <<'PY'
from dataclasses import fields
from qresearch.strategy.structure_gate import StructureGateConfig, V13_BOOK_WEIGHTS
cfg = StructureGateConfig.v13()
out = {f.name: getattr(cfg, f.name) for f in fields(cfg) if f.name != "ers_config"}
out["book_weights"] = dict(V13_BOOK_WEIGHTS)
print(out)
PY
```
