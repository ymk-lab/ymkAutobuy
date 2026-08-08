# Market Regime Label → Strategy Playbooks

在 QQQ 主書上，用每日形勢標籤選擇策略書，而不是全年只跑 Emerging RS；成敗仍對 QQQ 買進持有，且切換帳必須經 Bake-Off 同時打贏 QQQ B&H 與純 ERS 才可落實。

**Status**: accepted (design); implementation gated on Bake-Off

## Settled in grill

### Round 1
- Success = vs QQQ B&H，其次最大回撤
- Labels = 完整集合（後定五類）
- Scope v1 = QQQ 主書 only
- Emerging RS + G1 = 僅作為 Rotation Playbook

### Round 2
- Five labels: Defense / Range / Rotation / CrowdedTrend / PanicRebound
- Provisional mapping must be tested before adoption
- Range = stop new entries; wind down prior playbook → Cash
- PanicRebound strategy later set to small QQQ sleeve (not Cash-only)

### Round 3
- Classifier = Regime Scorecard（打分取最高）；若效果差提示改回「先風險再型態」層級法
- Hysteresis = enter Defense immediate；leave Defense / switch attack labels with confirmation days
- CrowdedTrend = leadership overlap high AND already-strong share high
- Bake-Off pass = beat QQQ B&H AND pure ERS(G1)

### Round 4
- Leave Defense: N=5；attack↔attack: N=3
- Scorecard feature sketch + tie-break priority: Defense > PanicRebound > CrowdedTrend > Rotation > Range
- PanicRebound = max 30% QQQ
- Bake-Off controls = 切換帳 vs 純 ERS vs QQQ B&H vs 永遠 QQQ vs 永遠 Cash

## Considered Options
- Label = Gate only（只有能不能做多）：無法區分輪動 vs 集中強勢
- 全年 ERS：在 CrowdedTrend（如 SMH 類行情）系統性落後
- 層級法當 v1 預設：較可解釋，但使用者先選打分；保留降級路徑
- PanicRebound 滿倉或開 ERS：假反彈風險高，改 30% QQQ
