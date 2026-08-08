(() => {
  const MODE_COPY = {
    cash: "空手防守：結構轉弱或不在 risk-on 時持有現金，等待下一根明確訊號。",
    ers: "新興轉強：風險開、非指數偏強時，持有剛相對基準轉強的個股（G1 ERS）。",
    strong: "已強領導：個股領漲且結構集中（crowded）時，升級持有確認過的領導股。",
    bench: "基準滿倉：Sticky／Thrust／指數偏強時，滿倉基準 ETF，避免選股落後指數。",
  };

  const PARAM_META = [
    ["sticky_enter_trail", "Sticky 進場：領導股 60 日超額落後門檻"],
    ["sticky_enter_confirm", "Sticky 進場確認日數"],
    ["sticky_exit_trail", "Sticky 出場：落後收斂門檻"],
    ["sticky_exit_confirm", "Sticky 出場確認日數"],
    ["sticky_require_above50", "Sticky 需站上 SMA50"],
    ["thrust_ret5_min", "Thrust：5 日報酬門檻"],
    ["thrust_ret10_min", "Thrust：10 日報酬門檻"],
    ["thrust_bounce20_min", "Thrust：20 日自低反彈門檻"],
    ["thrust_ret20_min", "Thrust：20 日報酬門檻"],
    ["thrust_require_above50", "Thrust 需站上 SMA50"],
    ["mild_defense_dd", "Mild：60 日回撤門檻（絕對值）"],
    ["mild_defense_ret20", "Mild：20 日報酬門檻"],
    ["harsh_defense_dd", "Harsh DD：60 日回撤門檻"],
    ["harsh_defense_ret20", "Harsh Ret：20 日急跌門檻"],
    ["stock_led_min_trail", "個股領漲 trail20 門檻"],
    ["index_lean_max_trail", "指數偏強 trail20 門檻"],
    ["bench_slippage_bps", "ETF 滑價（bps）"],
    ["stock_slippage_bps", "個股滑價（bps）"],
  ];

  function fmt(v) {
    if (typeof v === "boolean") return v ? "true" : "false";
    if (typeof v === "number") {
      if (Number.isInteger(v)) return String(v);
      return String(v);
    }
    if (v == null) return "—";
    return String(v);
  }

  function setMode(mode) {
    document.querySelectorAll(".sg-mode").forEach((el) => {
      el.classList.toggle("is-active", el.dataset.mode === mode);
    });
    const detail = document.getElementById("mode-detail");
    if (detail) detail.textContent = MODE_COPY[mode] || "";
  }

  async function loadParams() {
    const body = document.getElementById("params-body");
    if (!body) return;
    try {
      const res = await fetch("/api/structure-gate/v8");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      const cfg = data.config || {};
      body.innerHTML = "";
      for (const [key, meaning] of PARAM_META) {
        if (!(key in cfg)) continue;
        const tr = document.createElement("tr");
        tr.innerHTML = `<td>${key}</td><td>${fmt(cfg[key])}</td><td>${meaning}</td>`;
        body.appendChild(tr);
      }
      if (!body.children.length) {
        body.innerHTML = `<tr><td colspan="3" class="empty">無參數</td></tr>`;
      }
    } catch (err) {
      body.innerHTML = `<tr><td colspan="3" class="empty">載入失敗：${err.message}</td></tr>`;
    }
  }

  document.querySelectorAll(".sg-mode").forEach((btn) => {
    btn.addEventListener("click", () => setMode(btn.dataset.mode));
  });
  setMode("cash");
  loadParams();
})();
