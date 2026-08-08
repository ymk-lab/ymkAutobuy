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

  let submitEnabled = false;
  let busy = false;

  function $(sel) {
    return document.querySelector(sel);
  }

  function fmt(v) {
    if (typeof v === "boolean") return v ? "true" : "false";
    if (typeof v === "number") {
      if (Number.isInteger(v)) return String(v);
      return String(v);
    }
    if (v == null) return "—";
    return String(v);
  }

  function fmtPct(x) {
    if (x == null || Number.isNaN(Number(x))) return "—";
    return `${(Number(x) * 100).toFixed(1)}%`;
  }

  function setMode(mode) {
    document.querySelectorAll(".sg-mode").forEach((el) => {
      el.classList.toggle("is-active", el.dataset.mode === mode);
    });
    const detail = document.getElementById("mode-detail");
    if (detail) detail.textContent = MODE_COPY[mode] || "";
  }

  function pushActivity(msg, level = "info") {
    const box = $("#sg-activity");
    if (!box) return;
    const row = document.createElement("div");
    row.className = `sg-log sg-log-${level}`;
    const t = new Date().toISOString().slice(11, 19);
    row.textContent = `[${t}] ${msg}`;
    box.prepend(row);
    while (box.children.length > 40) box.removeChild(box.lastChild);
  }

  function setBusy(on, label) {
    busy = on;
    const b = $("#sg-badge-busy");
    if (!b) return;
    b.textContent = on ? label || "處理中" : "待命";
    b.className = on ? "badge badge-on" : "badge badge-idle";
  }

  function renderSubmitBadge() {
    const b = $("#sg-badge-submit");
    if (!b) return;
    b.textContent = submitEnabled ? "PAPER 送單 ON" : "PAPER 只計畫";
    b.className = submitEnabled ? "badge badge-on" : "badge badge-off";
  }

  function renderSgStatus(data) {
    if (!data) return;
    submitEnabled = !!data.submit_enabled;
    renderSubmitBadge();
    const sig = data.signal || {};
    const bt = data.backtest || {};
    const tgt = sig.target || {};
    const tgtS =
      Object.keys(tgt).length === 0
        ? "空手"
        : Object.entries(tgt)
            .map(([k, v]) => `${k} ${(Number(v) * 100).toFixed(0)}%`)
            .join(", ");
    const asof = $("#sg-asof");
    const modeEl = $("#sg-mode");
    const targetEl = $("#sg-target");
    const bookEl = $("#sg-book");
    const btSg = $("#sg-bt-sg");
    const btBh = $("#sg-bt-bh");
    if (asof) asof.textContent = sig.asof || "—";
    if (modeEl) modeEl.textContent = sig.mode || "—";
    if (targetEl) targetEl.textContent = tgtS;
    if (bookEl) bookEl.textContent = data.book || sig.book || "QQQ";
    if (btSg) btSg.textContent = fmtPct(bt.structure_gate_total_return);
    if (btBh) btBh.textContent = fmtPct(bt.bench_bh_total_return);
    const sel = $("#sg-book-select");
    if (sel && data.book) sel.value = data.book;
    if (sig.mode) setMode(sig.mode);
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

  async function refreshStatus() {
    const res = await fetch("/api/sg/status");
    if (!res.ok) throw new Error(`status HTTP ${res.status}`);
    const data = await res.json();
    renderSgStatus(data);
    return data;
  }

  async function consumeSSE(url, actionLabel) {
    setBusy(true, "處理中");
    pushActivity(`處理中：${actionLabel}…`, "info");
    const res = await fetch(url);
    if (!res.ok || !res.body) throw new Error(`請求失敗 (${res.status})`);
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let ok = false;
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const chunks = buffer.split("\n\n");
      buffer = chunks.pop() || "";
      for (const chunk of chunks) {
        const line = chunk
          .split("\n")
          .filter((l) => l.startsWith("data:"))
          .map((l) => l.slice(5).trim())
          .join("");
        if (!line) continue;
        let evt;
        try {
          evt = JSON.parse(line);
        } catch {
          continue;
        }
        const level = evt.level || (evt.phase === "error" ? "error" : "info");
        if (evt.message) pushActivity(evt.message, level);
        if (evt.phase === "done") ok = !!evt.ok;
        if (evt.data && (evt.data.signal || evt.data.backtest)) {
          renderSgStatus(evt.data);
        }
        if (evt.data && evt.data.submit_enabled != null) {
          submitEnabled = !!evt.data.submit_enabled;
          renderSubmitBadge();
        }
      }
    }
    setBusy(false);
    try {
      await refreshStatus();
    } catch {
      /* ignore */
    }
    if (!ok) throw new Error(`${actionLabel}未成功完成`);
  }

  async function withAction(fn) {
    if (busy) {
      pushActivity("忙碌中：請等待目前工作結束", "error");
      return;
    }
    try {
      await fn();
    } catch (err) {
      pushActivity(`錯誤：${err?.message || err}`, "error");
      setBusy(false);
    }
  }

  function bookParam() {
    const sel = $("#sg-book-select");
    return encodeURIComponent((sel && sel.value) || "QQQ");
  }

  document.querySelectorAll(".sg-mode").forEach((btn) => {
    btn.addEventListener("click", () => setMode(btn.dataset.mode));
  });

  document.querySelectorAll("[data-sg-action]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const action = btn.dataset.sgAction;
      if (action === "refresh") {
        withAction(async () => {
          setBusy(true, "處理中");
          pushActivity("處理中：重新整理狀態…", "info");
          await refreshStatus();
          pushActivity("完成：狀態已更新", "ok");
          setBusy(false);
        });
      } else if (action === "signal") {
        withAction(() =>
          consumeSSE(
            `/api/sg/run?mode=signal&submit=0&refresh=1&book=${bookParam()}`,
            "重算訊號"
          )
        );
      } else if (action === "once") {
        const submit = submitEnabled ? 1 : 0;
        withAction(() =>
          consumeSSE(
            `/api/sg/run?mode=once&submit=${submit}&refresh=1&book=${bookParam()}`,
            submit ? "執行一次（paper 送單）" : "執行一次（只計畫）"
          )
        );
      } else if (action === "backtest") {
        withAction(() =>
          consumeSSE(
            `/api/sg/run?mode=backtest&submit=0&refresh=1&book=${bookParam()}`,
            "長橋回測"
          )
        );
      } else if (action === "toggle-submit") {
        const next = submitEnabled ? 0 : 1;
        withAction(() =>
          consumeSSE(
            `/api/sg/set-submit?enabled=${next}`,
            next ? "開啟 paper 送單" : "關閉送單"
          )
        );
      }
    });
  });

  setMode("cash");
  loadParams();
  refreshStatus().catch((err) => pushActivity(`狀態載入失敗：${err.message}`, "error"));
})();
