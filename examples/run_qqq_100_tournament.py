#!/usr/bin/env python3
"""QQQ 100-strategy tournament (a priori logic → fixed params → contest).

Rules:
- Capital $50,000; window 2025-01-01 → 2026-08-06 inclusive
- Costs: Futu US fixed schedule + 3 bps slippage; 2% trade threshold
- Flat start at window open; next-bar open execution
- Parameters chosen from classic literature / common practice ONLY
  (no tuning on the contest window)
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from qresearch.backtest.futu_costs import FutuUsEquityFees
from qresearch.data.loader import validate_ohlcv

OUT = ROOT / "examples" / "data" / "qqq_100_tournament"
CAPITAL = 50_000.0
THR = 0.02
W0 = pd.Timestamp("2025-01-01")
W1 = pd.Timestamp("2026-08-06")


@dataclass(frozen=True)
class Spec:
    id: str
    family: str
    logic: str  # a priori rationale (Chinese/English short)
    params: str
    builder: str  # key into builders


def fetch_qqq() -> pd.DataFrame:
    raw = yf.download("QQQ", start="2017-01-01", end="2026-08-10", auto_adjust=True, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = [c[0].lower() for c in raw.columns]
    else:
        raw.columns = [str(c).lower() for c in raw.columns]
    df = validate_ohlcv(raw[["open", "high", "low", "close", "volume"]].dropna())
    df.index = pd.to_datetime(df.index).tz_localize(None)
    return df


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    h, l, c = df["high"].astype(float), df["low"].astype(float), df["close"].astype(float)
    prev = c.shift(1)
    tr = pd.concat([(h - l).abs(), (h - prev).abs(), (l - prev).abs()], axis=1).max(axis=1)
    return tr.rolling(n, min_periods=n).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0.0)
    dn = -d.clip(upper=0.0)
    au = up.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    ad = dn.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = au / ad.replace(0.0, np.nan)
    return (100 - (100 / (1 + rs))).fillna(50.0)


def realized_vol(close: pd.Series, n: int = 20) -> pd.Series:
    return close.pct_change().rolling(n, min_periods=n).std() * np.sqrt(252.0)


def high_vol_mask(close: pd.Series, lookback: int = 20, mult: float = 1.35) -> pd.Series:
    vol = close.pct_change().rolling(lookback, min_periods=lookback).std()
    base = vol.expanding(min_periods=lookback).median()
    return vol > (base * mult)


def apply_threshold(desired: pd.Series, thr: float = THR) -> pd.Series:
    executed = np.zeros(len(desired), dtype=float)
    prev = 0.0
    for i, w in enumerate(desired.to_numpy(dtype=float)):
        if prev == 0.0 and w != 0.0:
            prev = w
        elif w == 0.0 and prev != 0.0:
            prev = 0.0
        elif abs(w - prev) >= thr:
            prev = w
        executed[i] = prev
    return pd.Series(executed, index=desired.index)


def simulate(df: pd.DataFrame, signal: pd.Series) -> dict:
    fees = FutuUsEquityFees(slippage_bps=3.0)
    desired = signal.astype(float).clip(0.0, 1.0).shift(1).fillna(0.0)
    idx = df.index[(df.index >= W0) & (df.index <= W1)]
    bar = df.loc[idx]
    desired = desired.reindex(idx).fillna(0.0)
    target = apply_threshold(desired, THR)
    open_px = bar["open"].astype(float)
    close_px = bar["close"].astype(float)
    asset_ret = close_px / open_px - 1.0
    gap_ret = (open_px / close_px.shift(1) - 1.0).fillna(0.0)
    turnover = target.diff().abs().fillna(target.abs())
    eq = float(CAPITAL)
    equity = np.empty(len(bar))
    for i in range(len(bar)):
        w = float(target.iloc[i])
        cost = fees.cost_return_on_equity(float(turnover.iloc[i]), eq, float(open_px.iloc[i]))
        r = w * (float(gap_ret.iloc[i]) + float(asset_ret.iloc[i])) - cost
        eq *= 1.0 + r
        equity[i] = eq
    eq_s = pd.Series(equity, index=bar.index)
    r = eq_s.pct_change().fillna(0.0)
    ret = float(eq_s.iloc[-1] / CAPITAL - 1.0)
    sharpe = float(r.mean() / r.std(ddof=0) * np.sqrt(252)) if r.std(ddof=0) > 1e-12 else 0.0
    dd = float((eq_s / eq_s.cummax() - 1.0).min())
    n_trades = int((target.diff().fillna(target).abs() > 1e-12).sum())
    return {
        "total_return": ret,
        "total_pnl_usd": ret * CAPITAL,
        "end_equity_usd": float(eq_s.iloc[-1]),
        "sharpe": sharpe,
        "max_drawdown": dd,
        "avg_exposure": float(target.abs().mean()),
        "n_trades": n_trades,
    }


# ----- signal builders (logic first; params are classic defaults) -----

def sig_buy_hold(df, **_):
    return pd.Series(1.0, index=df.index)


def sig_sma_cross(df, fast, slow):
    c = df["close"].astype(float)
    return (sma(c, fast) > sma(c, slow)).astype(float)


def sig_ema_cross(df, fast, slow):
    c = df["close"].astype(float)
    return (ema(c, fast) > ema(c, slow)).astype(float)


def sig_price_above_ma(df, n):
    c = df["close"].astype(float)
    return (c > sma(c, n)).astype(float)


def sig_hysteresis(df, exit_n, enter_n, off=0.0):
    c = df["close"].astype(float)
    mx, me = sma(c, exit_n), sma(c, enter_n)
    out = np.zeros(len(df))
    pos = False
    for i in range(len(df)):
        if not np.isfinite(mx.iloc[i]):
            out[i] = 0.0
            continue
        if pos:
            if c.iloc[i] < mx.iloc[i]:
                pos = False
        else:
            if np.isfinite(me.iloc[i]) and c.iloc[i] > me.iloc[i]:
                pos = True
        out[i] = 1.0 if pos else off
    return pd.Series(out, index=df.index)


def sig_dual_confirm(df, exit_n=200, enter_n=50, confirm=2, off=0.0):
    c = df["close"].astype(float)
    mx, me = sma(c, exit_n), sma(c, enter_n)
    out = np.zeros(len(df))
    pos = False
    streak = 0
    for i in range(len(df)):
        if not np.isfinite(mx.iloc[i]):
            out[i] = 0.0
            pos = False
            streak = 0
            continue
        if c.iloc[i] < mx.iloc[i]:
            streak += 1
        else:
            streak = 0
        if pos:
            if streak >= confirm:
                pos = False
        else:
            if np.isfinite(me.iloc[i]) and c.iloc[i] > me.iloc[i]:
                pos = True
        out[i] = 1.0 if pos else off
    return pd.Series(out, index=df.index)


def sig_regime_sma(df, fast, slow, vol_mult=1.35):
    c = df["close"].astype(float)
    trend = sma(c, fast) > sma(c, slow)
    hv = high_vol_mask(c, 20, vol_mult)
    return (trend & ~hv).astype(float)


def sig_tsmom(df, lookback):
    c = df["close"].astype(float)
    mom = c / c.shift(lookback) - 1.0
    return (mom > 0).astype(float)


def sig_donchian(df, entry_n, exit_n=None):
    h, l, c = df["high"].astype(float), df["low"].astype(float), df["close"].astype(float)
    exit_n = exit_n or entry_n
    up = h.rolling(entry_n, min_periods=entry_n).max().shift(1)
    dn = l.rolling(exit_n, min_periods=exit_n).min().shift(1)
    out = np.zeros(len(df))
    pos = False
    for i in range(len(df)):
        if not np.isfinite(up.iloc[i]) or not np.isfinite(dn.iloc[i]):
            out[i] = 0.0
            continue
        if not pos and c.iloc[i] > up.iloc[i]:
            pos = True
        elif pos and c.iloc[i] < dn.iloc[i]:
            pos = False
        out[i] = 1.0 if pos else 0.0
    return pd.Series(out, index=df.index)


def sig_atr_trail(df, atr_n=14, mult=3.0, enter_ma=50):
    c = df["close"].astype(float)
    a = atr(df, atr_n)
    ma = sma(c, enter_ma)
    out = np.zeros(len(df))
    pos = False
    peak = 0.0
    stop = 0.0
    for i in range(len(df)):
        if not np.isfinite(a.iloc[i]) or not np.isfinite(ma.iloc[i]):
            out[i] = 0.0
            continue
        if not pos:
            if c.iloc[i] > ma.iloc[i]:
                pos = True
                peak = c.iloc[i]
                stop = peak - mult * a.iloc[i]
        else:
            peak = max(peak, c.iloc[i])
            stop = max(stop, peak - mult * a.iloc[i])
            if c.iloc[i] < stop:
                pos = False
        out[i] = 1.0 if pos else 0.0
    return pd.Series(out, index=df.index)


def sig_rsi_trend(df, n=14, thr=50.0, ma_filter=None):
    c = df["close"].astype(float)
    r = rsi(c, n)
    sig = r > thr
    if ma_filter:
        sig = sig & (c > sma(c, ma_filter))
    return sig.astype(float)


def sig_rsi_mr(df, n=14, buy=30.0, sell=70.0):
    c = df["close"].astype(float)
    r = rsi(c, n)
    out = np.zeros(len(df))
    pos = False
    for i in range(len(df)):
        if r.iloc[i] <= buy:
            pos = True
        elif r.iloc[i] >= sell:
            pos = False
        out[i] = 1.0 if pos else 0.0
    return pd.Series(out, index=df.index)


def sig_macd(df, fast=12, slow=26, signal=9):
    c = df["close"].astype(float)
    line = ema(c, fast) - ema(c, slow)
    sig = ema(line, signal)
    return (line > sig).astype(float)


def sig_vol_target(df, target=0.15, lookback=20, floor=0.0, cap=1.0):
    c = df["close"].astype(float)
    vol = realized_vol(c, lookback).replace(0.0, np.nan)
    w = (target / vol).clip(lower=floor, upper=cap).fillna(0.0)
    return w


def sig_severe(df, severe_ma=100, vol_mult=1.35, off=0.0):
    c = df["close"].astype(float)
    ms = sma(c, severe_ma)
    hv = high_vol_mask(c, 20, vol_mult)
    risk = hv & (c < ms)
    return pd.Series(np.where(risk, off, 1.0), index=df.index, dtype=float)


def sig_stfr(df, exit_ma=200, severe_ma=100, reentry_ma=50, confirm=2, trim=0.5, vol_mult=1.35):
    c = df["close"].astype(float)
    mx, ms, mr = sma(c, exit_ma), sma(c, severe_ma), sma(c, reentry_ma)
    hv = high_vol_mask(c, 20, vol_mult)
    out = np.ones(len(df))
    w = 1.0
    streak = 0
    for i in range(len(df)):
        if not np.isfinite(mx.iloc[i]):
            out[i] = 0.0
            w = 0.0
            streak = 0
            continue
        if c.iloc[i] < mx.iloc[i]:
            streak += 1
        else:
            streak = 0
        severe = (bool(hv.iloc[i]) and c.iloc[i] < ms.iloc[i]) or (streak >= confirm)
        reclaim = np.isfinite(mr.iloc[i]) and c.iloc[i] > mr.iloc[i]
        if severe:
            w = trim
        elif reclaim:
            w = 1.0
        out[i] = w
    return pd.Series(out, index=df.index)


def sig_roc_ma(df, roc_n, ma_n):
    c = df["close"].astype(float)
    roc = c / c.shift(roc_n) - 1.0
    return ((roc > 0) & (c > sma(c, ma_n))).astype(float)


def sig_boll_trend(df, n=20, k=2.0):
    c = df["close"].astype(float)
    mid = sma(c, n)
    sd = c.rolling(n, min_periods=n).std()
    upper = mid + k * sd
    # trend-follow: long above mid; exit below mid (classic midline rule)
    return (c > mid).astype(float)


def sig_boll_break(df, n=20, k=2.0):
    c = df["close"].astype(float)
    mid = sma(c, n)
    sd = c.rolling(n, min_periods=n).std()
    upper = mid + k * sd
    lower = mid - k * sd
    out = np.zeros(len(df))
    pos = False
    for i in range(len(df)):
        if not np.isfinite(upper.iloc[i]):
            continue
        if not pos and c.iloc[i] > upper.iloc[i]:
            pos = True
        elif pos and c.iloc[i] < mid.iloc[i]:
            pos = False
        out[i] = 1.0 if pos else 0.0
    return pd.Series(out, index=df.index)


def sig_seasonality_simple(df, skip_months):
    """A priori: avoid historically weak calendar months (Sell-in-May style variants)."""
    c = df["close"].astype(float)
    m = c.index.month
    long = ~pd.Series(m, index=c.index).isin(skip_months)
    return long.astype(float)


def build_catalog() -> list[tuple[Spec, callable, dict]]:
    """Exactly 100 specs. Params from classics / common practice, not contest-tuned."""
    items: list[tuple[Spec, callable, dict]] = []

    def add(i, family, logic, params, fn, kwargs):
        sid = f"S{i:03d}"
        items.append(
            (
                Spec(sid, family, logic, params, fn.__name__),
                fn,
                kwargs,
            )
        )

    i = 1
    add(i, "benchmark", "被動滿倉對照", "always 1", sig_buy_hold, {})
    i += 1

    # SMA crosses — classic pairs used in textbooks/TA
    for fast, slow in [
        (5, 20),
        (5, 50),
        (10, 20),
        (10, 30),
        (10, 40),
        (10, 50),
        (10, 100),
        (20, 50),
        (20, 100),
        (20, 200),
        (50, 100),
        (50, 200),
    ]:
        add(
            i,
            "sma_cross",
            "黃金/死亡交叉：快線在慢線之上做多",
            f"SMA{fast}>{slow}",
            sig_sma_cross,
            {"fast": fast, "slow": slow},
        )
        i += 1

    # EMA crosses — same classic pairs
    for fast, slow in [
        (5, 20),
        (5, 50),
        (10, 20),
        (10, 30),
        (10, 40),
        (10, 50),
        (12, 26),
        (20, 50),
        (20, 100),
        (50, 200),
    ]:
        add(
            i,
            "ema_cross",
            "EMA 交叉對價格更敏感，邏輯同均線趨勢跟隨",
            f"EMA{fast}>{slow}",
            sig_ema_cross,
            {"fast": fast, "slow": slow},
        )
        i += 1

    # Price above MA filter
    for n in (10, 20, 50, 100, 150, 200):
        add(i, "price_ma", "價格在均線上視為多頭環境，滿倉否則空手", f"close>SMA{n}", sig_price_above_ma, {"n": n})
        i += 1

    # Hysteresis (turtle-like slow exit / faster enter)
    for ex, en in [(200, 50), (200, 100), (200, 20), (150, 50), (100, 20), (100, 50)]:
        add(
            i,
            "hysteresis",
            "慢均線破位出場、快均線站回進場，減少鞭炮式來回",
            f"exit SMA{ex} / enter SMA{en}",
            sig_hysteresis,
            {"exit_n": ex, "enter_n": en, "off": 0.0},
        )
        i += 1

    # Dual confirm on long MA break
    for conf, en in [(1, 50), (2, 50), (3, 50), (2, 20), (2, 100)]:
        add(
            i,
            "dual_confirm",
            "長期均線需連續確認才認作趨勢破壞，避免假跌破",
            f"SMA200 x{conf} / reenter SMA{en}",
            sig_dual_confirm,
            {"exit_n": 200, "enter_n": en, "confirm": conf, "off": 0.0},
        )
        i += 1

    # Regime-aware SMA (vol filter) — S12 family priors
    for fast, slow, vm in [
        (10, 40, 1.20),
        (10, 40, 1.35),
        (10, 40, 1.50),
        (10, 50, 1.35),
        (20, 50, 1.35),
        (5, 20, 1.35),
        (10, 30, 1.35),
        (20, 100, 1.35),
    ]:
        add(
            i,
            "regime_sma",
            "趨勢向上且非高波動才持倉：高波動時趨勢訊號不可靠",
            f"SMA{fast}>{slow}, vol>{vm}x median flat",
            sig_regime_sma,
            {"fast": fast, "slow": slow, "vol_mult": vm},
        )
        i += 1

    # Time-series momentum (Moskowitz et al. style horizons)
    for lb in (21, 63, 126, 189, 252):
        add(i, "tsmom", "時間序列動能：過去N日報酬為正則做多", f"ret({lb})>0", sig_tsmom, {"lookback": lb})
        i += 1

    # Donchian / channel breakout (Turtle priors 20/55)
    for entry, exit_n in [(20, 20), (20, 10), (55, 55), (55, 20), (100, 100), (100, 50)]:
        add(
            i,
            "donchian",
            "通道突破：創新高進場、跌破通道低點出場",
            f"Donchian entry{entry}/exit{exit_n}",
            sig_donchian,
            {"entry_n": entry, "exit_n": exit_n},
        )
        i += 1

    # ATR trailing (Wilder-style risk exit)
    for mult, ema_n in [(2.0, 50), (2.5, 50), (3.0, 50), (3.5, 50), (3.0, 20), (3.0, 100)]:
        add(
            i,
            "atr_trail",
            "站上均線進場，其後用 ATR 追蹤停損鎖住趨勢",
            f"enter SMA{ema_n}, ATR14x{mult}",
            sig_atr_trail,
            {"atr_n": 14, "mult": mult, "enter_ma": ema_n},
        )
        i += 1

    # RSI trend / MR
    for n, thr, maf in [(14, 50, None), (14, 50, 200), (14, 55, 50), (7, 50, None), (21, 50, 100)]:
        add(
            i,
            "rsi_trend",
            "RSI 在中線之上視為多頭動能（可加長期均線過濾）",
            f"RSI{n}>{thr}" + (f" & >SMA{maf}" if maf else ""),
            sig_rsi_trend,
            {"n": n, "thr": thr, "ma_filter": maf},
        )
        i += 1
    for buy, sell in [(30, 70), (25, 75), (20, 80)]:
        add(i, "rsi_mr", "超賣買入、超買賣出的均值回歸", f"RSI14 buy{buy}/sell{sell}", sig_rsi_mr, {"n": 14, "buy": buy, "sell": sell})
        i += 1

    # MACD classic sets
    for f, s, g in [(12, 26, 9), (8, 17, 9), (5, 35, 5)]:
        add(i, "macd", "MACD 柱線交叉：動能由負轉正做多", f"MACD({f},{s},{g})", sig_macd, {"fast": f, "slow": s, "signal": g})
        i += 1

    # Volatility targeting (risk parity style on single asset)
    for tgt in (0.10, 0.12, 0.15, 0.18, 0.20):
        add(
            i,
            "vol_target",
            "波動目標：實現波動高則降倉，使風險近似恆定",
            f"target {tgt:.0%} lookback20 clip[0,1]",
            sig_vol_target,
            {"target": tgt, "lookback": 20, "floor": 0.0, "cap": 1.0},
        )
        i += 1

    # Severe risk trim / flat (offense)
    for sma_n, off in [(50, 0.0), (100, 0.0), (100, 0.5), (50, 0.5)]:
        add(
            i,
            "severe",
            "僅在高波動且跌破中期均線時減倉，其餘滿倉",
            f"HV & <SMA{sma_n} → {off}",
            sig_severe,
            {"severe_ma": sma_n, "vol_mult": 1.35, "off": off},
        )
        i += 1

    # STFR priors (fixed literature-like knobs, not contest-searched)
    for trim, reentry, conf in [(0.5, 50, 2), (0.5, 20, 2), (0.3, 50, 2), (0.0, 50, 2)]:
        add(
            i,
            "stfr",
            "嚴重風險才降倉，站回中期均線快速回滿倉",
            f"trim{trim} reentry{reentry} confirm{conf}",
            sig_stfr,
            {"trim": trim, "reentry_ma": reentry, "confirm": conf},
        )
        i += 1

    # ROC + MA filter
    for roc_n, ma_n in [(20, 50), (60, 100), (120, 200), (250, 200)]:
        add(i, "roc_ma", "中期動能為正且價格在均線上", f"ROC{roc_n}>0 & >SMA{ma_n}", sig_roc_ma, {"roc_n": roc_n, "ma_n": ma_n})
        i += 1

    # Bollinger
    for n, k in [(20, 2.0), (20, 2.5), (10, 2.0)]:
        add(i, "boll_mid", "布林中軌之上視為多頭", f"BB({n},{k}) close>mid", sig_boll_trend, {"n": n, "k": k})
        i += 1
    for n, k in [(20, 2.0), (55, 2.0)]:
        add(i, "boll_break", "突破上軌進場、回到中軌出場", f"BB({n},{k}) breakout", sig_boll_break, {"n": n, "k": k})
        i += 1

    # Calendar (Sell in May & go away variants — classic folklore, a priori)
    for months, label in [
        ((5, 6, 7, 8, 9), "May-Sep off"),
        ((9,), "Sep off"),
    ]:
        add(
            i,
            "calendar",
            "日曆效應：避開傳統較弱月份（民間法則，非資料擬合）",
            label,
            sig_seasonality_simple,
            {"skip_months": months},
        )
        i += 1

    assert len(items) == 100, f"expected 100 strategies, got {len(items)}"
    return items


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    df = fetch_qqq()
    catalog = build_catalog()

    # declare logic ledger BEFORE running contest metrics into a file
    ledger = [
        {
            "id": sp.id,
            "family": sp.family,
            "logic": sp.logic,
            "params": sp.params,
            "builder": sp.builder,
        }
        for sp, _, _ in catalog
    ]
    pd.DataFrame(ledger).to_csv(OUT / "strategy_ledger_apriori.csv", index=False)

    rows = []
    for sp, fn, kwargs in catalog:
        sig = fn(df, **kwargs)
        st = simulate(df, sig)
        rows.append(
            {
                "id": sp.id,
                "family": sp.family,
                "logic": sp.logic,
                "params": sp.params,
                **st,
            }
        )
        print(f"{sp.id} {sp.family:16s} ret={st['total_return']:+.2%} dd={st['max_drawdown']:.2%} trades={st['n_trades']}")

    out = pd.DataFrame(rows)
    bh = float(out.loc[out.family == "benchmark", "total_return"].iloc[0])
    bh_dd = float(out.loc[out.family == "benchmark", "max_drawdown"].iloc[0])
    out["vs_bh_ret"] = out["total_return"] - bh
    out["vs_bh_dd"] = out["max_drawdown"] - bh_dd
    out["beats_bh"] = out["vs_bh_ret"] > 1e-12
    # contest rank: beat return first, then shallower DD
    out = out.sort_values(
        by=["vs_bh_ret", "max_drawdown", "total_return"],
        ascending=[False, False, False],
    ).reset_index(drop=True)
    out.insert(0, "rank", np.arange(1, len(out) + 1))
    out.to_csv(OUT / "tournament_results.csv", index=False)

    winners = out[out["beats_bh"] & (out["family"] != "benchmark")]
    print("\n===== CONTEST WINDOW =====")
    print(f"QQQ B&H: ret={bh:+.2%} dd={bh_dd:.2%} capital=${CAPITAL:,.0f}")
    print(f"Strategies: {len(out)} | Beat B&H: {len(winners)}")
    print("\n===== TOP 15 by vs B&H then DD =====")
    show = out.head(15)[
        ["rank", "id", "family", "params", "total_return", "vs_bh_ret", "beats_bh", "max_drawdown", "sharpe", "n_trades"]
    ].copy()
    for c in ["total_return", "vs_bh_ret", "max_drawdown"]:
        show[c] = show[c].map(lambda v: f"{v:+.2%}" if c != "max_drawdown" else f"{v:.2%}")
    show["sharpe"] = show["sharpe"].map(lambda v: f"{v:.2f}")
    print(show.to_string(index=False))

    if len(winners):
        print("\n===== ALL BEATERS (vs B&H > 0) =====")
        w = winners[
            ["rank", "id", "family", "params", "logic", "total_return", "vs_bh_ret", "max_drawdown", "sharpe", "n_trades"]
        ].copy()
        for c in ["total_return", "vs_bh_ret", "max_drawdown"]:
            w[c] = w[c].map(lambda v: f"{v:+.2%}" if c != "max_drawdown" else f"{v:.2%}")
        w["sharpe"] = w["sharpe"].map(lambda v: f"{v:.2f}")
        print(w.to_string(index=False))
        # among beaters, best DD
        best_dd = winners.sort_values("max_drawdown", ascending=False).iloc[0]
        print(
            f"\nBest DD among beaters: {best_dd.id} {best_dd.params} "
            f"ret={best_dd.total_return:+.2%} vsBH={best_dd.vs_bh_ret:+.2%} dd={best_dd.max_drawdown:.2%}"
        )
    else:
        print("\n===== NO STRATEGY BEAT QQQ B&H IN THIS WINDOW =====")
        closest = out[out.family != "benchmark"].iloc[0]
        print(
            f"Closest: {closest.id} {closest.family} {closest.params} "
            f"ret={closest.total_return:+.2%} vsBH={closest.vs_bh_ret:+.2%}"
        )

    (OUT / "config.json").write_text(
        json.dumps(
            {
                "symbol": "QQQ",
                "capital_usd": CAPITAL,
                "window": [str(W0.date()), str(W1.date())],
                "n_strategies": len(out),
                "costs": "Futu US fixed + 3bps slip; thr 2%; next-bar open; flat start",
                "methodology": "a priori logic families + classic parameter grids; no contest-window tuning",
                "bh_return": bh,
                "n_beat_bh": int(len(winners)),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nsaved → {OUT}")


if __name__ == "__main__":
    main()
