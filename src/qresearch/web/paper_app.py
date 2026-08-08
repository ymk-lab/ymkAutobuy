"""FastAPI control panel for Structure Gate v11 Futu paper trading."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
import math
from typing import Any, AsyncIterator

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parents[3]
STATIC = Path(__file__).resolve().parent / "static"
DEFAULT_OUT = ROOT / "examples" / "data" / "emerging_rs_g1_paper"
DEFAULT_SG_OUT = ROOT / "examples" / "data" / "structure_gate_v11_paper"
DAILY = ROOT / "examples" / "run_emerging_rs_g1_paper_daily.py"
SG_DAILY = ROOT / "examples" / "run_structure_gate_v11_paper_daily.py"
SG_BLEND = ROOT / "examples" / "run_structure_gate_v11_blend.py"
BLEND_SUMMARY = ROOT / "examples" / "data" / "structure_gate_v11_blend" / "summary.json"

app = FastAPI(title="qresearch Structure Gate v11 · Futu Paper", version="0.4.0")
_lock = threading.Lock()


def _out_dir() -> Path:
    path = Path(os.getenv("QRESEARCH_PAPER_OUT", str(DEFAULT_OUT)))
    path.mkdir(parents=True, exist_ok=True)
    (path / "logs").mkdir(parents=True, exist_ok=True)
    return path


def _sg_out_dir() -> Path:
    path = Path(os.getenv("QRESEARCH_SG_PAPER_OUT", str(DEFAULT_SG_OUT)))
    path.mkdir(parents=True, exist_ok=True)
    (path / "logs").mkdir(parents=True, exist_ok=True)
    (path / "backtest").mkdir(parents=True, exist_ok=True)
    return path


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _env_truthy(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _env_submit() -> bool:
    return _env_truthy("QRESEARCH_LB_SUBMIT", "0")


def _env_sg_submit() -> bool:
    return _env_truthy("QRESEARCH_SG_PAPER_SUBMIT", "0")


def _sse(payload: dict[str, Any]) -> str:
    payload = {
        **payload,
        "ts": datetime.now(timezone.utc).strftime("%H:%M:%S"),
    }
    return f"data: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


def _python() -> str:
    venv = ROOT / ".venv" / "bin" / "python"
    return str(venv) if venv.is_file() else sys.executable


def _read_text(path: Path) -> str:
    """Read text as UTF-8 (Windows default cp950 breaks .env with box-drawing chars)."""
    return path.read_text(encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def _load_dotenv() -> None:
    env_path = ROOT / ".env"
    if not env_path.is_file():
        return
    try:
        from dotenv import load_dotenv

        load_dotenv(env_path, override=False, encoding="utf-8")
    except TypeError:
        # older python-dotenv without encoding=
        load_dotenv(env_path, override=False)
    except ImportError:
        for line in _read_text(env_path).splitlines():
            if not line.strip() or line.strip().startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def _account_snapshot() -> dict[str, Any]:
    _load_dotenv()
    sys.path.insert(0, str(ROOT / "src"))
    from qresearch.brokers.futu import FutuBrokerAdapter, has_futu_opend
    from qresearch.brokers.futu.symbols import normalize_symbol

    if not has_futu_opend():
        return {
            "ok": False,
            "error": "無法連線富途 OpenD（檢查 FUTU_OPEND_HOST/PORT，預設 127.0.0.1:11111）",
        }
    broker = FutuBrokerAdapter.from_opend(
        dry_run=True,
        currency=os.getenv("QRESEARCH_LB_CURRENCY", "USD"),
        default_market="US",
        simulate=True,
    )
    try:
        cash = broker.get_cash()
        holdings: list[dict[str, Any]] = []
        positions: dict[str, float] = {}
        # Prefer detailed position query when available.
        if broker.trade_ctx is not None:
            from futu import RET_OK

            ret, data = broker.trade_ctx.position_list_query(trd_env=broker._trd_env())  # noqa: SLF001
            if ret == RET_OK and data is not None and len(data):
                for _, pos in data.iterrows():
                    sym = normalize_symbol(str(pos["code"]), default_market="US")
                    qty = float(pos.get("qty", 0) or 0)
                    if abs(qty) < 1e-12:
                        continue
                    cost = float(pos.get("cost_price", 0) or 0)
                    positions[sym] = positions.get(sym, 0.0) + qty
                    holdings.append(
                        {
                            "symbol": sym,
                            "name": str(pos.get("stock_name", "") or ""),
                            "quantity": qty,
                            "available_quantity": float(pos.get("can_sell_qty", qty) or qty),
                            "currency": "USD",
                            "cost_price": cost,
                        }
                    )
        if not holdings:
            positions = broker.get_positions()
            for sym, qty in positions.items():
                holdings.append(
                    {
                        "symbol": sym,
                        "name": "",
                        "quantity": float(qty),
                        "available_quantity": float(qty),
                        "currency": "USD",
                        "cost_price": None,
                    }
                )

        quotes: dict[str, float] = {}
        quote_meta: dict[str, dict[str, float]] = {}
        syms = sorted(set(positions) | {"SPY.US", "QQQ.US", "SMH.US"})
        quote_warning = None
        try:
            quotes = broker.snapshot_quotes(syms)
            for sym, last in quotes.items():
                quote_meta[sym] = {
                    "last": float(last),
                    "prev_close": float("nan"),
                    "open": float("nan"),
                }
        except Exception as exc:  # noqa: BLE001
            quote_warning = str(exc)

        enriched: list[dict[str, Any]] = []
        total_mv = 0.0
        total_cost = 0.0
        total_upnl = 0.0
        total_day = 0.0
        for h in holdings:
            sym = h["symbol"]
            qty = float(h["quantity"])
            cost = h.get("cost_price")
            meta = quote_meta.get(sym) or {}
            last = quotes.get(sym)
            meta_last = meta.get("last")
            if last is None and meta_last is not None and not math.isnan(meta_last):
                last = meta_last
            prev = meta.get("prev_close")
            if prev is not None and math.isnan(prev):
                prev = None
            row = dict(h)
            row["last"] = last
            row["prev_close"] = prev
            market_value = (last * qty) if last is not None else None
            cost_value = (float(cost) * qty) if cost not in (None, "") else None
            upnl = (
                market_value - cost_value
                if market_value is not None and cost_value is not None
                else None
            )
            upnl_pct = (
                (last / float(cost) - 1.0)
                if last is not None and cost not in (None, "", 0, 0.0)
                else None
            )
            day_pnl = (
                (last - float(prev)) * qty
                if last is not None and prev is not None and prev == prev
                else None
            )
            day_pct = (
                (last / float(prev) - 1.0)
                if last is not None and prev is not None and prev == prev and float(prev) != 0
                else None
            )
            row.update(
                {
                    "market_value": market_value,
                    "cost_value": cost_value,
                    "unrealized_pnl": upnl,
                    "unrealized_pnl_pct": upnl_pct,
                    "day_pnl": day_pnl,
                    "day_pnl_pct": day_pct,
                }
            )
            enriched.append(row)
            if market_value is not None:
                total_mv += market_value
            if cost_value is not None:
                total_cost += cost_value
            if upnl is not None:
                total_upnl += upnl
            if day_pnl is not None:
                total_day += day_pnl

        equity = float(cash) + total_mv
        out: dict[str, Any] = {
            "ok": True,
            "broker": "futu",
            "trd_env": "SIMULATE",
            "cash_usd": cash,
            "positions": positions,
            "quotes": quotes,
            "holdings": enriched,
            "pnl": {
                "market_value": total_mv,
                "cost_value": total_cost,
                "unrealized_pnl": total_upnl,
                "unrealized_pnl_pct": (total_upnl / total_cost) if total_cost > 1e-9 else None,
                "day_pnl": total_day,
                "equity_usd": equity,
            },
        }
        if quote_warning:
            out["quote_warning"] = quote_warning
        return out
    finally:
        broker.close()


def _account_path(*, sg: bool = True) -> Path:
    base = _sg_out_dir() if sg else _out_dir()
    return base / "account_live.json"


def _save_account(snap: dict[str, Any], *, sg: bool = True) -> dict[str, Any]:
    """Persist live account snapshot so UI refresh does not fall back to stale signal."""
    payload = {
        "ok": bool(snap.get("ok", True)),
        "cash_usd": snap.get("cash_usd"),
        "positions": snap.get("positions") or {},
        "quotes": snap.get("quotes") or {},
        "holdings": snap.get("holdings") or [],
        "pnl": snap.get("pnl") or {},
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    if snap.get("quote_warning"):
        payload["quote_warning"] = snap["quote_warning"]
    if snap.get("error"):
        payload["error"] = snap["error"]
        payload["ok"] = False
    _account_path(sg=sg).write_text(json.dumps(payload, indent=2, default=float) + "\n")
    return payload


def _account_from_files(*, sg: bool = True) -> dict[str, Any]:
    live = _read_json(_account_path(sg=sg))
    if live:
        return live
    out = _sg_out_dir() if sg else _out_dir()
    run = _read_json(out / "latest_run.json") or {}
    signal = _read_json(out / "latest_signal.json") or {}
    if run.get("positions_after") is not None or run.get("cash_after") is not None:
        return {
            "ok": True,
            "cash_usd": run.get("cash_after"),
            "positions": run.get("positions_after") or {},
            "quotes": {},
            "updated_at_utc": run.get("generated_at_utc"),
            "source": "latest_run",
        }
    if signal.get("positions") is not None or signal.get("cash_usd") is not None:
        return {
            "ok": True,
            "cash_usd": signal.get("cash_usd"),
            "positions": signal.get("positions") or {},
            "quotes": {},
            "updated_at_utc": signal.get("generated_at_utc"),
            "source": "latest_signal",
        }
    return {"ok": True, "cash_usd": None, "positions": {}, "quotes": {}, "source": "none"}


def _status_payload(*, live: bool = False) -> dict[str, Any]:
    out = _out_dir()
    signal = _read_json(out / "latest_signal.json") or {}
    run = _read_json(out / "latest_run.json") or {}
    state = _read_json(out / "state.json") or {}
    if live:
        snap = _account_snapshot()
        account = (
            _save_account(snap, sg=False)
            if snap.get("ok")
            else {**snap, "positions": {}, "quotes": {}}
        )
    else:
        account = _account_from_files(sg=False)
    return {
        "ok": True,
        "root": str(ROOT),
        "out_dir": str(out),
        "submit_enabled": _env_submit(),
        "sleeve_usd": os.getenv("QRESEARCH_SLEEVE_USD", ""),
        "signal": signal,
        "account": account,
        "last_run": run,
        "state": state,
        "server_time_utc": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/structure-gate")
def structure_gate_page() -> FileResponse:
    """Legacy path — same Structure Gate paper monitor as `/`."""
    return FileResponse(STATIC / "index.html")


@app.get("/api/structure-gate/v8")
def structure_gate_v8_config() -> JSONResponse:
    """Expose Structure Gate knobs (v11 == v8) for the rules UI."""
    sys.path.insert(0, str(ROOT / "src"))
    from dataclasses import asdict

    from qresearch.strategy.structure_gate import V11_BOOK_WEIGHTS, StructureGateConfig

    cfg = StructureGateConfig.v11()
    payload = asdict(cfg)
    # EmergingRSWaveConfig is nested; keep JSON-safe primitives only.
    if payload.get("ers_config") is not None:
        payload["ers_config"] = str(payload["ers_config"])
    return JSONResponse(
        {
            "preset": "v11",
            "rule": "structure_gate_v11_blend",
            "weights": dict(V11_BOOK_WEIGHTS),
            "priority": [
                "harsh_ret",
                "thrust",
                "sticky",
                "harsh_dd",
                "mild",
                "index_lean",
                "stock_led+crowded",
                "ers",
                "cash",
            ],
            "modes": ["cash", "ers", "strong", "bench"],
            "execution": "next_open",
            "broker": "futu",
            "fee_note": "Futu US equity schedule + slippage_bps on notional",
            "config": payload,
            "paper": {
                "script": str(SG_DAILY.relative_to(ROOT)),
                "blend_script": str(SG_BLEND.relative_to(ROOT)),
                "out_dir": str(_sg_out_dir()),
                "submit_env": "QRESEARCH_SG_PAPER_SUBMIT",
                "paper_only": True,
                "trd_env": "SIMULATE",
            },
        }
    )


def _flatten_v11_backtest(summary: dict[str, Any] | None) -> dict[str, Any]:
    """Map v11 blend summary → UI latest_backtest fields."""
    if not summary:
        return {}
    windows = summary.get("windows") or []
    if not windows:
        return {"ok": False, "error": "no windows"}
    w = windows[0]
    gate = w.get("soft_pass")
    if isinstance(gate, dict):
        soft = gate.get("soft_pass")
        hard = gate.get("hard_pass_beat_both")
    else:
        soft = gate
        hard = w.get("hard_pass_beat_both")
    blend = w.get("blend") or {}
    spy = w.get("spy_bh") or {}
    return {
        "ok": True,
        "book": "V11",
        "preset": "v11_blend",
        "start": w.get("start"),
        "end": w.get("end"),
        "structure_gate_total_return": blend.get("total_return"),
        "bench_bh_total_return": spy.get("total_return"),
        "max_drawdown": blend.get("max_drawdown"),
        "soft_pass": soft,
        "hard_pass_beat_both": hard,
        "weights": w.get("weights") or summary.get("design", {}).get("weights"),
        "vs_spy_bh_pp": blend.get("vs_spy_bh_pp"),
    }


def _publish_v11_backtest() -> dict[str, Any]:
    summary = _read_json(BLEND_SUMMARY) or {}
    flat = _flatten_v11_backtest(summary)
    if flat:
        (_sg_out_dir() / "latest_backtest.json").write_text(
            json.dumps(flat, indent=2, default=float) + "\n"
        )
    return flat


def _sg_status_payload(*, live: bool = False) -> dict[str, Any]:
    _load_dotenv()
    out = _sg_out_dir()
    signal = _read_json(out / "latest_signal.json") or {}
    run = _read_json(out / "latest_run.json") or {}
    state = _read_json(out / "state.json") or {}
    backtest = _read_json(out / "latest_backtest.json") or {}
    if live:
        snap = _account_snapshot()
        account = (
            _save_account(snap, sg=True)
            if snap.get("ok")
            else {**snap, "positions": {}, "quotes": {}}
        )
    else:
        account = _account_from_files(sg=True)
    weights = signal.get("weights") or {"SPY": 0.4, "QQQ": 0.3, "SMH": 0.3}
    return {
        "ok": True,
        "out_dir": str(out),
        "book": "V11",
        "preset": signal.get("preset") or "v11",
        "broker": "futu",
        "weights": weights,
        "submit_enabled": _env_sg_submit(),
        "paper_only": _env_truthy("QRESEARCH_SG_PAPER_ONLY", "1"),
        "sleeve_usd": os.getenv("QRESEARCH_SLEEVE_USD", ""),
        "signal": signal,
        "account": account,
        "last_run": run,
        "state": state,
        "backtest": backtest,
        "server_time_utc": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/sg/status")
def api_sg_status(live: int = Query(0, ge=0, le=1)) -> dict[str, Any]:
    return _sg_status_payload(live=bool(live))


@app.get("/api/sg/sync-account")
async def api_sg_sync_account() -> StreamingResponse:
    async def gen() -> AsyncIterator[str]:
        yield _sse({"phase": "start", "message": "處理中：準備連線富途 OpenD…", "level": "info"})
        await asyncio.sleep(0.05)
        if not _lock.acquire(blocking=False):
            yield _sse({"phase": "error", "message": "忙碌中：另一個工作正在執行", "level": "error"})
            yield _sse({"phase": "done", "ok": False})
            return
        try:
            yield _sse({"phase": "progress", "message": "處理中：讀取模擬盤現金與持倉…", "level": "info"})
            snap = await asyncio.to_thread(_account_snapshot)
            if not snap.get("ok"):
                yield _sse({"phase": "error", "message": f"失敗：{snap.get('error')}", "level": "error"})
                yield _sse({"phase": "done", "ok": False})
                return
            saved = await asyncio.to_thread(lambda: _save_account(snap, sg=True))
            npos = len(saved.get("positions") or {})
            pos_txt = (
                ", ".join(f"{k}×{v:g}" for k, v in (saved.get("positions") or {}).items())
                if npos
                else "無持倉"
            )
            pnl = saved.get("pnl") or {}
            yield _sse(
                {
                    "phase": "progress",
                    "message": (
                        f"完成帳戶同步（Futu SIMULATE）：現金 USD {float(saved.get('cash_usd') or 0):,.2f}，"
                        f"權益 {float(pnl.get('equity_usd') or 0):,.2f}，持倉 {pos_txt}"
                    ),
                    "level": "ok",
                    "data": {"account": saved, **snap},
                }
            )
            status = _sg_status_payload(live=False)
            status["account"] = saved
            yield _sse({"phase": "done", "ok": True, "data": status})
        except Exception as exc:  # noqa: BLE001
            yield _sse({"phase": "error", "message": f"錯誤：{exc}", "level": "error"})
            yield _sse({"phase": "done", "ok": False})
        finally:
            _lock.release()

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/api/sg/logs")
def api_sg_logs(tail: int = Query(80, ge=1, le=500)) -> dict[str, Any]:
    log_dir = _sg_out_dir() / "logs"
    files = sorted(log_dir.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    json_runs = sorted(log_dir.glob("run_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if files:
        path = files[0]
        lines = path.read_text(errors="replace").splitlines()
        return {"ok": True, "file": path.name, "lines": lines[-tail:]}
    if json_runs:
        path = json_runs[0]
        text = path.read_text(errors="replace")
        return {"ok": True, "file": path.name, "lines": text.splitlines()[-tail:]}
    return {"ok": True, "file": None, "lines": []}


@app.get("/api/sg/run")
async def api_sg_run(
    mode: str = Query("once", pattern="^(signal|once|backtest)$"),
    submit: int = Query(0, ge=0, le=1),
    refresh: int = Query(1, ge=0, le=1),
    book: str = Query("V11"),
    start: str | None = Query(None, description="Backtest start YYYY-MM-DD"),
    end: str | None = Query(None, description="Backtest end YYYY-MM-DD"),
) -> StreamingResponse:
    async def gen() -> AsyncIterator[str]:
        yield _sse({"phase": "start", "message": "處理中：排隊啟動 Structure Gate v11…", "level": "info"})
        if not _lock.acquire(blocking=False):
            yield _sse({"phase": "error", "message": "忙碌中：請稍候再試", "level": "error"})
            yield _sse({"phase": "done", "ok": False})
            return
        try:
            script = SG_BLEND if mode == "backtest" else SG_DAILY
            if not script.is_file():
                yield _sse({"phase": "error", "message": f"找不到腳本 {script}", "level": "error"})
                yield _sse({"phase": "done", "ok": False})
                return

            # Paper-only hard gate: never allow venue submit when paper_only is off,
            # and never escalate via G1's QRESEARCH_LB_SUBMIT.
            want_submit = bool(submit) and mode == "once"
            if want_submit and not _env_truthy("QRESEARCH_SG_PAPER_ONLY", "1"):
                yield _sse(
                    {
                        "phase": "error",
                        "message": "拒絕：Structure Gate 僅允許 paper trade（QRESEARCH_SG_PAPER_ONLY）",
                        "level": "error",
                    }
                )
                yield _sse({"phase": "done", "ok": False})
                return

            env = os.environ.copy()
            env["QRESEARCH_SG_PAPER_SUBMIT"] = "1" if want_submit else "0"
            env["QRESEARCH_SG_PAPER_ONLY"] = "1"
            env["QRESEARCH_LB_SUBMIT"] = "0"  # never couple to G1 live submit
            env["QRESEARCH_REFRESH_CACHE"] = "1" if refresh else "0"
            env["QRESEARCH_SG_PAPER_OUT"] = str(_sg_out_dir())
            env["QRESEARCH_SG_BOOK"] = "V11"
            env["FUTU_TRD_ENV"] = env.get("FUTU_TRD_ENV") or "SIMULATE"
            env["PYTHONUNBUFFERED"] = "1"
            env["PYTHONIOENCODING"] = "utf-8"
            env["PYTHONUTF8"] = "1"
            env["PYTHONPATH"] = str(ROOT / "src") + (
                os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
            )

            if mode == "backtest":
                label = "v11 blend 回測（不下單）"
            elif want_submit:
                label = "送單到富途模擬盤（paper only）"
            else:
                label = "只算訊號（不下單）"
            yield _sse(
                {
                    "phase": "progress",
                    "message": (
                        f"處理中：mode={mode} book=V11，{label}，"
                        f"refresh={bool(refresh)}"
                    ),
                    "level": "info",
                }
            )
            yield _sse(
                {
                    "phase": "progress",
                    "message": (
                        "處理中：v11 blend 回測…"
                        if mode == "backtest"
                        else "處理中：快取／OpenD 日 K + 計算 Structure Gate v11…"
                    ),
                    "level": "info",
                }
            )

            if mode == "backtest":
                bt_start = (start or os.getenv("QRESEARCH_SG_BT_START") or "2025-08-07").strip()
                bt_end = (end or os.getenv("QRESEARCH_SG_BT_END") or "2026-08-07").strip()
                # Basic guard so bad UI input fails early with a clear message.
                try:
                    from datetime import date as _date

                    d0 = _date.fromisoformat(bt_start[:10])
                    d1 = _date.fromisoformat(bt_end[:10])
                    if d1 < d0:
                        raise ValueError("end before start")
                except Exception as exc:  # noqa: BLE001
                    yield _sse(
                        {
                            "phase": "error",
                            "message": f"回測日期無效：start={bt_start} end={bt_end} ({exc})",
                            "level": "error",
                        }
                    )
                    yield _sse({"phase": "done", "ok": False})
                    return
                env["QRESEARCH_SG_BT_START"] = bt_start[:10]
                env["QRESEARCH_SG_BT_END"] = bt_end[:10]
                yield _sse(
                    {
                        "phase": "progress",
                        "message": f"回測區間 {bt_start[:10]} → {bt_end[:10]}",
                        "level": "info",
                    }
                )
                cmd = [_python(), str(SG_BLEND), bt_start[:10], bt_end[:10]]
            else:
                cmd = [_python(), str(SG_DAILY), mode]

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(ROOT),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            assert proc.stdout is not None
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").rstrip()
                if not text:
                    continue
                if text.startswith("+---") or text.startswith("|"):
                    continue
                yield _sse({"phase": "log", "message": text, "level": "log"})

            code = await proc.wait()
            if mode == "backtest" and code == 0:
                await asyncio.to_thread(_publish_v11_backtest)

            try:
                status = await asyncio.to_thread(lambda: _sg_status_payload(live=True))
            except Exception:
                status = _sg_status_payload(live=False)
            signal = status.get("signal") or {}
            backtest = status.get("backtest") or {}
            if code == 0:
                if mode == "backtest":
                    msg = (
                        f"完成 v11 回測：{backtest.get('start')}→{backtest.get('end')} "
                        f"SG={float(backtest.get('structure_gate_total_return') or 0)*100:.1f}% "
                        f"SPY_BH={float(backtest.get('bench_bh_total_return') or 0)*100:.1f}%"
                    )
                else:
                    tgt = signal.get("target") or {}
                    tgt_s = ", ".join(f"{k} {v:.0%}" for k, v in tgt.items()) or "空手"
                    msg = (
                        f"完成：asof={signal.get('asof')} mode={signal.get('mode')} "
                        f"目標={tgt_s}"
                    )
                yield _sse(
                    {
                        "phase": "progress",
                        "message": msg,
                        "level": "ok",
                        "data": status,
                    }
                )
                yield _sse({"phase": "done", "ok": True, "data": {**status, "exit_code": code}})
            else:
                yield _sse(
                    {
                        "phase": "error",
                        "message": f"失敗：行程結束碼 {code}",
                        "level": "error",
                    }
                )
                yield _sse({"phase": "done", "ok": False, "data": {"exit_code": code}})
        except Exception as exc:  # noqa: BLE001
            yield _sse({"phase": "error", "message": f"錯誤：{exc}", "level": "error"})
            yield _sse({"phase": "done", "ok": False})
        finally:
            _lock.release()

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/api/sg/set-submit")
async def api_sg_set_submit(enabled: int = Query(..., ge=0, le=1)) -> StreamingResponse:
    async def gen() -> AsyncIterator[str]:
        yield _sse({"phase": "start", "message": "處理中：更新 Structure Gate paper 送單開關…", "level": "info"})
        if not _lock.acquire(blocking=False):
            yield _sse({"phase": "error", "message": "忙碌中：請稍候再試", "level": "error"})
            yield _sse({"phase": "done", "ok": False})
            return
        try:
            env_path = ROOT / ".env"
            if not env_path.is_file():
                yield _sse({"phase": "error", "message": "找不到 .env", "level": "error"})
                yield _sse({"phase": "done", "ok": False})
                return

            def _write() -> None:
                lines = []
                found_submit = False
                found_only = False
                for line in _read_text(env_path).splitlines():
                    if line.startswith("QRESEARCH_SG_PAPER_SUBMIT="):
                        lines.append(f"QRESEARCH_SG_PAPER_SUBMIT={enabled}")
                        found_submit = True
                    elif line.startswith("QRESEARCH_SG_PAPER_ONLY="):
                        lines.append("QRESEARCH_SG_PAPER_ONLY=1")
                        found_only = True
                    else:
                        lines.append(line)
                if not found_submit:
                    lines.append(f"QRESEARCH_SG_PAPER_SUBMIT={enabled}")
                if not found_only:
                    lines.append("QRESEARCH_SG_PAPER_ONLY=1")
                _write_text(env_path, "\n".join(lines) + "\n")
                try:
                    env_path.chmod(0o600)
                except OSError:
                    pass
                os.environ["QRESEARCH_SG_PAPER_SUBMIT"] = str(enabled)
                os.environ["QRESEARCH_SG_PAPER_ONLY"] = "1"

            await asyncio.to_thread(_write)
            msg = (
                "已開啟 Structure Gate 模擬盤送單（SG_PAPER_SUBMIT=1）"
                if enabled
                else "已關閉 Structure Gate 送單（只計畫）"
            )
            yield _sse({"phase": "progress", "message": f"完成：{msg}", "level": "ok"})
            yield _sse(
                {
                    "phase": "done",
                    "ok": True,
                    "data": {"submit_enabled": bool(enabled), "paper_only": True},
                }
            )
        except Exception as exc:  # noqa: BLE001
            yield _sse({"phase": "error", "message": f"錯誤：{exc}", "level": "error"})
            yield _sse({"phase": "done", "ok": False})
        finally:
            _lock.release()

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/api/status")
def api_status(live: int = Query(0, ge=0, le=1)) -> dict[str, Any]:
    return _status_payload(live=bool(live))


@app.get("/api/signal")
def api_signal() -> JSONResponse:
    data = _read_json(_out_dir() / "latest_signal.json")
    if data is None:
        return JSONResponse({"ok": False, "error": "尚無 latest_signal.json"}, status_code=404)
    return JSONResponse({"ok": True, "signal": data})


@app.get("/api/logs")
def api_logs(tail: int = Query(80, ge=1, le=500)) -> dict[str, Any]:
    log_dir = _out_dir() / "logs"
    files = sorted(log_dir.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return {"ok": True, "file": None, "lines": []}
    path = files[0]
    lines = path.read_text(errors="replace").splitlines()
    return {"ok": True, "file": path.name, "lines": lines[-tail:]}


@app.get("/api/sync-account")
async def api_sync_account() -> StreamingResponse:
    async def gen() -> AsyncIterator[str]:
        yield _sse({"phase": "start", "message": "處理中：準備連線長橋帳戶…", "level": "info"})
        await asyncio.sleep(0.05)
        if not _lock.acquire(blocking=False):
            yield _sse({"phase": "error", "message": "忙碌中：另一個工作正在執行", "level": "error"})
            yield _sse({"phase": "done", "ok": False})
            return
        try:
            yield _sse({"phase": "progress", "message": "處理中：讀取現金與持倉…", "level": "info"})
            snap = await asyncio.to_thread(_account_snapshot)
            if not snap.get("ok"):
                yield _sse({"phase": "error", "message": f"失敗：{snap.get('error')}", "level": "error"})
                yield _sse({"phase": "done", "ok": False})
                return
            saved = await asyncio.to_thread(_save_account, snap)
            npos = len(saved.get("positions") or {})
            pos_txt = (
                ", ".join(f"{k}×{v:g}" for k, v in (saved.get("positions") or {}).items())
                if npos
                else "無持倉"
            )
            yield _sse(
                {
                    "phase": "progress",
                    "message": (
                        f"完成帳戶同步：現金 USD {float(saved.get('cash_usd') or 0):,.2f}，"
                        f"持倉 {pos_txt}"
                    ),
                    "level": "ok",
                    "data": {"account": saved, **snap},
                }
            )
            yield _sse({"phase": "done", "ok": True, "data": {"account": saved, **snap}})
        except Exception as exc:  # noqa: BLE001
            yield _sse({"phase": "error", "message": f"錯誤：{exc}", "level": "error"})
            yield _sse({"phase": "done", "ok": False})
        finally:
            _lock.release()

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/api/run")
async def api_run(
    mode: str = Query("once", pattern="^(signal|once)$"),
    submit: int = Query(0, ge=0, le=1),
    refresh: int = Query(1, ge=0, le=1),
) -> StreamingResponse:
    async def gen() -> AsyncIterator[str]:
        yield _sse({"phase": "start", "message": "處理中：排隊啟動每日作業…", "level": "info"})
        if not _lock.acquire(blocking=False):
            yield _sse({"phase": "error", "message": "忙碌中：請稍候再試", "level": "error"})
            yield _sse({"phase": "done", "ok": False})
            return
        try:
            if not DAILY.is_file():
                yield _sse({"phase": "error", "message": f"找不到腳本 {DAILY}", "level": "error"})
                yield _sse({"phase": "done", "ok": False})
                return

            env = os.environ.copy()
            env["QRESEARCH_LB_SUBMIT"] = "1" if submit else "0"
            env["QRESEARCH_REFRESH_CACHE"] = "1" if refresh else "0"
            env["QRESEARCH_PAPER_OUT"] = str(_out_dir())
            env["PYTHONUNBUFFERED"] = "1"

            label = "送單到模擬盤" if submit else "只算訊號（不下單）"
            yield _sse(
                {
                    "phase": "progress",
                    "message": f"處理中：模式={mode}，{label}，重新抓資料={bool(refresh)}",
                    "level": "info",
                }
            )
            yield _sse({"phase": "progress", "message": "處理中：向長橋抓取日 K / 計算 G1…", "level": "info"})

            proc = await asyncio.create_subprocess_exec(
                _python(),
                str(DAILY),
                mode,
                cwd=str(ROOT),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            assert proc.stdout is not None
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").rstrip()
                if not text:
                    continue
                # Soften SDK banner noise
                if text.startswith("+---") or text.startswith("|"):
                    continue
                yield _sse({"phase": "log", "message": text, "level": "log"})

            code = await proc.wait()
            signal = _read_json(_out_dir() / "latest_signal.json") or {}
            run = _read_json(_out_dir() / "latest_run.json") or {}
            # Prefer fresh broker snapshot; fall back to run result.
            try:
                account = await asyncio.to_thread(_save_account, await asyncio.to_thread(_account_snapshot))
            except Exception:
                account = _save_account(
                    {
                        "ok": True,
                        "cash_usd": run.get("cash_after", signal.get("cash_usd")),
                        "positions": run.get("positions_after") or signal.get("positions") or {},
                    }
                )
            if code == 0:
                tgt = signal.get("target") or {}
                tgt_s = ", ".join(f"{k} {v:.0%}" for k, v in tgt.items()) or "空手"
                pos = account.get("positions") or {}
                pos_s = ", ".join(f"{k}×{v:g}" for k, v in pos.items()) or "無持倉"
                yield _sse(
                    {
                        "phase": "progress",
                        "message": f"完成：asof={signal.get('asof')} 目標={tgt_s}；帳戶持倉 {pos_s}",
                        "level": "ok",
                        "data": {"signal": signal, "account": account},
                    }
                )
                yield _sse(
                    {
                        "phase": "done",
                        "ok": True,
                        "data": {"signal": signal, "account": account, "exit_code": code},
                    }
                )
            else:
                yield _sse(
                    {
                        "phase": "error",
                        "message": f"失敗：行程結束碼 {code}",
                        "level": "error",
                    }
                )
                yield _sse({"phase": "done", "ok": False, "data": {"exit_code": code}})
        except Exception as exc:  # noqa: BLE001
            yield _sse({"phase": "error", "message": f"錯誤：{exc}", "level": "error"})
            yield _sse({"phase": "done", "ok": False})
        finally:
            _lock.release()

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/api/set-submit")
async def api_set_submit(enabled: int = Query(..., ge=0, le=1)) -> StreamingResponse:
    async def gen() -> AsyncIterator[str]:
        yield _sse({"phase": "start", "message": "處理中：更新 .env 下單開關…", "level": "info"})
        if not _lock.acquire(blocking=False):
            yield _sse({"phase": "error", "message": "忙碌中：請稍候再試", "level": "error"})
            yield _sse({"phase": "done", "ok": False})
            return
        try:
            env_path = ROOT / ".env"
            if not env_path.is_file():
                yield _sse({"phase": "error", "message": "找不到 .env", "level": "error"})
                yield _sse({"phase": "done", "ok": False})
                return

            def _write() -> None:
                lines = []
                found = False
                for line in _read_text(env_path).splitlines():
                    if line.startswith("QRESEARCH_LB_SUBMIT="):
                        lines.append(f"QRESEARCH_LB_SUBMIT={enabled}")
                        found = True
                    else:
                        lines.append(line)
                if not found:
                    lines.append(f"QRESEARCH_LB_SUBMIT={enabled}")
                _write_text(env_path, "\n".join(lines) + "\n")
                try:
                    env_path.chmod(0o600)
                except OSError:
                    pass
                os.environ["QRESEARCH_LB_SUBMIT"] = str(enabled)

            await asyncio.to_thread(_write)
            msg = "已開啟自動送單（SUBMIT=1）" if enabled else "已關閉送單（SUBMIT=0，只計畫）"
            yield _sse({"phase": "progress", "message": f"完成：{msg}", "level": "ok"})
            yield _sse({"phase": "done", "ok": True, "data": {"submit_enabled": bool(enabled)}})
        except Exception as exc:  # noqa: BLE001
            yield _sse({"phase": "error", "message": f"錯誤：{exc}", "level": "error"})
            yield _sse({"phase": "done", "ok": False})
        finally:
            _lock.release()

    return StreamingResponse(gen(), media_type="text/event-stream")


if STATIC.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")

# Load .env when the ASGI module is imported (uvicorn entrypoint).
_load_dotenv()


def main() -> None:
    import uvicorn

    _load_dotenv()
    host = os.getenv("QRESEARCH_UI_HOST", "0.0.0.0")
    port = int(os.getenv("QRESEARCH_UI_PORT", "8787"))
    uvicorn.run("qresearch.web.paper_app:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
