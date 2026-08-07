(() => {
  const $ = (sel) => document.querySelector(sel);
  const activity = $("#activity");
  const toastRoot = $("#toast-root");
  const buttons = [...document.querySelectorAll("[data-action]")];

  let busy = false;
  let submitEnabled = false;
  let statusCache = null;

  function fmtUsd(n) {
    if (n == null || Number.isNaN(Number(n))) return "—";
    return `USD ${Number(n).toLocaleString("en-US", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    })}`;
  }

  function fmtMoney(n, digits = 2) {
    if (n == null || Number.isNaN(Number(n))) return "—";
    return Number(n).toLocaleString("en-US", {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    });
  }

  function fmtPct(n) {
    if (n == null || Number.isNaN(Number(n))) return "—";
    const v = Number(n) * 100;
    const sign = v > 0 ? "+" : "";
    return `${sign}${v.toFixed(2)}%`;
  }

  function pnlClass(n) {
    if (n == null || Number.isNaN(Number(n)) || Math.abs(Number(n)) < 1e-9) return "pnl-flat";
    return Number(n) > 0 ? "pnl-up" : "pnl-down";
  }

  function fmtPnlPair(usd, pct) {
    if (usd == null || Number.isNaN(Number(usd))) return "—";
    const sign = Number(usd) > 0 ? "+" : "";
    const main = `${sign}${fmtMoney(usd)}`;
    return pct == null || Number.isNaN(Number(pct)) ? main : `${main} (${fmtPct(pct)})`;
  }

  function renderHoldings(account) {
    const body = $("#holdings-body");
    const sub = $("#holdings-sub");
    const holdings = account.holdings || [];
    const pnl = account.pnl || {};
    if (sub) {
      const ts = account.updated_at_utc
        ? `更新 ${String(account.updated_at_utc).replace("T", " ").slice(0, 19)} UTC`
        : "同步帳戶後顯示成本、現價與未實現損益";
      sub.textContent = holdings.length
        ? `${ts} · 合計未實現 ${fmtPnlPair(pnl.unrealized_pnl, pnl.unrealized_pnl_pct)}`
        : ts;
    }
    if (!holdings.length) {
      body.innerHTML = `<tr><td colspan="7" class="empty">目前無持倉</td></tr>`;
      return;
    }
    body.innerHTML = holdings
      .map((h) => {
        const upnlCls = pnlClass(h.unrealized_pnl);
        const dayCls = pnlClass(h.day_pnl);
        return `<tr>
          <td><span class="sym">${h.symbol || "—"}</span>${
            h.name ? `<span class="name">${h.name}</span>` : ""
          }</td>
          <td>${fmtMoney(h.quantity, 0)}</td>
          <td>${fmtMoney(h.cost_price)}</td>
          <td>${fmtMoney(h.last)}</td>
          <td>${fmtMoney(h.market_value)}</td>
          <td class="${upnlCls}">${fmtPnlPair(h.unrealized_pnl, h.unrealized_pnl_pct)}</td>
          <td class="${dayCls}">${fmtPnlPair(h.day_pnl, h.day_pnl_pct)}</td>
        </tr>`;
      })
      .join("");
  }

  function toast(message, level = "info") {
    const el = document.createElement("div");
    el.className = `toast ${level}`;
    el.textContent = message;
    toastRoot.appendChild(el);
    setTimeout(() => {
      el.style.opacity = "0";
      el.style.transition = "opacity .25s ease";
      setTimeout(() => el.remove(), 280);
    }, 3200);
  }

  function pushActivity(message, level = "info", ts) {
    const li = document.createElement("li");
    const t = document.createElement("span");
    t.className = "t";
    t.textContent = ts || new Date().toLocaleTimeString("zh-TW", { hour12: false });
    const m = document.createElement("span");
    m.className = level;
    m.textContent = message;
    li.append(t, m);
    activity.prepend(li);
    while (activity.children.length > 120) activity.lastChild.remove();
  }

  function setBusy(on, label = "處理中") {
    busy = on;
    const badge = $("#badge-busy");
    badge.textContent = on ? label : "待命";
    badge.className = on ? "badge badge-busy" : "badge badge-idle";
    buttons.forEach((btn) => {
      btn.disabled = on;
      btn.classList.toggle("is-busy", on && btn.dataset.active === "1");
    });
  }

  function markActive(action) {
    buttons.forEach((btn) => {
      btn.dataset.active = btn.dataset.action === action ? "1" : "0";
    });
  }

  function renderStatus(data) {
    statusCache = data;
    const signal = data.signal || {};
    const target = signal.target || {};
    const keys = Object.keys(target);
    const targetText = keys.length
      ? keys.map((k) => `${k} ${(Number(target[k]) * 100).toFixed(0)}%`).join(" · ")
      : "空手 / Flat";

    $("#hero-target").textContent = targetText;
    const gate = signal.gate_open == null ? "—" : signal.gate_open ? "閘門開" : "閘門關";
    $("#hero-reason").textContent = `asof ${signal.asof || "—"} · ${gate} · 預覽單 ${
      (signal.preview_orders || []).length
    } 筆`;

    const pills = $("#hero-pills");
    pills.innerHTML = "";
    [
      `Gate ${signal.gate || "G1"}`,
      data.submit_enabled ? "送單 ON" : "送單 OFF",
      data.sleeve_usd ? `袖口 ${data.sleeve_usd}` : null,
    ]
      .filter(Boolean)
      .forEach((t) => {
        const s = document.createElement("span");
        s.className = "pill";
        s.textContent = t;
        pills.appendChild(s);
      });

    // Live account (broker) must win over stale signal.positions snapshot.
    const account = data.account || {};
    const pnl = account.pnl || {};
    $("#m-sleeve").textContent = fmtUsd(signal.sleeve_equity_usd);
    $("#m-cash").textContent = fmtUsd(
      account.cash_usd != null ? account.cash_usd : signal.cash_usd
    );
    $("#m-mv").textContent = fmtUsd(pnl.market_value);
    const upnlEl = $("#m-upnl");
    upnlEl.textContent = fmtPnlPair(pnl.unrealized_pnl, pnl.unrealized_pnl_pct);
    upnlEl.className = pnlClass(pnl.unrealized_pnl);
    const dayEl = $("#m-day");
    dayEl.textContent = fmtPnlPair(pnl.day_pnl, null);
    dayEl.className = pnlClass(pnl.day_pnl);
    $("#m-asof").textContent = signal.asof || "—";
    renderHoldings(account);
    $("#signal-view").textContent = JSON.stringify(
      {
        account_pnl: pnl,
        holdings: account.holdings || [],
        target: signal.target,
        asof: signal.asof,
        gate_open: signal.gate_open,
        signal,
      },
      null,
      2
    );
    $("#server-clock").textContent = data.server_time_utc
      ? `伺服器 ${data.server_time_utc.replace("T", " ").slice(0, 19)} UTC`
      : "—";

    submitEnabled = !!data.submit_enabled;
    const b = $("#badge-submit");
    b.textContent = submitEnabled ? "SUBMIT=1 送單" : "SUBMIT=0 只計畫";
    b.className = submitEnabled ? "badge badge-on" : "badge badge-off";
  }

  async function refreshStatus({ quiet = false, live = false } = {}) {
    if (!quiet) {
      pushActivity(
        live ? "處理中：重新整理並向長橋同步帳戶…" : "處理中：重新整理狀態…",
        "info"
      );
      toast(live ? "處理中：向長橋同步帳戶…" : "處理中：重新整理狀態…", "info");
    }
    const res = await fetch(live ? "/api/status?live=1" : "/api/status");
    if (!res.ok) throw new Error(`狀態讀取失敗 (${res.status})`);
    const data = await res.json();
    renderStatus(data);
    if (!quiet) {
      const pos = (data.account && data.account.positions) || {};
      const n = Object.keys(pos).length;
      pushActivity(
        n
          ? `完成：狀態已更新（持倉 ${Object.keys(pos).join(", ")}）`
          : "完成：狀態已更新（目前無持倉）",
        "ok"
      );
      toast("完成：狀態已更新", "ok");
    }
    return data;
  }

  async function consumeSSE(url, actionLabel) {
    markActive(actionLabel);
    setBusy(true, "處理中");
    pushActivity(`處理中：${actionLabel}…`, "info");
    toast(`處理中：${actionLabel}…`, "info");

    const res = await fetch(url);
    if (!res.ok || !res.body) {
      throw new Error(`請求失敗 (${res.status})`);
    }

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
          pushActivity(evt.message, level, evt.ts);
          if (level === "ok" || level === "error" || evt.phase === "start") {
            toast(evt.message, level === "log" ? "info" : level);
          }
        }
        if (evt.phase === "done") ok = !!evt.ok;
        if (evt.data && evt.data.signal) {
          renderStatus({
            ...(statusCache || {}),
            signal: evt.data.signal,
            submit_enabled: submitEnabled,
            server_time_utc: new Date().toISOString(),
          });
        }
        if (evt.data && evt.data.submit_enabled != null) {
          submitEnabled = !!evt.data.submit_enabled;
        }
        if (evt.data && (evt.data.account || evt.data.cash_usd != null) && statusCache) {
          const account = evt.data.account || {
            cash_usd: evt.data.cash_usd,
            positions: evt.data.positions || {},
            quotes: evt.data.quotes || {},
          };
          renderStatus({
            ...statusCache,
            account,
            submit_enabled: submitEnabled,
          });
        }
      }
    }

    setBusy(false);
    markActive("");
    await refreshStatus({ quiet: true });
    if (!ok) throw new Error(`${actionLabel}未成功完成`);
  }

  async function withButton(action, fn) {
    if (busy) {
      toast("忙碌中：請等待目前工作結束", "error");
      pushActivity("忙碌中：請等待目前工作結束", "error");
      return;
    }
    const btn = buttons.find((b) => b.dataset.action === action);
    try {
      if (btn) btn.dataset.active = "1";
      await fn();
    } catch (err) {
      const msg = err?.message || String(err);
      pushActivity(`錯誤：${msg}`, "error");
      toast(`錯誤：${msg}`, "error");
      setBusy(false);
      markActive("");
    }
  }

  buttons.forEach((btn) => {
    btn.addEventListener("click", () => {
      const action = btn.dataset.action;
      if (action === "refresh-status") {
        withButton(action, async () => {
          markActive(action);
          setBusy(true, "處理中");
          // Pull live broker positions so we never flash stale "無持倉" from signal JSON.
          await refreshStatus({ live: true });
          setBusy(false);
          markActive("");
        });
      } else if (action === "sync-account") {
        withButton(action, () => consumeSSE("/api/sync-account", "同步長橋帳戶"));
      } else if (action === "run-signal") {
        withButton(action, () =>
          consumeSSE("/api/run?mode=signal&submit=0&refresh=1", "重算訊號")
        );
      } else if (action === "run-once") {
        const submit = submitEnabled ? 1 : 0;
        withButton(action, () =>
          consumeSSE(
            `/api/run?mode=once&submit=${submit}&refresh=1`,
            submit ? "執行一次（將送單）" : "執行一次（只計畫）"
          )
        );
      } else if (action === "toggle-submit") {
        const next = submitEnabled ? 0 : 1;
        withButton(action, () =>
          consumeSSE(`/api/set-submit?enabled=${next}`, next ? "開啟送單" : "關閉送單")
        );
      } else if (action === "load-logs") {
        withButton(action, async () => {
          markActive(action);
          setBusy(true, "處理中");
          pushActivity("處理中：載入最新日誌…", "info");
          toast("處理中：載入最新日誌…", "info");
          const res = await fetch("/api/logs?tail=60");
          const data = await res.json();
          if (!data.ok) throw new Error("日誌讀取失敗");
          if (!data.file) {
            pushActivity("完成：目前沒有日誌檔", "ok");
            toast("完成：目前沒有日誌檔", "ok");
          } else {
            pushActivity(`完成：已載入 ${data.file}`, "ok");
            toast(`完成：已載入 ${data.file}`, "ok");
            (data.lines || []).slice(-20).forEach((line) => {
              if (line.trim()) pushActivity(line, "log");
            });
          }
          setBusy(false);
          markActive("");
        });
      }
    });
  });

  pushActivity("介面已就緒，正在讀取狀態…", "info");
  refreshStatus({ quiet: false }).catch((err) => {
    pushActivity(`錯誤：${err.message}`, "error");
    toast(`錯誤：${err.message}`, "error");
  });
})();
