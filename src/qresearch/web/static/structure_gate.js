(() => {
  const LS_API = "qresearch_api_base";

  function normalizeApiBase(raw) {
    let s = String(raw || "")
      .trim()
      .replace(/\/$/, "");
    if (!s) return "";
    if (!/^https?:\/\//i.test(s)) s = `https://${s}`;
    s = s.replace(/\/$/, "");
    // Reject broken deploy leftovers like https://.trycloudflare.com
    if (/^https?:\/\/\.trycloudflare\.com$/i.test(s)) return "";
    if (/^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/i.test(s) && location.protocol === "https:") {
      return "";
    }
    return s;
  }

  function resolveApiBase() {
    const params = new URLSearchParams(location.search);
    const rawQ = params.get("api") || params.get("api_base");
    // Same-origin Cloud Run rewrite: ?api=same or ?api=clear
    if (rawQ === "same" || rawQ === "clear" || rawQ === ".") {
      try {
        localStorage.removeItem(LS_API);
      } catch {
        /* ignore */
      }
      return "";
    }
    const fromQuery = normalizeApiBase(rawQ);
    if (fromQuery) {
      try {
        localStorage.setItem(LS_API, fromQuery);
      } catch {
        /* ignore */
      }
      return fromQuery;
    }
    try {
      const fromLs = normalizeApiBase(localStorage.getItem(LS_API));
      if (fromLs) return fromLs;
    } catch {
      /* ignore */
    }
    return normalizeApiBase(window.QRESEARCH_API_BASE);
  }

  let API_BASE = resolveApiBase();

  function apiUrl(path) {
    if (!path) return API_BASE || "/";
    if (/^https?:\/\//i.test(path)) return path;
    const p = path.startsWith("/") ? path : `/${path}`;
    return `${API_BASE}${p}`;
  }

  function paintApiBase() {
    const el = $("#sg-api-base");
    if (!el) return;
    el.textContent = API_BASE ? `API: ${API_BASE}` : "API: 未設定（點此填隧道網址）";
    el.title = "點擊設定／更換 API 隧道網址";
  }

  function promptApiBase(reason) {
    const msg =
      (reason ? `${reason}\n\n` : "") +
      "貼上 cloudflared 印出的完整網址，例如：\nhttps://abc-def-123.trycloudflare.com";
    const next = window.prompt(msg, API_BASE || "https://");
    if (next == null) return false;
    const normalized = normalizeApiBase(next);
    if (!normalized) {
      toast("API 網址無效（不能是 https://.trycloudflare.com）", "error");
      return false;
    }
    API_BASE = normalized;
    try {
      localStorage.setItem(LS_API, API_BASE);
    } catch {
      /* ignore */
    }
    paintApiBase();
    toast(`API 已設為 ${API_BASE}`, "ok");
    return true;
  }

  const MODE_COPY = {
    cash: "空手防守：結構轉弱或不在 risk-on 時持有現金。",
    ers: "新興轉強：持有剛相對基準轉強的個股（G1 ERS）。",
    strong: "已強領導：個股領漲且 crowded 時，持有確認領導股。",
    bench: "基準滿倉：Sticky／Thrust／指數偏強時，滿倉基準 ETF。",
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
  let statusCache = null;

  const $ = (sel) => document.querySelector(sel);

  function fmt(v) {
    if (typeof v === "boolean") return v ? "true" : "false";
    if (typeof v === "number") {
      if (Number.isInteger(v)) return String(v);
      return String(v);
    }
    if (v == null) return "—";
    return String(v);
  }

  function money(x) {
    if (x == null || Number.isNaN(Number(x))) return "—";
    return Number(x).toLocaleString("en-US", {
      style: "currency",
      currency: "USD",
      maximumFractionDigits: 0,
    });
  }

  function money2(x) {
    if (x == null || Number.isNaN(Number(x))) return "—";
    return Number(x).toLocaleString("en-US", {
      style: "currency",
      currency: "USD",
      maximumFractionDigits: 2,
    });
  }

  function pct(x) {
    if (x == null || Number.isNaN(Number(x))) return "—";
    return `${(Number(x) * 100).toFixed(1)}%`;
  }

  function signedMoney(x) {
    if (x == null || Number.isNaN(Number(x))) return "—";
    const n = Number(x);
    const s = money2(Math.abs(n));
    if (n > 0) return `+${s}`;
    if (n < 0) return `−${s}`;
    return s;
  }

  function pnlClass(x) {
    if (x == null || Number.isNaN(Number(x))) return "";
    if (Number(x) > 0) return "is-up";
    if (Number(x) < 0) return "is-down";
    return "";
  }

  function toast(msg, level = "info") {
    const root = $("#toast-root");
    if (!root) return;
    const el = document.createElement("div");
    el.className = `toast ${level}`;
    el.textContent = msg;
    root.appendChild(el);
    setTimeout(() => el.remove(), 4200);
  }

  function pushActivity(msg, level = "info") {
    const box = $("#sg-activity");
    if (!box) return;
    const row = document.createElement("div");
    row.className = `sg-log sg-log-${level}`;
    const t = new Date().toISOString().slice(11, 19);
    row.textContent = `[${t}] ${msg}`;
    box.prepend(row);
    while (box.children.length > 80) box.removeChild(box.lastChild);
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

  function setMode(mode) {
    document.querySelectorAll(".sg-mode").forEach((el) => {
      el.classList.toggle("is-active", el.dataset.mode === mode);
    });
    const detail = $("#mode-detail");
    if (detail) detail.textContent = MODE_COPY[mode] || "";
  }

  function renderOrders(listEl, rows, emptyText) {
    if (!listEl) return;
    listEl.innerHTML = "";
    if (!rows || !rows.length) {
      const li = document.createElement("li");
      li.className = "empty";
      li.textContent = emptyText;
      listEl.appendChild(li);
      return;
    }
    for (const o of rows) {
      const li = document.createElement("li");
      const side = (o.side || "").toLowerCase();
      li.innerHTML = `<span class="side ${side}">${side}</span> <strong>${o.quantity}</strong> ${o.symbol} <span class="px">@ ${Number(o.price).toFixed(2)}</span>`;
      listEl.appendChild(li);
    }
  }

  function auditStatusClass(status) {
    if (status === "pass" || status === "ok") return "sg-status-ok";
    if (status === "warn") return "sg-status-warn";
    return "sg-status-fail";
  }

  function renderFillAudit(audit) {
    const badge = $("#sg-audit-badge");
    const summary = $("#sg-audit-summary");
    const body = $("#fills-audit-body");
    const posBody = $("#fills-pos-body");
    const issuesEl = $("#sg-audit-issues");
    if (!body) return;

    if (!audit || (!audit.n_fills && !audit.n_preview && !(audit.lines || []).length)) {
      if (badge) {
        badge.textContent = "無成交";
        badge.className = "badge badge-idle";
      }
      if (summary) summary.textContent = "尚未有 latest_run／fills_ledger 可查核";
      body.innerHTML = `<tr><td colspan="9" class="empty">尚無成交可查核（需 latest_run 或 ledger）</td></tr>`;
      if (posBody) posBody.innerHTML = `<tr><td colspan="5" class="empty">—</td></tr>`;
      if (issuesEl) issuesEl.innerHTML = "";
      return;
    }

    const st = audit.status || (audit.ok ? "pass" : "fail");
    if (badge) {
      badge.textContent = `查核 ${String(st).toUpperCase()}`;
      badge.className =
        st === "pass"
          ? "badge badge-on"
          : st === "pending" || st === "warn"
            ? "badge badge-busy"
            : "badge badge-off";
    }
    if (summary) {
      const src = audit.sources || {};
      summary.textContent =
        `asof ${audit.asof || "—"} · preview ${audit.n_preview ?? 0} · fills ${audit.n_fills ?? 0}` +
        ` · issues ${audit.n_issues ?? 0}` +
        ` · run=${src.latest_run ? "Y" : "N"} account=${src.account_live ? "Y" : "N"}`;
    }

    const lines = audit.lines || [];
    if (!lines.length) {
      body.innerHTML = `<tr><td colspan="9" class="empty">無逐筆資料</td></tr>`;
    } else {
      body.innerHTML = lines
        .map((r) => {
          const bps = r.price_bps == null ? "—" : Number(r.price_bps).toFixed(1);
          const notion = r.notional == null ? "—" : money2(r.notional);
          return `<tr>
            <td class="${auditStatusClass(r.status)}">${r.status}</td>
            <td>${r.side || "—"}</td>
            <td>${r.symbol || "—"}</td>
            <td>${r.preview_qty == null ? "—" : r.preview_qty}</td>
            <td>${r.fill_qty == null ? "—" : r.fill_qty}</td>
            <td>${r.preview_price == null ? "—" : Number(r.preview_price).toFixed(2)}</td>
            <td>${r.fill_price == null ? "—" : Number(r.fill_price).toFixed(2)}</td>
            <td>${bps}</td>
            <td>${notion}</td>
          </tr>`;
        })
        .join("");
    }

    const pos = audit.positions || [];
    if (posBody) {
      if (!pos.length) {
        posBody.innerHTML = `<tr><td colspan="5" class="empty">—</td></tr>`;
      } else {
        posBody.innerHTML = pos
          .map((p) => {
            const okTxt = p.ok == null ? "—" : p.ok ? "ok" : "mismatch";
            const cls = p.ok === false ? "sg-status-fail" : p.ok ? "sg-status-ok" : "";
            return `<tr>
              <td>${p.symbol}</td>
              <td>${p.before ?? "—"}</td>
              <td>${p.expected_after ?? "—"}</td>
              <td>${p.after == null ? "—" : p.after}</td>
              <td class="${cls}">${okTxt}</td>
            </tr>`;
          })
          .join("");
      }
    }

    if (issuesEl) {
      const issues = audit.issues || [];
      issuesEl.innerHTML = issues.map((x) => `<li>${x}</li>`).join("");
    }
  }

  function renderHoldings(account) {
    const body = $("#holdings-body");
    if (!body) return;
    const holdings = account?.holdings || [];
    if (!holdings.length) {
      const pos = account?.positions || {};
      const keys = Object.keys(pos);
      if (!keys.length) {
        body.innerHTML = `<tr><td colspan="7" class="empty">無持倉</td></tr>`;
        return;
      }
      body.innerHTML = keys
        .map((k) => {
          const q = account?.quotes?.[k];
          return `<tr><td>${k}</td><td>${pos[k]}</td><td>—</td><td>${q != null ? Number(q).toFixed(2) : "—"}</td><td>—</td><td>—</td><td>—</td></tr>`;
        })
        .join("");
      return;
    }
    body.innerHTML = holdings
      .map((h) => {
        const up = h.unrealized_pnl;
        const day = h.day_pnl;
        return `<tr>
          <td>${h.symbol}${h.name ? `<small>${h.name}</small>` : ""}</td>
          <td>${h.quantity}</td>
          <td>${h.cost_price != null ? Number(h.cost_price).toFixed(2) : "—"}</td>
          <td>${h.last != null ? Number(h.last).toFixed(2) : "—"}</td>
          <td>${h.market_value != null ? money2(h.market_value) : "—"}</td>
          <td class="${pnlClass(up)}">${up != null ? signedMoney(up) : "—"}</td>
          <td class="${pnlClass(day)}">${day != null ? signedMoney(day) : "—"}</td>
        </tr>`;
      })
      .join("");
  }

  function renderSgStatus(data) {
    if (!data) return;
    statusCache = data;
    submitEnabled = !!data.submit_enabled;
    renderSubmitBadge();

    const sig = data.signal || {};
    const bt = data.backtest || {};
    const account = data.account || {};
    const pnl = account.pnl || {};
    const run = data.last_run || {};
    const state = data.state || {};

    const mode = sig.mode || "—";
    const tgt = sig.target || {};
    const tgtS =
      Object.keys(tgt).length === 0
        ? "空手"
        : Object.entries(tgt)
            .map(([k, v]) => `${k} ${(Number(v) * 100).toFixed(0)}%`)
            .join(", ");

    const sleeveCap = data.sleeve_usd ? Number(data.sleeve_usd) : null;
    const sleeveFromSig = sig.sleeve_equity_usd != null ? Number(sig.sleeve_equity_usd) : null;
    const equity = pnl.equity_usd != null ? Number(pnl.equity_usd) : null;
    const sleeve =
      sleeveCap != null && sleeveCap > 0
        ? sleeveCap
        : sleeveFromSig != null
          ? sleeveFromSig
          : equity;

    $("#m-sleeve") && ($("#m-sleeve").textContent = money(sleeve));
    $("#m-cash") && ($("#m-cash").textContent = money2(account.cash_usd ?? sig.cash_usd));
    $("#m-equity") && ($("#m-equity").textContent = money2(equity ?? sleeveFromSig));
    const upnlEl = $("#m-upnl");
    if (upnlEl) {
      upnlEl.textContent = signedMoney(pnl.unrealized_pnl);
      upnlEl.className = pnlClass(pnl.unrealized_pnl);
    }
    const dayEl = $("#m-day");
    if (dayEl) {
      dayEl.textContent = signedMoney(pnl.day_pnl);
      dayEl.className = pnlClass(pnl.day_pnl);
    }
    $("#m-asof") && ($("#m-asof").textContent = sig.asof || "—");

    $("#sg-mode-hero") && ($("#sg-mode-hero").textContent = mode);
    $("#sg-target-hero") && ($("#sg-target-hero").textContent = tgtS);
    const weights = data.weights || sig.weights || { SPY: 0.4, QQQ: 0.3, SMH: 0.3 };
    const bookLabel =
      "V11 · " +
      Object.entries(weights)
        .map(([k, v]) => `${k}${(Number(v) * 100).toFixed(0)}`)
        .join(" / ");
    $("#sg-book") && ($("#sg-book").textContent = bookLabel);
    $("#sg-mode") && ($("#sg-mode").textContent = mode);
    $("#sg-target") && ($("#sg-target").textContent = tgtS);

    const flags = ["sticky", "thrust", "mild", "harsh_ret", "harsh_dd", "index_lean", "stock_led", "crowded"]
      .filter((k) => sig[k])
      .join(" · ");
    $("#sg-flags") && ($("#sg-flags").textContent = flags || "—");

    const sub = $("#sg-monitor-sub");
    if (sub) {
      const submitTxt = submitEnabled ? "送單開啟（模擬盤）" : "只計畫、不送單";
      sub.textContent = `asof ${sig.asof || "—"} · ${submitTxt} · paper only`;
    }

    renderOrders($("#preview-list"), sig.preview_orders || [], "尚無預覽單");
    renderOrders($("#fill-list"), run.fills || [], "尚無成交紀錄");
    const st = $("#state-line");
    if (st) {
      st.textContent = state.asof
        ? `state：asof=${state.asof} submitted=${!!state.submitted}${state.mode ? ` mode=${state.mode}` : ""}`
        : "state：尚無";
    }

    renderFillAudit(data.fill_audit || null);
    renderHoldings(account);

    $("#sg-bt-sg") && ($("#sg-bt-sg").textContent = pct(bt.structure_gate_total_return));
    $("#sg-bt-bh") && ($("#sg-bt-bh").textContent = pct(bt.bench_bh_total_return));
    $("#sg-bt-range") &&
      ($("#sg-bt-range").textContent =
        bt.start && bt.end ? `${bt.start} → ${bt.end}` : "—");
    $("#sg-bt-gate") &&
      ($("#sg-bt-gate").textContent =
        bt.soft_pass == null
          ? "—"
          : `${bt.soft_pass ? "soft✓" : "soft✗"} / ${bt.hard_pass_beat_both ? "hard✓" : "hard✗"}`);

    const sel = $("#sg-book-select");
    if (sel && (data.book || sig.book)) sel.value = data.book || sig.book;

    if (sig.mode) setMode(sig.mode);

    const clock = $("#sg-badge-clock");
    if (clock && data.server_time_utc) {
      clock.textContent = String(data.server_time_utc).slice(11, 19) + "Z";
    }
  }

  async function loadParams() {
    const body = $("#params-body");
    if (!body) return;
    try {
      const res = await fetch(apiUrl("/api/structure-gate/v8"));
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

  async function refreshStatus({ live = false } = {}) {
    const url = live ? apiUrl("/api/sg/status?live=1") : apiUrl("/api/sg/status");
    const res = await fetch(url);
    if (!res.ok) throw new Error(`status HTTP ${res.status}`);
    const data = await res.json();
    renderSgStatus(data);
    return data;
  }

  async function consumeSSE(url, actionLabel) {
    setBusy(true, "處理中");
    pushActivity(`處理中：${actionLabel}…`, "info");
    toast(`處理中：${actionLabel}…`, "info");
    const res = await fetch(apiUrl(url));
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
        if (evt.message) {
          pushActivity(evt.message, level);
          if (level === "ok" || level === "error" || evt.phase === "start") {
            toast(evt.message, level === "log" ? "info" : level);
          }
        }
        if (evt.phase === "done") ok = !!evt.ok;
        if (evt.data) {
          if (evt.data.signal || evt.data.backtest || evt.data.account) {
            renderSgStatus({ ...(statusCache || {}), ...evt.data, submit_enabled: submitEnabled });
          }
          if (evt.data.submit_enabled != null) {
            submitEnabled = !!evt.data.submit_enabled;
            renderSubmitBadge();
          }
        }
      }
    }
    setBusy(false);
    try {
      await refreshStatus({ live: false });
    } catch {
      /* ignore */
    }
    if (!ok) throw new Error(`${actionLabel}未成功完成`);
  }

  async function withAction(fn) {
    if (busy) {
      pushActivity("忙碌中：請等待目前工作結束", "error");
      toast("忙碌中：請稍候", "error");
      return;
    }
    try {
      await fn();
    } catch (err) {
      pushActivity(`錯誤：${err?.message || err}`, "error");
      toast(`錯誤：${err?.message || err}`, "error");
      setBusy(false);
    }
  }

  function bookParam() {
    return "V11";
  }

  function isoDate(d) {
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return `${y}-${m}-${day}`;
  }

  function btRange() {
    const startEl = $("#sg-bt-start");
    const endEl = $("#sg-bt-end");
    const start = (startEl && startEl.value) || "2025-08-07";
    const end = (endEl && endEl.value) || "2026-08-07";
    return { start, end };
  }

  function saveBtRange() {
    try {
      const { start, end } = btRange();
      localStorage.setItem("sg_bt_start", start);
      localStorage.setItem("sg_bt_end", end);
    } catch {
      /* ignore */
    }
  }

  function loadBtRange() {
    const startEl = $("#sg-bt-start");
    const endEl = $("#sg-bt-end");
    if (!startEl || !endEl) return;
    try {
      const s = localStorage.getItem("sg_bt_start");
      const e = localStorage.getItem("sg_bt_end");
      if (s) startEl.value = s;
      if (e) endEl.value = e;
    } catch {
      /* ignore */
    }
    // If backtest summary already has a range, prefer showing that once status loads.
  }

  function applyBtPreset(kind) {
    const end = new Date();
    let start = new Date(end);
    if (kind === "3m") {
      start.setMonth(start.getMonth() - 3);
    } else if (kind === "1y") {
      start.setFullYear(start.getFullYear() - 1);
    } else if (kind === "ytd") {
      start = new Date(end.getFullYear(), 0, 1);
    } else if (kind === "2021") {
      start = new Date(2021, 5, 1); // 2021-06-01
    } else {
      return;
    }
    const startEl = $("#sg-bt-start");
    const endEl = $("#sg-bt-end");
    if (startEl) startEl.value = isoDate(start);
    if (endEl) endEl.value = isoDate(end);
    saveBtRange();
  }

  document.querySelectorAll(".sg-mode").forEach((btn) => {
    btn.addEventListener("click", () => setMode(btn.dataset.mode));
  });

  document.querySelectorAll("[data-bt-preset]").forEach((btn) => {
    btn.addEventListener("click", () => applyBtPreset(btn.dataset.btPreset));
  });
  ["sg-bt-start", "sg-bt-end"].forEach((id) => {
    const el = $("#" + id);
    if (el) el.addEventListener("change", saveBtRange);
  });

  document.querySelectorAll("[data-sg-action]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const action = btn.dataset.sgAction;
      if (action === "refresh") {
        withAction(async () => {
          setBusy(true, "處理中");
          pushActivity("處理中：重新整理狀態…", "info");
          await refreshStatus({ live: true });
          pushActivity("完成：狀態已更新", "ok");
          toast("完成：狀態已更新", "ok");
          setBusy(false);
        });
      } else if (action === "sync") {
        withAction(() => consumeSSE("/api/sg/sync-account", "同步富途帳戶"));
      } else if (action === "signal") {
        withAction(() =>
          consumeSSE(
            `/api/sg/run?mode=signal&submit=0&refresh=1&book=${bookParam()}`,
            "重算 v11 訊號"
          )
        );
      } else if (action === "once") {
        const submit = submitEnabled ? 1 : 0;
        withAction(() =>
          consumeSSE(
            `/api/sg/run?mode=once&submit=${submit}&refresh=1&book=${bookParam()}`,
            submit ? "執行一次（富途 paper 送單）" : "執行一次（只計畫）"
          )
        );
      } else if (action === "backtest") {
        const { start, end } = btRange();
        if (!start || !end) {
          toast("請先設定回測起迄日", "error");
          return;
        }
        if (end < start) {
          toast("結束日不可早於開始日", "error");
          return;
        }
        saveBtRange();
        withAction(() =>
          consumeSSE(
            `/api/sg/run?mode=backtest&submit=0&refresh=0&book=${bookParam()}&start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`,
            `v11 blend 回測 ${start}→${end}`
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
      } else if (action === "audit-fills") {
        withAction(async () => {
          setBusy(true, "查核中");
          pushActivity("處理中：逐筆成交查核…", "info");
          try {
            const res = await fetch(apiUrl("/api/sg/fills?refresh=1"));
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            renderFillAudit(data.audit || null);
            const st = (data.audit && data.audit.status) || "—";
            pushActivity(`完成：成交查核 ${st}`, data.audit && data.audit.ok ? "ok" : "error");
            toast(`成交查核：${st}`, data.audit && data.audit.ok ? "ok" : "error");
            await refreshStatus({ live: false });
          } catch (err) {
            pushActivity(`查核失敗：${err?.message || err}`, "error");
            toast(`查核失敗：${err?.message || err}`, "error");
          } finally {
            setBusy(false);
          }
        });
      }
    });
  });

  paintApiBase();
  const apiBaseEl = $("#sg-api-base");
  if (apiBaseEl) {
    apiBaseEl.style.cursor = "pointer";
    apiBaseEl.addEventListener("click", async () => {
      if (!promptApiBase()) return;
      try {
        await refreshStatus({ live: true });
        toast("完成：已連上 API", "ok");
      } catch (err) {
        toast(`仍無法連線：${err?.message || err}`, "error");
        pushActivity(`狀態載入失敗：${err?.message || err}`, "error");
      }
    });
  }

  if (!API_BASE && location.hostname.includes("web.app")) {
    promptApiBase("Firebase 頁面需要本機隧道 API 網址。");
  }

  setMode("cash");
  loadBtRange();
  loadParams();
  refreshStatus({ live: false })
    .then((data) => {
      const bt = (data && data.backtest) || {};
      if (bt.start && $("#sg-bt-start") && !localStorage.getItem("sg_bt_start")) {
        $("#sg-bt-start").value = String(bt.start).slice(0, 10);
      }
      if (bt.end && $("#sg-bt-end") && !localStorage.getItem("sg_bt_end")) {
        $("#sg-bt-end").value = String(bt.end).slice(0, 10);
      }
      return refreshStatus({ live: true }).catch(() => null);
    })
    .catch(async (err) => {
      pushActivity(`狀態載入失敗：${err.message}`, "error");
      if (/Failed to fetch|NetworkError|Load failed/i.test(String(err?.message || err))) {
        if (promptApiBase("無法連到 API（Failed to fetch）。")) {
          try {
            await refreshStatus({ live: true });
          } catch (e2) {
            pushActivity(`狀態載入失敗：${e2.message}`, "error");
          }
        }
      }
    });
})();
