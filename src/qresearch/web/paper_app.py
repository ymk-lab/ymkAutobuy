"""FastAPI control panel for Emerging RS G1 Longbridge paper trading."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parents[3]
STATIC = Path(__file__).resolve().parent / "static"
DEFAULT_OUT = ROOT / "examples" / "data" / "emerging_rs_g1_paper"
DAILY = ROOT / "examples" / "run_emerging_rs_g1_paper_daily.py"

app = FastAPI(title="qresearch G1 Paper", version="0.1.0")
_lock = threading.Lock()


def _out_dir() -> Path:
    path = Path(os.getenv("QRESEARCH_PAPER_OUT", str(DEFAULT_OUT)))
    path.mkdir(parents=True, exist_ok=True)
    (path / "logs").mkdir(parents=True, exist_ok=True)
    return path


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _env_submit() -> bool:
    return os.getenv("QRESEARCH_LB_SUBMIT", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _sse(payload: dict[str, Any]) -> str:
    payload = {
        **payload,
        "ts": datetime.now(timezone.utc).strftime("%H:%M:%S"),
    }
    return f"data: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


def _python() -> str:
    venv = ROOT / ".venv" / "bin" / "python"
    return str(venv) if venv.is_file() else sys.executable


def _load_dotenv() -> None:
    env_path = ROOT / ".env"
    if not env_path.is_file():
        return
    try:
        from dotenv import load_dotenv

        load_dotenv(env_path, override=False)
    except ImportError:
        for line in env_path.read_text().splitlines():
            if not line.strip() or line.strip().startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def _account_snapshot() -> dict[str, Any]:
    _load_dotenv()
    sys.path.insert(0, str(ROOT / "src"))
    from qresearch.brokers.longbridge import LongbridgeBrokerAdapter, has_longbridge_credentials

    if not has_longbridge_credentials():
        return {"ok": False, "error": "缺少 Longbridge 憑證"}
    broker = LongbridgeBrokerAdapter.from_env(
        dry_run=True,
        currency=os.getenv("QRESEARCH_LB_CURRENCY", "USD"),
        default_market="US",
    )
    positions = broker.get_positions()
    cash = broker.get_cash()
    quotes: dict[str, float] = {}
    syms = sorted(set(positions) | {"QQQ.US", "ORLY.US"})
    if broker.quote_ctx is not None and syms:
        try:
            for q in broker.quote_ctx.quote(syms):
                last = getattr(q, "last_done", None)
                if last is not None and float(last) > 0:
                    quotes[str(q.symbol)] = float(last)
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": True,
                "cash_usd": cash,
                "positions": positions,
                "quotes": quotes,
                "quote_warning": str(exc),
            }
    return {"ok": True, "cash_usd": cash, "positions": positions, "quotes": quotes}


def _status_payload() -> dict[str, Any]:
    out = _out_dir()
    signal = _read_json(out / "latest_signal.json") or {}
    run = _read_json(out / "latest_run.json") or {}
    state = _read_json(out / "state.json") or {}
    return {
        "ok": True,
        "root": str(ROOT),
        "out_dir": str(out),
        "submit_enabled": _env_submit(),
        "sleeve_usd": os.getenv("QRESEARCH_SLEEVE_USD", ""),
        "signal": signal,
        "last_run": run,
        "state": state,
        "server_time_utc": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/status")
def api_status() -> dict[str, Any]:
    return _status_payload()


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
            yield _sse(
                {
                    "phase": "progress",
                    "message": (
                        f"完成帳戶同步：現金 USD {snap.get('cash_usd'):,.2f}，"
                        f"持倉 {len(snap.get('positions') or {})} 檔"
                    ),
                    "level": "ok",
                    "data": snap,
                }
            )
            yield _sse({"phase": "done", "ok": True, "data": snap})
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
            if code == 0:
                tgt = signal.get("target") or {}
                tgt_s = ", ".join(f"{k} {v:.0%}" for k, v in tgt.items()) or "空手"
                yield _sse(
                    {
                        "phase": "progress",
                        "message": f"完成：asof={signal.get('asof')} 目標={tgt_s}",
                        "level": "ok",
                        "data": {"signal": signal},
                    }
                )
                yield _sse({"phase": "done", "ok": True, "data": {"signal": signal, "exit_code": code}})
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
                for line in env_path.read_text().splitlines():
                    if line.startswith("QRESEARCH_LB_SUBMIT="):
                        lines.append(f"QRESEARCH_LB_SUBMIT={enabled}")
                        found = True
                    else:
                        lines.append(line)
                if not found:
                    lines.append(f"QRESEARCH_LB_SUBMIT={enabled}")
                env_path.write_text("\n".join(lines) + "\n")
                env_path.chmod(0o600)
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


def main() -> None:
    import uvicorn

    _load_dotenv()
    host = os.getenv("QRESEARCH_UI_HOST", "0.0.0.0")
    port = int(os.getenv("QRESEARCH_UI_PORT", "8787"))
    uvicorn.run("qresearch.web.paper_app:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
