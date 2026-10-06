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

  const MODE_NAME = {
    cash: "持有現金",
    ers: "買入剛轉強的股票",
    strong: "買入已經領先的股票",
    bench: "滿倉持有基準指數基金",
  };

  const MODE_COPY = {
    cash: "市場結構轉弱，或者還沒有打開風險時，這個袖口不持股，把錢留成現金。",
    ers: "有股票剛剛相對基準轉強，而且連續幾天守住，這個袖口會買入這些剛轉強的股票。",
    strong: "漲勢集中在已經領先的股票，這個袖口會買入那些確認領先的股票。",
    bench: "指數自己偏強，或者原本領先的股票守不住時，這個袖口改為滿倉持有基準指數基金。",
  };

  const FLAG_SENTENCE = {
    sticky: "原本領先的股票相對基準掉了下來，這條黏住規則正在生效。",
    thrust: "基準指數短期衝高，這條衝刺規則正在生效。",
    mild: "基準只是輕度轉弱，這條輕度防守正在生效。",
    harsh_ret: "基準最近 20 日跌得太急，這條急跌規則正在生效。",
    harsh_dd: "基準自高位回撤已經很深，這條深度回撤規則正在生效。",
    index_lean: "漲勢由指數帶動，個股並未領先。",
    stock_led: "個股相對基準領先，漲勢由股票帶動。",
    crowded: "領漲集中在少數股票，而且持股彼此重疊。",
  };

  const AUDIT_STATUS = {
    ok: "股數和價格都對得上",
    pass: "對得上",
    pending: "計劃已寫下，尚未成交",
    warn: "成交了，但價格偏離計劃",
    fail: "對不上",
    extra_fill: "帳戶有這筆成交，但計劃裡沒有",
    missing_fill: "計劃有這筆，但帳戶尚未成交",
    qty_mismatch: "成交股數和計劃股數不同",
    price_warn: "成交價偏離計劃價超過容許範圍",
  };

  const PARAM_META = [
    ["sticky_enter_trail", "領先股票相對基準的 60 日超額跌破這個幅度，才開始考慮結束黏住、改持指數基金。"],
    ["sticky_enter_confirm", "上面的落後要連續出現這麼多天，才確認領先股票守不住。"],
    ["sticky_exit_trail", "落後收斂到這個幅度以內，才考慮結束黏住。"],
    ["sticky_exit_confirm", "落後收斂要連續這麼多天，才確認可以離開黏住狀態。"],
    ["sticky_require_above50", "黏住期間是否還要求股價站在 50 日均線之上。"],
    ["thrust_ret5_min", "基準最近 5 日漲幅至少要達到這個數，才算短期衝高。"],
    ["thrust_ret10_min", "基準最近 10 日漲幅至少要達到這個數，才算短期衝高。"],
    ["thrust_bounce20_min", "基準用 20 日低點反彈至少這個幅度，才算衝刺。"],
    ["thrust_ret20_min", "基準最近 20 日漲幅至少要達到這個數，才算衝刺。"],
    ["thrust_require_above50", "衝刺時是否還要求基準站在 50 日均線之上。"],
    ["mild_defense_dd", "基準自 60 日高位回撤達到這個幅度，視為輕度轉弱並改持現金。"],
    ["mild_defense_ret20", "基準最近 20 日跌幅達到這個數，視為輕度轉弱。"],
    ["harsh_defense_dd", "基準自高位回撤達到這個幅度，視為深度回撤並改持現金。"],
    ["harsh_defense_ret20", "基準最近 20 日跌幅達到這個數，視為急跌並當天改持現金。"],
    ["stock_led_min_trail", "個股相對基準的 20 日超額至少這個數，才算股票帶動漲勢。"],
    ["index_lean_max_trail", "個股相對基準的 20 日超額低於這個數，才算指數單獨偏強。"],
    ["bench_slippage_bps", "回測買賣指數基金時，假設成交價再滑這個基點數。1 個基點是萬分之一。"],
    ["stock_slippage_bps", "回測買賣個股時，假設成交價再滑這個基點數。"],
  ];

  let submitEnabled = false;
  let busy = false;
  let statusCache = null;
  let lastSeenAsof = null;
  let pollTimer = null;

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

  function fmtHktClock(raw) {
    /** Prefer API HKT string; else parse ISO → Asia/Hong_Kong YYYY-MM-DD HH:MM. */
    if (raw == null || raw === "") return null;
    const s = String(raw).trim();
    if (/HKT\s*$/i.test(s) && /\d{2}:\d{2}/.test(s)) return s;
    const ms = Date.parse(s);
    if (!Number.isFinite(ms)) {
      // date-only → show as midnight mark is misleading; keep date + ask for better field
      if (/^\d{4}-\d{2}-\d{2}$/.test(s)) return `${s} （僅日期）`;
      return s;
    }
    try {
      const fmt = new Intl.DateTimeFormat("en-CA", {
        timeZone: "Asia/Hong_Kong",
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      });
      const parts = Object.fromEntries(fmt.formatToParts(new Date(ms)).map((p) => [p.type, p.value]));
      return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute} HKT`;
    } catch {
      return s;
    }
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
    b.textContent = submitEnabled ? "模擬盤送單已開" : "只計算，不送單";
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
      const verb = side === "buy" ? "買入" : side === "sell" ? "賣出" : "交易";
      const qty = Number(o.quantity);
      const px = Number(o.price);
      const notion = Number.isFinite(qty) && Number.isFinite(px) ? money2(qty * px) : "—";
      li.textContent = `${verb} ${o.symbol || "未命名標的"} ${Number.isFinite(qty) ? qty : "—"} 股，每股 ${Number.isFinite(px) ? px.toFixed(2) : "—"} 美元，金額 ${notion}。`;
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
        badge.textContent = "沒有可核對的成交";
        badge.className = "badge badge-idle";
      }
      if (summary) summary.textContent = "這一次還沒有計劃單或成交紀錄可以對帳。";
      body.innerHTML = `<tr><td colspan="9" class="empty">尚未有這一次的計劃單或成交可以核對</td></tr>`;
      if (posBody) posBody.innerHTML = `<tr><td colspan="5" class="empty">—</td></tr>`;
      if (issuesEl) issuesEl.innerHTML = "";
      return;
    }

    const st = audit.status || (audit.ok ? "pass" : "fail");
    if (badge) {
      badge.textContent = AUDIT_STATUS[st] || "需要再看";
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
        `訊號日 ${audit.asof || "未標明"}。計劃 ${audit.n_preview ?? 0} 筆，實際成交 ${audit.n_fills ?? 0} 筆，有 ${audit.n_issues ?? 0} 項對不上。` +
        `${src.latest_run ? "已讀到這一次的執行結果。" : "尚未讀到這一次的執行結果。"}` +
        `${src.account_live ? "已讀到帳戶快照。" : "尚未讀到帳戶快照。"}`;
    }

    const lines = audit.lines || [];
    if (!lines.length) {
      body.innerHTML = `<tr><td colspan="9" class="empty">沒有可以逐筆列出的資料</td></tr>`;
    } else {
      body.innerHTML = lines
        .map((r) => {
          const verb = r.side === "buy" ? "買入" : r.side === "sell" ? "賣出" : "交易";
          const sentence = `${verb} ${r.symbol || "未命名標的"}`;
          const bpsTxt = r.price_bps == null ? "—" : `${Number(r.price_bps).toFixed(1)} 個基點`;
          const notion = r.notional == null ? "—" : money2(r.notional);
          const fee = r.fee == null ? "—" : money2(r.fee);
          return `<tr>
            <td class="${auditStatusClass(r.status)}">${AUDIT_STATUS[r.status] || "需要再看"}</td>
            <td>${sentence}</td>
            <td>${r.preview_qty == null ? "—" : r.preview_qty}</td>
            <td>${r.fill_qty == null ? "—" : r.fill_qty}</td>
            <td>${r.preview_price == null ? "—" : Number(r.preview_price).toFixed(2)}</td>
            <td>${r.fill_price == null ? "—" : Number(r.fill_price).toFixed(2)}</td>
            <td>${bpsTxt}</td>
            <td>${notion}</td>
            <td>${fee}</td>
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
            const okTxt = p.ok == null ? "帳戶股數尚未讀到" : p.ok ? "相符" : "不相符";
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

  function envSentence(env) {
    const key = String(env || "").toUpperCase();
    if (key === "REAL") return "這份持倉來自真倉。";
    if (key === "SIMULATE") return "這份持倉來自富途模擬倉。接上真倉並同步之後，同一張表會改顯示真倉。";
    return "尚未標明這份持倉是真倉還是模擬倉。";
  }

  function renderHoldings(account, trdEnv) {
    const body = $("#holdings-body");
    const note = $("#sg-holdings-note");
    const trace = $("#sg-pnl-trace");
    if (note) {
      const err = account?.live_error ? ` ${account.live_error}` : "";
      note.textContent = `${envSentence(account?.trd_env || trdEnv)}${err}`;
    }
    if (!body) return;
    const pnl = account?.pnl || {};
    const equity = pnl.equity_usd;
    if (trace) {
      const parts = [
        `現金 ${money2(account?.cash_usd)}`,
        `持倉市值 ${money2(pnl.market_value)}`,
        `持倉成本 ${money2(pnl.cost_value)}`,
        `未賣出的盈虧 ${signedMoney(pnl.unrealized_pnl)}`,
        `今日市價變動 ${signedMoney(pnl.day_pnl)}`,
        `帳戶權益 ${money2(equity)}`,
      ];
      trace.textContent = parts.join("。") + "。";
    }
    const holdings = account?.holdings || [];
    const emptyRow = `<tr><td colspan="10" class="empty">帳戶裡目前沒有持倉。</td></tr>`;
    if (!holdings.length) {
      const pos = account?.positions || {};
      const keys = Object.keys(pos);
      if (!keys.length) {
        body.innerHTML = emptyRow;
        return;
      }
      body.innerHTML = keys
        .map((k) => {
          const q = account?.quotes?.[k];
          const qty = Number(pos[k]);
          const last = q != null ? Number(q) : null;
          const mv = last != null && Number.isFinite(qty) ? last * qty : null;
          const weight = mv != null && equity ? mv / Number(equity) : null;
          return `<tr>
            <td>${k}</td>
            <td>${pos[k]}</td>
            <td>—</td>
            <td>—</td>
            <td>—</td>
            <td>${last != null ? last.toFixed(2) : "—"}</td>
            <td>${mv != null ? money2(mv) : "—"}</td>
            <td>${weight != null ? pct(weight) : "—"}</td>
            <td>—</td>
            <td>—</td>
          </tr>`;
        })
        .join("");
      return;
    }
    body.innerHTML = holdings
      .map((h) => {
        const up = h.unrealized_pnl;
        const day = h.day_pnl;
        const mv = h.market_value;
        const weight = mv != null && equity ? Number(mv) / Number(equity) : null;
        const upTxt =
          up == null
            ? "—"
            : `${signedMoney(up)}${h.unrealized_pnl_pct != null ? `（${pct(h.unrealized_pnl_pct)}）` : ""}`;
        const dayTxt =
          day == null
            ? "—"
            : `${signedMoney(day)}${h.day_pnl_pct != null ? `（${pct(h.day_pnl_pct)}）` : ""}`;
        return `<tr>
          <td>${h.symbol}${h.name ? `<small>${h.name}</small>` : ""}</td>
          <td>${h.quantity}</td>
          <td>${h.available_quantity != null ? h.available_quantity : "—"}</td>
          <td>${h.cost_price != null ? Number(h.cost_price).toFixed(4) : "—"}</td>
          <td>${h.cost_value != null ? money2(h.cost_value) : "—"}</td>
          <td>${h.last != null ? Number(h.last).toFixed(2) : "—"}</td>
          <td>${mv != null ? money2(mv) : "—"}</td>
          <td>${weight != null ? pct(weight) : "—"}</td>
          <td class="${pnlClass(up)}">${upTxt}</td>
          <td class="${pnlClass(day)}">${dayTxt}</td>
        </tr>`;
      })
      .join("");
  }

  function renderLedger(ledger) {
    const body = $("#sg-ledger-body");
    const kpis = $("#sg-ledger-kpis");
    if (!body) return;
    const rows = ledger?.rows || [];
    if (kpis) {
      const cards = [
        ["買入金額合計", money2(ledger?.buy_notional)],
        ["賣出金額合計", money2(ledger?.sell_notional)],
        ["費用合計", money2(ledger?.fees)],
        ["已實現盈虧", signedMoney(ledger?.realized_pnl)],
      ];
      kpis.innerHTML = cards
        .map(
          ([label, value]) =>
            `<article class="sg-ops-card"><h3>${label}</h3><strong>${value}</strong></article>`
        )
        .join("");
    }
    if (!rows.length) {
      body.innerHTML = `<tr><td colspan="10" class="empty">尚未寫入成交帳。同步並送單之後，每一筆金額會出現在這裡。</td></tr>`;
      return;
    }
    body.innerHTML = rows
      .map((r) => {
        const verb = r.side === "buy" ? "買入" : "賣出";
        const when = fmtHktClock(r.timestamp) || r.asof || "時間未標明";
        let sentence = `${verb} ${r.symbol}`;
        if (r.order_id) sentence += `，單號 ${r.order_id}`;
        if (r.basis_note) sentence += `。${r.basis_note}`;
        const avg = r.avg_cost_after != null ? Number(r.avg_cost_after).toFixed(4) : "已清倉";
        return `<tr>
          <td>${when}</td>
          <td>${sentence}</td>
          <td>${r.quantity}</td>
          <td>${Number(r.price).toFixed(4)}</td>
          <td>${money2(r.notional)}</td>
          <td>${money2(r.fee)}</td>
          <td class="${pnlClass(r.cash)}">${signedMoney(r.cash)}</td>
          <td>${r.position_after}</td>
          <td>${avg}</td>
          <td class="${pnlClass(r.realized_pnl)}">${r.realized_pnl == null ? "買入不計算已實現盈虧" : signedMoney(r.realized_pnl)}</td>
        </tr>`;
      })
      .join("");
  }

  function pctNum(x, digits = 2) {
    if (x == null || Number.isNaN(Number(x))) return "—";
    return `${(Number(x) * 100).toFixed(digits)}%`;
  }

  function renderNameTable(rows, emptyText) {
    if (!rows || !rows.length) {
      return `<p class="empty">${emptyText}</p>`;
    }
    const body = rows
      .slice(0, 10)
      .map((r, i) => {
        const miss = [];
        if (r.just_turned === false) miss.push("還沒有剛剛轉強");
        if (r.persist3 === false) miss.push("未連續三天維持轉強");
        if (r.excess_mid_ok === false) miss.push("中期超額報酬不夠");
        if (r.not_already_strong === false) miss.push("已經太強，不再當作剛轉強");
        const note = r.entry_ok
          ? "四項條件都成立，可以買入"
          : miss.length
            ? miss.join("；")
            : `四項條件過了 ${r.legs_pass ?? "—"} 項`;
        return `<tr>
          <td>${i + 1}</td>
          <td>${r.symbol || "—"}</td>
          <td>${pctNum(r.excess_20)}</td>
          <td>${pctNum(r.excess_10)}</td>
          <td>${pctNum(r.excess_60)}</td>
          <td>${note}</td>
        </tr>`;
      })
      .join("");
    return `<div class="table-scroll"><table class="sg-table">
      <thead><tr><th>名次</th><th>標的</th><th>20 日超額</th><th>10 日超額</th><th>60 日超額</th><th>能不能買</th></tr></thead>
      <tbody>${body}</tbody>
    </table></div>`;
  }

  function renderDiagnose(diagnose, diagnoseText) {
    const body = $("#sg-diagnose-body");
    const asofBadge = $("#sg-diagnose-asof");
    const textEl = $("#sg-diagnose-text");
    if (textEl) textEl.textContent = diagnoseText || "—";
    if (!body) return;

    if (!diagnose || !diagnose.books || !Object.keys(diagnose.books).length) {
      body.innerHTML =
        `<p class="empty">還沒有診斷。按「重新診斷」會讀取已儲存的行情，大約需要幾十秒。</p>`;
      if (asofBadge) {
        asofBadge.textContent = "尚未診斷";
        asofBadge.className = "badge badge-idle";
      }
      return;
    }

    if (asofBadge) {
      const when =
        (statusCache && statusCache.diagnose_updated_at_hkt) ||
        fmtHktClock(diagnose.generated_at_utc) ||
        null;
      asofBadge.textContent = when
        ? `${when}${diagnose.asof ? ` · asof ${diagnose.asof}` : ""}`
        : `asof ${diagnose.asof || "—"}`;
      asofBadge.className = "badge badge-on";
    }

    const blocks = Object.entries(diagnose.books)
      .map(([book, blk]) => {
        const flags = Object.entries(blk.flags || {})
          .filter(([, v]) => !!v)
          .map(([k]) => FLAG_SENTENCE[k] || `${k} 這條規則正在生效。`)
          .join("");
        const reasons = (blk.reasons || [])
          .map((r) => `<li>${r}</li>`)
          .join("");
        const ers = blk.would_hold_if_ers || {};
        const strong = blk.would_hold_if_strong || {};
        const sc = blk.ers_scorecard || {};
        const entryRows = sc.entry_ok_ranked || [];
        const nearRows = sc.near_miss_ranked || [];
        return `<article class="sg-diagnose-book">
          <h3>${book} 袖口 · ${MODE_NAME[blk.mode] || "持倉方式未標明"}</h3>
          <p class="sg-diagnose-meta">
            ${flags || "沒有額外規則正在生效。"}
            領先股票相對基準的 20 日超額是 ${pctNum(blk.leader_vs_bench_trail20)}，60 日超額是 ${pctNum(blk.leader_vs_bench_trail60)}。
            如果改買剛轉強的股票，會是 ${ers.symbol || "沒有合格股票"}。
            如果改買已經領先的股票，會是 ${strong.symbol || "沒有合格股票"}。
            今天新符合轉強條件的有 ${sc.n_entry_ok ?? 0} 隻。
          </p>
          <ul class="sg-diagnose-reasons">${reasons || "<li>無解釋</li>"}</ul>
          <h3 class="sg-mini">今天可以當作剛轉強而買入的股票</h3>
          ${renderNameTable(entryRows, "沒有股票四項條件都成立")}
          <h3 class="sg-mini">接近可以買入的股票（四項裡至少過了兩項）</h3>
          ${renderNameTable(nearRows, "沒有接近合格的股票")}
        </article>`;
      })
      .join("");
    body.innerHTML = blocks;
  }

  function bps(x) {
    if (x == null || Number.isNaN(Number(x))) return "—";
    const n = Number(x);
    const sign = n > 0 ? "+" : "";
    return `${sign}${n.toFixed(1)} bps`;
  }

  function targetLabel(target) {
    const entries = Object.entries(target || {});
    if (!entries.length) return "尚未寫入目標";
    return entries
      .map(([k, v]) => {
        const n = Number(v);
        if (!Number.isFinite(n)) return k;
        return `${k} ${(n * 100).toFixed(0)}%`;
      })
      .join(" · ");
  }

  function renderOps(ops) {
    const freezeBadge = $("#sg-badge-freeze");
    const freezeCard = $("#sg-ops-freeze");
    const bandCard = $("#sg-ops-band");
    if (!ops) {
      if (freezeBadge) {
        freezeBadge.textContent = "凍結 —";
        freezeBadge.className = "badge badge-idle";
      }
      return;
    }

    if (freezeBadge) {
      freezeBadge.textContent = ops.frozen ? "已凍結" : "未凍結";
      freezeBadge.className = ops.frozen ? "badge badge-off" : "badge badge-on";
    }
    if (freezeCard) freezeCard.classList.toggle("is-alert", !!ops.frozen);
    const freezeValue = $("#sg-ops-freeze-value");
    const freezeDetail = $("#sg-ops-freeze-detail");
    if (freezeValue) freezeValue.textContent = ops.frozen ? "已凍結" : "未凍結";
    if (freezeDetail) {
      const reason = ops.freeze_reason ? String(ops.freeze_reason) : "";
      const limit = ops.slip_bps_limit != null ? `${ops.slip_bps_limit} bps` : "50 bps";
      const when = ops.frozen_at ? fmtHktClock(ops.frozen_at) : "";
      freezeDetail.textContent = ops.frozen
        ? `${reason || "人手凍結"}${when ? ` · ${when}` : ""}`
        : `送單環境 ${ops.trading_env || "SIMULATE"}。單筆滑價超過 ${limit} 會凍結。`;
    }

    const plan = ops.locked_plan || {};
    const planValue = $("#sg-ops-plan-value");
    const planDetail = $("#sg-ops-plan-detail");
    if (planValue) planValue.textContent = plan.present ? plan.asof || "已鎖定" : "未鎖定";
    if (planDetail) {
      planDetail.textContent = plan.present
        ? `${plan.locked ? "已鎖定" : "有檔未標鎖定"} · ${targetLabel(plan.target)}`
        : "尚無 locked_plan.json。Once 仍未改為只讀這份檔。";
    }

    const notionalValue = $("#sg-ops-notional-value");
    const notionalDetail = $("#sg-ops-notional-detail");
    if (notionalValue) notionalValue.textContent = money(ops.sleeve_notional);
    if (notionalDetail) {
      const base = ops.notional_base === "buying_power" ? "購買力" : "權益";
      const cap = money(ops.notional_cap);
      notionalDetail.textContent = ops.buying_power_cap
        ? `上限 ${cap} · 已開購買力代替${base}。只會影響下一轉 Signal。`
        : `上限 ${cap} · 名義 = min(上限, ${base})。只會影響下一轉 Signal。`;
    }

    if (bandCard) bandCard.classList.add("is-off");
    const bandValue = $("#sg-ops-band-value");
    const bandDetail = $("#sg-ops-band-detail");
    const rulePct = ops.rebalance_band_rule != null ? `${(Number(ops.rebalance_band_rule) * 100).toFixed(0)}%` : "2%";
    if (bandValue) bandValue.textContent = `規則 ${rulePct}`;
    if (bandDetail) {
      bandDetail.textContent =
        "每日送單帶寬仍是 0，微調單尚未被跳過。進場、清倉、一鍵平倉不受此限。";
    }

    const body = $("#sg-blotter-body");
    if (!body) return;
    const days = Array.isArray(ops.sleeve_days) ? ops.sleeve_days.slice().reverse() : [];
    body.replaceChildren();
    if (!days.length) {
      const tr = document.createElement("tr");
      const td = document.createElement("td");
      td.colSpan = 6;
      td.className = "empty";
      td.textContent = "尚未寫入 sleeve_daily.jsonl。每日流程未呼叫對帳。";
      tr.appendChild(td);
      body.appendChild(tr);
      return;
    }
    for (const row of days) {
      const tr = document.createElement("tr");
      const cells = [
        row.asof || "—",
        money2(row.equity),
        signedMoney(row.day_pnl),
        bps(row.realized_slip_bps),
        row.n_fills == null ? "—" : String(row.n_fills),
        money(row.sleeve_notional),
      ];
      cells.forEach((text, i) => {
        const td = document.createElement("td");
        td.textContent = text;
        if (i === 2) td.className = pnlClass(row.day_pnl);
        if (i === 3 && row.realized_slip_bps != null) {
          td.className = Number(row.realized_slip_bps) > 0 ? "is-down" : "";
        }
        tr.appendChild(td);
      });
      body.appendChild(tr);
    }
  }

  function renderSgStatus(data) {
    if (!data) return;
    statusCache = data;
    submitEnabled = !!data.submit_enabled;
    renderSubmitBadge();

    const sig = data.signal || {};
    const prevAsof = lastSeenAsof;
    if (sig.asof) {
      if (prevAsof && prevAsof !== sig.asof) {
        const when = data.signal_updated_at_hkt || fmtHktClock(sig.generated_at_utc) || "";
        pushActivity(
          `自動更新：訊號日 ${prevAsof} → ${sig.asof}${when ? ` @ ${when}` : ""}`,
          "ok"
        );
        toast(`訊號已更新：${sig.asof}${when ? `（${when}）` : ""}`, "ok");
      }
      lastSeenAsof = sig.asof;
    }
    const bt = data.backtest || {};
    const account = data.account || {};
    const pnl = account.pnl || {};
    const run = data.last_run || {};
    const state = data.state || {};

    const mode = MODE_NAME[sig.mode] || (sig.mode ? "持倉方式未標明" : "尚未算出持倉方式");
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
    const updatedHkt =
      data.signal_updated_at_hkt ||
      fmtHktClock(sig.generated_at_utc) ||
      fmtHktClock(data.signal_updated_at_utc);
    $("#m-asof") && ($("#m-asof").textContent = updatedHkt || sig.asof || "—");

    $("#sg-mode-hero") && ($("#sg-mode-hero").textContent = mode);
    $("#sg-target-hero") && ($("#sg-target-hero").textContent = tgtS);
    const weights = data.weights || sig.weights || { SPY: 0.5, QQQ: 0.5 };
    const bookLabel = Object.entries(weights)
      .map(([k, v]) => `${k} 佔 ${(Number(v) * 100).toFixed(0)}%`)
      .join("，");
    $("#sg-book") && ($("#sg-book").textContent = bookLabel);
    $("#sg-mode") && ($("#sg-mode").textContent = mode);
    $("#sg-target") && ($("#sg-target").textContent = tgtS);

    const flags = ["sticky", "thrust", "mild", "harsh_ret", "harsh_dd", "index_lean", "stock_led", "crowded"]
      .filter((k) => sig[k])
      .map((k) => FLAG_SENTENCE[k])
      .join("");
    $("#sg-flags") && ($("#sg-flags").textContent = flags || "沒有額外規則正在生效。");

    const sub = $("#sg-monitor-sub");
    if (sub) {
      const submitTxt = submitEnabled ? "模擬盤送單已經打開。" : "現在只計算，不會送單。";
      const asofPart = sig.asof ? `訊號日是 ${sig.asof}` : "還沒有訊號日";
      const updPart = updatedHkt ? `上次更新是 ${updatedHkt}` : "還沒有更新時間";
      sub.textContent = `${asofPart}。${updPart}。${submitTxt}`;
    }

    renderOrders($("#preview-list"), sig.preview_orders || [], "尚無預覽單");
    renderOrders($("#fill-list"), run.fills || [], "尚無成交紀錄");
    const st = $("#state-line");
    if (st) {
      st.textContent = state.asof
        ? `訊號日 ${state.asof}。${state.submitted ? "這一天的單已經送出。" : "這一天尚未送出。"}持倉方式是${MODE_NAME[state.mode] || "尚未標明"}。`
        : "還沒有送單狀態。";
    }

    renderFillAudit(data.fill_audit || null);
    renderHoldings(account, data.trd_env);
    renderLedger(data.ledger || null);
    renderDiagnose(data.diagnose || null, data.diagnose_text || "");
    renderOps(data.ops || null);

    const envLine = $("#sg-env-line");
    if (envLine) {
      envLine.textContent = `${envSentence(data.trd_env)} 兩個袖口固定為標普 500 指數基金一半、納斯達克 100 指數基金一半。`;
    }
    const footer = $("#sg-footer-env");
    if (footer) {
      footer.textContent = `${envSentence(data.trd_env)} 買賣明細用來同券商結單對帳。`;
    }

    $("#sg-bt-sg") && ($("#sg-bt-sg").textContent = pct(bt.structure_gate_total_return));
    $("#sg-bt-bh") && ($("#sg-bt-bh").textContent = pct(bt.bench_bh_total_return));
    $("#sg-bt-range") &&
      ($("#sg-bt-range").textContent =
        bt.start && bt.end ? `${bt.start} → ${bt.end}` : "—");
    $("#sg-bt-gate") &&
      ($("#sg-bt-gate").textContent =
        bt.soft_pass == null
          ? "—"
          : `${bt.soft_pass ? "寬鬆檢驗通過" : "寬鬆檢驗未過"}，${bt.hard_pass_beat_both ? "同時打敗兩個基準" : "未同時打敗兩個基準"}`);

    const sel = $("#sg-book-select");
    if (sel && (data.book || sig.book)) sel.value = data.book || sig.book;

    if (sig.mode) setMode(sig.mode);

    const clock = $("#sg-badge-clock");
    if (clock) {
      clock.textContent =
        data.server_time_hkt ||
        fmtHktClock(data.server_time_utc) ||
        (data.server_time_utc ? String(data.server_time_utc).slice(11, 19) + "Z" : "—");
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
        const rule = document.createElement("td");
        const value = document.createElement("td");
        rule.textContent = meaning;
        value.textContent = typeof cfg[key] === "boolean" ? (cfg[key] ? "是" : "否") : fmt(cfg[key]);
        tr.append(rule, value);
        body.appendChild(tr);
      }
      if (!body.children.length) {
        body.innerHTML = `<tr><td colspan="2" class="empty">沒有讀到規則門檻</td></tr>`;
      }
    } catch (err) {
      body.innerHTML = `<tr><td colspan="2" class="empty">載入失敗：${err.message}</td></tr>`;
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
    let lastError = "";

    const applyChunk = (chunk) => {
      const lines = chunk
        .split("\n")
        .filter((l) => l.startsWith("data:"))
        .map((l) => l.slice(5).trim())
        .filter(Boolean);
      for (const line of lines) {
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
          if (level === "error" || evt.phase === "error") {
            lastError = String(evt.message);
          }
          const msg = String(evt.message);
          if (level === "ok" || /=== END ===/.test(msg) || /wrote .*sleeve_diagnose/.test(msg)) {
            ok = true;
          }
        }
        if (evt.phase === "done") ok = !!evt.ok || ok;
        if (evt.data) {
          if (
            evt.data.signal ||
            evt.data.backtest ||
            evt.data.account ||
            evt.data.diagnose ||
            evt.data.diagnose_text
          ) {
            renderSgStatus({ ...(statusCache || {}), ...evt.data, submit_enabled: submitEnabled });
          }
          if (evt.data.submit_enabled != null) {
            submitEnabled = !!evt.data.submit_enabled;
            renderSubmitBadge();
          }
        }
      }
    };

    const drainBuffer = (flushDecoder) => {
      if (flushDecoder) buffer += decoder.decode();
      const chunks = buffer.split("\n\n");
      buffer = chunks.pop() || "";
      for (const chunk of chunks) applyChunk(chunk);
    };

    while (true) {
      const { value, done } = await reader.read();
      if (value) buffer += decoder.decode(value, { stream: !done });
      drainBuffer(false);
      if (done) {
        drainBuffer(true);
        if (buffer.trim()) applyChunk(buffer);
        break;
      }
    }
    setBusy(false);
    try {
      const data = await refreshStatus({ live: false });
      if (data && (data.diagnose || data.diagnose_text)) ok = true;
    } catch {
      /* ignore */
    }
    if (!ok) {
      throw new Error(lastError || `${actionLabel}未成功完成（未收到成功回報；請看活動紀錄上一行）`);
    }
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
    return "V13";
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
            "重算 v13 訊號"
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
            `v13 blend 回測 ${start}→${end}`
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
      } else if (action === "diagnose") {
        withAction(async () => {
          try {
            await consumeSSE("/api/sg/run-diagnose", "袖口診斷（為何 BENCH／近 ERS）");
          } catch (err) {
            // Still paint any prior diagnose from status so the pane is not empty.
            try {
              await refreshStatus({ live: false });
            } catch {
              /* ignore */
            }
            throw err;
          }
        });
      }
    });
  });

  function etParts(now = new Date()) {
    // en-US with timeZone gives America/New_York wall clock parts.
    const fmt = new Intl.DateTimeFormat("en-US", {
      timeZone: "America/New_York",
      weekday: "short",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    });
    const parts = Object.fromEntries(fmt.formatToParts(now).map((p) => [p.type, p.value]));
    const hour = Number(parts.hour === "24" ? 0 : parts.hour);
    const minute = Number(parts.minute);
    const weekday = parts.weekday; // Mon..Sun English short
    const isWeekday = !["Sat", "Sun"].includes(weekday);
    return { hour, minute, weekday, isWeekday, mins: hour * 60 + minute };
  }

  function pollIntervalMs() {
    const { isWeekday, mins } = etParts();
    if (!isWeekday) return 120000;
    // Around official windows: 09:40 and 16:30 ET (±20 min) — poll faster.
    const nearOnce = Math.abs(mins - (9 * 60 + 40)) <= 20;
    const nearSignal = Math.abs(mins - (16 * 60 + 30)) <= 25;
    if (nearOnce || nearSignal) return 15000;
    return 60000;
  }

  async function quietPoll() {
    if (busy || document.hidden) return;
    try {
      await refreshStatus({ live: false });
    } catch {
      /* ignore transient poll errors */
    }
  }

  function schedulePoll() {
    if (pollTimer) clearTimeout(pollTimer);
    pollTimer = setTimeout(async () => {
      await quietPoll();
      schedulePoll();
    }, pollIntervalMs());
  }

  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) quietPoll();
  });
  window.addEventListener("focus", () => quietPoll());

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
      schedulePoll();
      return refreshStatus({ live: true }).catch(() => null);
    })
    .catch(async (err) => {
      pushActivity(`狀態載入失敗：${err.message}`, "error");
      if (/Failed to fetch|NetworkError|Load failed/i.test(String(err?.message || err))) {
        if (promptApiBase("無法連到 API（Failed to fetch）。")) {
          try {
            await refreshStatus({ live: true });
            schedulePoll();
          } catch (e2) {
            pushActivity(`狀態載入失敗：${e2.message}`, "error");
          }
        }
      }
    });
})();
