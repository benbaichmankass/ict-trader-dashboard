"""ICT Trader Dashboard — Streamlit version with sidebar navigation.

Read-only dashboard for the ICT Trading Bot's FastAPI on the VPS.
Sidebar navigation is collapsible (hamburger on mobile) and the
pages render one at a time so there is no wasted network round-trip
for hidden tabs.

Local dev: `pip install -r requirements.txt && streamlit run streamlit_app.py`
Override the upstream with the BOT_API_URL env var.
"""
from __future__ import annotations

import calendar
import datetime as dt
import json
import os
import re
import time
from typing import Any, Optional
from urllib.parse import quote, urlencode

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
import streamlit.components.v1 as components
import yfinance as yf

try:
    from streamlit_autorefresh import st_autorefresh
    _AUTOREFRESH_AVAILABLE = True
except ImportError:
    _AUTOREFRESH_AVAILABLE = False

BOT_API = os.environ.get("BOT_API_URL", "http://158.178.210.252:8001")
TIMEOUT_S = 10.0
POLL_INTERVAL_S = 10
DEFAULT_LIMIT = 50

# Preview app vs production. The preview Streamlit app (tracking
# claude/web-app-preview) sets DASHBOARD_PREVIEW=1 in its Secrets so it does
# NOT auto-poll the bot by default — you flip "Live data" on only when actively
# testing, sparing the bot from a second always-on poller. Production leaves it
# unset → live by default. Streamlit Cloud surfaces Secrets via st.secrets (not
# os.environ), so read both.
def _cfg(key: str, default: str = "") -> str:
    try:
        if key in st.secrets:
            return str(st.secrets[key])
    except Exception:  # no secrets.toml (local dev) — fall through to env
        pass
    return os.environ.get(key, default)


_PREVIEW_MODE = _cfg("DASHBOARD_PREVIEW").strip().lower() in {"1", "true", "yes"}
_DEFAULT_LIVE = not _PREVIEW_MODE

# Yahoo Finance ticker mapping (dashboard uses bot symbol style for signal matching).
# MES (Micro E-mini S&P 500, IBKR) maps to the full-size continuous E-mini
# front-month `ES=F`, which tracks the identical S&P index level as MES and
# carries far deeper Yahoo history than the micro contract `MES=F`; the same
# micro→full-size reasoning maps MGC (Micro Gold)→`GC=F` and MHG (Micro
# Copper)→`HG=F`. Spot gold (OANDA XAUUSD) also reads `GC=F` — the deepest
# Yahoo proxy for the gold price. This map covers only the symbols that NEED
# translating; `_yf_ticker` below derives everything else by rule (crypto
# `*USDT`→`*-USD`; equities/ETFs pass through unchanged) so a newly traded
# instrument gets a sensible fallback without a dashboard edit.
_YF_SYMBOL: dict[str, str] = {
    "BTCUSDT": "BTC-USD",
    "ETHUSDT": "ETH-USD",
    "SOLUSDT": "SOL-USD",
    "BNBUSDT": "BNB-USD",
    "XRPUSDT": "XRP-USD",
    "MES": "ES=F",
    "MGC": "GC=F",
    "MHG": "HG=F",
    "XAUUSD": "GC=F",
}


def _yf_ticker(symbol: str) -> str:
    """Bot symbol → Yahoo Finance ticker, rule-based beyond the known map."""
    sym = str(symbol).upper()
    if sym in _YF_SYMBOL:
        return _YF_SYMBOL[sym]
    if sym.endswith("USDT"):
        return f"{sym[:-4]}-USD"  # Bybit linear perp → Yahoo crypto pair
    return sym  # equities / ETFs (SPY, QQQ, GLD, …) use the same ticker

# yfinance interval + download period that yields ~200 bars per interval label
_YF_PARAMS: dict[str, dict] = {
    "1m":  {"interval": "1m",  "period": "1d"},
    "5m":  {"interval": "5m",  "period": "5d"},
    "15m": {"interval": "15m", "period": "20d"},
    "1h":  {"interval": "1h",  "period": "30d"},
    "4h":  {"interval": "1h",  "period": "60d"},   # resampled after fetch
    "1d":  {"interval": "1d",  "period": "2y"},
}

# TradingView-inspired palette
_TV_BG     = "#131722"
_TV_GRID   = "#1e2634"
_TV_GREEN  = "#26a69a"
_TV_RED    = "#ef5350"
_TV_TEXT   = "#b2b5be"
_TV_EMA20  = "#f5a623"
_TV_EMA50  = "#9b59b6"
_TV_ENTRY  = "#3d7aed"
_TV_FVG    = "#9c6ade"   # fair-value-gap zone band
_TV_SWEEP  = "#e0a030"   # liquidity-sweep level

# Lightweight Charts overview chart tuning — change these to adjust look/feel
_LC_HEIGHT = 520           # chart height in pixels
_LC_GRID_H = "rgba(42,54,74,0.6)"   # horizontal grid lines
_LC_GRID_V = "rgba(42,54,74,0.0)"   # vertical grid lines (off by default)

_CHART_CONFIG = {
    "scrollZoom": True,
    "displayModeBar": True,
    "modeBarButtonsToRemove": [
        "toImage", "sendDataToCloud", "lasso2d", "select2d", "autoScale2d",
    ],
    "displaylogo": False,
}

st.set_page_config(
    page_title="ICT Trader",
    page_icon="\U0001f4c8",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.html("""
<style>
  :root { --ict-bg:#0a0f1c; --ict-panel:#0d1628; --ict-border:#1a2840; --ict-muted:#6b7488; }
  /* App + sidebar surfaces */
  [data-testid="stAppViewContainer"] { background: #0a0f1c; }
  [data-testid="stSidebar"] {
      background: linear-gradient(180deg, #050c1a 0%, #091428 100%);
      border-right: 1px solid #182040;
  }
  /* Sidebar nav — quiet by default, accent bar on the active item */
  [data-testid="stSidebar"] .stRadio > div { gap: 1px; }
  [data-testid="stSidebar"] .stRadio label {
      padding: 7px 10px; border-radius: 6px; font-size: 0.9rem;
      color: #aeb6c6; border-left: 2px solid transparent; transition: background .12s;
  }
  [data-testid="stSidebar"] .stRadio label:hover { background: #131d36; }
  [data-testid="stSidebar"] .stRadio label:has(input:checked) {
      background: #15233f; border-left: 2px solid #3d7aed; color: #f0f3fa;
  }
  /* Metric cards — flatter, denser, platform-like */
  [data-testid="stMetric"] {
      background: var(--ict-panel);
      border: 1px solid var(--ict-border);
      border-radius: 8px;
      padding: 0.7rem 0.9rem;
  }
  [data-testid="stMetricLabel"] {
      text-transform: uppercase; letter-spacing: 0.06em;
      font-size: 0.7rem !important; color: var(--ict-muted);
  }
  [data-testid="stMetricValue"] { font-size: 1.5rem; font-weight: 600; }
  /* Headers — tighter, with a subtle underline rule */
  h1, h2, h3 { letter-spacing: 0.01em; }
  h1 { font-size: 1.7rem !important; font-weight: 700; }
  h2 { font-size: 1.25rem !important; font-weight: 650;
       padding-bottom: 0.3rem; border-bottom: 1px solid #16203a; }
  [data-testid="stExpander"] { border-color: var(--ict-border); border-radius: 8px; }
  hr { margin: 0.8rem 0; border-color: #16203a; }
  .main .block-container { padding-top: 1.1rem; max-width: 1500px; }
  @media (max-width: 640px) {
      [data-testid="column"] { min-width: 100% !important; }
  }
</style>
""")


# ── Data fetching ──────────────────────────────────────────────────────────────

@st.cache_data(ttl=POLL_INTERVAL_S, show_spinner=False)
def _fetch(path: str) -> tuple[Any, str | None]:
    url = f"{BOT_API}{path}"
    try:
        r = requests.get(url, timeout=TIMEOUT_S)
        r.raise_for_status()
        return r.json(), None
    except requests.HTTPError as e:
        return None, f"HTTP {e.response.status_code} on {path}"
    except requests.Timeout:
        return None, f"Timed out after {TIMEOUT_S}s on {path}"
    except requests.RequestException as e:
        return None, f"Network error on {path}: {e}"
    except ValueError as e:
        return None, f"Bad JSON from {path}: {e}"


def _fetch_parallel(
    paths: list[str], timeout: float = TIMEOUT_S
) -> dict[str, tuple[Any, str | None]]:
    """Fetch several endpoints CONCURRENTLY with a per-request timeout.

    For pages that need multiple independent reads (e.g. the Positions join
    data), firing them in parallel bounds the page's blocking time to the
    slowest single call instead of their sum — so a slow endpoint can't stack
    past the auto-refresh interval and wedge the page in a perpetual reload.
    Plain ``requests`` (not the cached ``_fetch``) so it's safe off the main
    thread; each value is ``(json, None)`` or ``(None, error_str)``.
    """
    import concurrent.futures

    out: dict[str, tuple[Any, str | None]] = {}
    if not paths:
        return out

    def _one(path: str) -> tuple[str, tuple[Any, str | None]]:
        try:
            r = requests.get(f"{BOT_API}{path}", timeout=timeout)
            r.raise_for_status()
            return path, (r.json(), None)
        except requests.RequestException as e:
            return path, (None, f"{type(e).__name__} on {path}")
        except ValueError:
            return path, (None, f"Bad JSON from {path}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(6, len(paths))) as ex:
        for path, res in ex.map(_one, paths):
            out[path] = res
    return out


def _discover_symbols() -> list[str]:
    """Every symbol the bot trades, derived live from the API — never hardcoded.

    Union of (a) per-account ``symbols`` from ``/api/bot/config`` (the
    canonical "what trades" enumeration, mirroring the bot's own
    ``_resolve_tick_symbols``), (b) per-strategy ``symbols`` from the same
    payload's ``strategies`` block (covers bot builds that predate the
    account-symbols exposure), and (c) symbols on open positions (so a
    live position is always selectable even if config briefly fails to
    load). Order follows config declaration order so accounts.yaml drives
    the selector. Static pair only as a last-resort API-down fallback —
    adding an instrument to the bot must surface here with no dashboard
    edit.
    """
    symbols: list[str] = []

    def _add(raw: Any) -> None:
        sym = str(raw or "").strip().upper()
        if sym and sym not in symbols:
            symbols.append(sym)

    cfg, _cfg_err = _fetch("/api/bot/config")
    if isinstance(cfg, dict):
        for acc in cfg.get("accounts") or []:
            if isinstance(acc, dict):
                for s in acc.get("symbols") or []:
                    _add(s)
        strategies = cfg.get("strategies")
        if isinstance(strategies, dict):
            for scfg in strategies.values():
                if isinstance(scfg, dict):
                    for s in scfg.get("symbols") or []:
                        _add(s)
    positions, _pos_err = _fetch("/api/bot/positions")
    for p in positions or []:
        if isinstance(p, dict):
            _add(p.get("symbol"))
    return symbols or ["BTCUSDT", "MES"]


def _overview_chart_symbols(positions: list[dict] | None) -> list[str]:
    """Active symbols for the Overview, with open-position symbols first.

    Same active-symbol set as ``_discover_symbols()`` (every instrument the
    bot is paper/live-trading), re-ordered so any symbol that currently holds
    an open position floats to the top — what's at risk right now is seen
    first. The remainder keeps config-declaration order. ``positions`` is
    passed in (already fetched by the caller) to avoid a duplicate API call.
    """
    symbols = _discover_symbols()
    open_syms = {
        str(p.get("symbol") or "").strip().upper()
        for p in (positions or [])
        if isinstance(p, dict)
    }
    with_pos = [s for s in symbols if s in open_syms]
    without_pos = [s for s in symbols if s not in open_syms]
    return with_pos + without_pos


def _fetch_candles(
    symbol: str, interval: str, limit: int = 200
) -> tuple[pd.DataFrame | None, str | None]:
    """Candles for the chart. Prefer the bot's own exchange feed
    (`/api/bot/candles` — matches what the strategies see); fall back to
    Yahoo Finance when that endpoint is unavailable/empty (e.g. not deployed
    yet, or MES without an IB feed)."""
    bot_df = _fetch_candles_bot(symbol, interval, limit)
    if bot_df is not None and not bot_df.empty:
        return bot_df, None
    return _fetch_candles_yf(symbol, interval, limit)


def _fetch_candles_bot(
    symbol: str, interval: str, limit: int
) -> pd.DataFrame | None:
    """OHLCV from the bot's `/api/bot/candles` endpoint, or None on any miss."""
    data, err = _fetch(
        "/api/bot/candles?" + urlencode(
            {"symbol": symbol, "interval": interval, "limit": limit}
        )
    )
    if err or not isinstance(data, dict):
        return None
    rows = data.get("candles") or []
    if not rows:
        return None
    df = pd.DataFrame(rows)
    if not {"time", "open", "high", "low", "close"}.issubset(df.columns):
        return None
    df["timestamp"] = pd.to_datetime(df["time"], unit="s")
    if "volume" not in df.columns:
        df["volume"] = 0.0
    return df[["timestamp", "open", "high", "low", "close", "volume"]]


@st.cache_data(ttl=30, show_spinner=False)
def _fetch_candles_yf(
    symbol: str, interval: str, limit: int = 200
) -> tuple[pd.DataFrame | None, str | None]:
    try:
        params = _YF_PARAMS.get(interval, _YF_PARAMS["15m"])
        yf_symbol = _yf_ticker(symbol)

        raw = yf.download(
            yf_symbol,
            period=params["period"],
            interval=params["interval"],
            progress=False,
            auto_adjust=True,
        )
        if raw.empty:
            return None, f"No data returned for {yf_symbol}"

        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)

        if interval == "4h":
            raw = raw.resample("4h").agg({
                "Open": "first", "High": "max",
                "Low": "min", "Close": "last", "Volume": "sum",
            }).dropna()

        raw = raw.tail(limit)
        ts = raw.index
        if hasattr(ts, "tz") and ts.tz is not None:
            ts = ts.tz_convert("UTC").tz_localize(None)

        df = pd.DataFrame({
            "timestamp": ts,
            "open":   raw["Open"].to_numpy(),
            "high":   raw["High"].to_numpy(),
            "low":    raw["Low"].to_numpy(),
            "close":  raw["Close"].to_numpy(),
            "volume": raw["Volume"].to_numpy(),
        })
        return df, None
    except Exception as exc:  # noqa: BLE001
        return None, f"Candle fetch error: {exc}"


def fmt_pct(x: float | None) -> str:
    return "—" if x is None else f"{x:.1f}%"


def fmt_usd(x: float | None) -> str:
    return "—" if x is None else f"${x:,.2f}"


def fmt_num(x: float | None) -> str:
    """Plain price formatter (no currency) — BTCUSDT and MES live on very
    different scales, so keep it generic and let the value speak."""
    if x is None:
        return "—"
    try:
        return f"{float(x):,.2f}"
    except (TypeError, ValueError):
        return "—"


# ── Sidebar ───────────────────────────────────────────────────────────────────

PAGES = [
    # Operational, top-to-bottom: glance → performance → what's trading →
    # routing → decisions/fills → raw feed; then ops/diagnostics; then dev tools.
    "Overview", "Performance", "Insights", "Strategies", "Models", "Accounts",
    "Order Packages", "Positions", "Signals", "News",
    "Backtesting", "Promotion", "Health",
    "Data Explorer", "Logs",
]


def _status_dot(color: str) -> str:
    return (
        f"<span style='display:inline-block;width:9px;height:9px;border-radius:50%;"
        f"background:{color};box-shadow:0 0 6px {color};margin-right:6px;'></span>"
    )


# Status dots for collapsible-row LABELS. st.expander labels render markdown,
# not HTML, so the colored-circle emoji is the only way to get a status dot in
# a collapsed row header. Used uniformly by the Strategies / Models / Accounts
# list pages.
_ROW_DOTS = {
    "live": "🟢", "ok": "🟢", "shadow": "🔵", "warn": "🟡",
    "stale": "🟡", "off": "⚫", "dry": "⚫", "bad": "🔴", "unknown": "⚪",
}


def _row_dot(state: str) -> str:
    return _ROW_DOTS.get(state, "⚪")


def _capped_table(df: pd.DataFrame, key: str, cap: int = 10) -> None:
    """Render up to `cap` rows of `df` open by default, with a 'Show all'
    toggle that reveals the rest. `df` should already be ordered newest-first."""
    n = len(df)
    if n == 0:
        return
    if n > cap:
        if not st.checkbox(f"Show all {n} rows", key=key):
            df = df.head(cap)
    st.dataframe(df, hide_index=True, use_container_width=True)


def render_sidebar() -> str:
    with st.sidebar:
        st.markdown(
            "<div style='font-size:1.25rem;font-weight:700;letter-spacing:0.04em;'>"
            "ICT&nbsp;TRADER</div>"
            "<div style='font-size:0.72rem;color:#6b7488;letter-spacing:0.14em;"
            "text-transform:uppercase;'>Trading Console</div>",
            unsafe_allow_html=True,
        )
        st.divider()

        stats, err = _fetch("/api/bot/stats")
        if err:
            st.markdown(
                _status_dot("#888") + "**Bot unreachable**",
                unsafe_allow_html=True,
            )
        elif stats:
            status = stats.get("status", "unknown")
            color = {"running": _TV_GREEN, "paused": "#f5a623",
                     "stopped": _TV_RED}.get(status, "#6b7488")
            st.markdown(
                _status_dot(color)
                + f"**{status.upper()}** · {stats.get('datasource', '?')}",
                unsafe_allow_html=True,
            )

        st.caption(f"{dt.datetime.utcnow().strftime('%H:%M:%S')} UTC")
        st.divider()

        page = st.radio(
            "nav", PAGES,
            label_visibility="collapsed",
        )
        st.divider()
        # Live data: ON auto-polls the bot every POLL_INTERVAL_S. OFF stops the
        # auto-refresh so the app only hits the bot when you load/navigate —
        # default OFF on the preview app (DASHBOARD_PREVIEW=1) so it isn't a
        # second always-on poller against the bot.
        live = st.toggle(
            "Live data", value=_DEFAULT_LIVE, key="live_data",
            help=f"On: auto-refresh every {POLL_INTERVAL_S}s. Off: fetch only "
                 "when you load or navigate (use 'Refresh now').",
        )
        if live:
            st.caption(f"\U0001f7e2 Live · auto-refresh {POLL_INTERVAL_S}s")
        else:
            st.caption("⏸ Paused — not polling the bot")
            st.button("Refresh now", use_container_width=True, key="refresh_now")
        if _PREVIEW_MODE:
            st.caption("preview app")
        # Deploy marker — bump on each release so a stale Streamlit Cloud
        # instance is obvious at a glance. If this date is old, the app
        # needs a reboot/redeploy.
        st.caption("build 2026-06-14 · model scores from order package")

    return page  # type: ignore[return-value]


# ── Lightweight Charts helpers ────────────────────────────────────────────────────

def _lc_candle_data(df: pd.DataFrame) -> list[dict]:
    """Convert OHLCV DataFrame to Lightweight Charts candlestick format (unix seconds)."""
    records = []
    for _, row in df.iterrows():
        ts = row["timestamp"]
        if not isinstance(ts, pd.Timestamp):
            ts = pd.Timestamp(ts)
        records.append({
            "time":  int(ts.timestamp()),
            "open":  float(row["open"]),
            "high":  float(row["high"]),
            "low":   float(row["low"]),
            "close": float(row["close"]),
        })
    return records


def _lc_markers(
    signals: list[dict] | None,
    trades:  list[dict] | None,
    symbol:  str,
) -> list[dict]:
    """Build a sorted Lightweight Charts marker list from signals and closed trades.

    Signal direction: accepts both "direction" (LONG/SHORT) and "side" (buy/sell).
    Trade timestamps: accepts both openedAt/closedAt and openTime/closeTime.
    Marker shapes: arrowUp / arrowDown / circle / square
    Positions:     belowBar / aboveBar / inBar
    """
    markers: list[dict] = []

    if signals:
        sdf = pd.DataFrame(signals)
        if "symbol" in sdf.columns:
            sdf = sdf[sdf["symbol"] == symbol]
        if not sdf.empty and "timestamp" in sdf.columns:
            sdf = sdf.copy()
            sdf["ts_utc"] = pd.to_datetime(sdf["timestamp"], errors="coerce", utc=True)
            sdf = sdf.dropna(subset=["ts_utc"])
            for _, row in sdf.iterrows():
                # Resolve direction: "direction" field (LONG/SHORT) takes priority,
                # fall back to "side" field (buy/sell) for other API shapes.
                raw_dir = str(row.get("direction", row.get("side", "buy"))).lower()
                is_long = raw_dir in ("long", "buy")
                markers.append({
                    "time":     int(row["ts_utc"].timestamp()),
                    "position": "belowBar" if is_long else "aboveBar",
                    "color":    _TV_GREEN  if is_long else _TV_RED,
                    "shape":    "arrowUp"  if is_long else "arrowDown",
                    "text":     "LONG"     if is_long else "SHORT",
                })

    if trades:
        tdf = pd.DataFrame(trades)
        if "symbol" in tdf.columns:
            tdf = tdf[tdf["symbol"] == symbol]
        pnl_col   = "realizedPnl" if "realizedPnl" in tdf.columns else None
        # Accept both field-name conventions from different API versions
        open_col  = next((c for c in ("openedAt",  "openTime")  if c in tdf.columns), None)
        close_col = next((c for c in ("closedAt",  "closeTime") if c in tdf.columns), None)

        # Entry markers (blue circle below bar)
        if not tdf.empty and open_col and "entryPrice" in tdf.columns:
            sub = tdf.copy()
            sub["ts_utc"] = pd.to_datetime(sub[open_col], errors="coerce", utc=True)
            sub = sub.dropna(subset=["ts_utc"])
            for _, row in sub.iterrows():
                markers.append({
                    "time":     int(row["ts_utc"].timestamp()),
                    "position": "belowBar",
                    "color":    _TV_ENTRY,
                    "shape":    "circle",
                    "text":     "Entry",
                })

        # Exit markers (green/red arrow above bar)
        if not tdf.empty and close_col and "exitPrice" in tdf.columns:
            sub = tdf.copy()
            sub["ts_utc"] = pd.to_datetime(sub[close_col], errors="coerce", utc=True)
            sub = sub.dropna(subset=["ts_utc"])
            for _, row in sub.iterrows():
                # realizedPnl is nullable (reconciler-incomplete close shape,
                # ict-trading-bot #2759). A null PnL is "not measured", not a
                # loss — paint it neutral grey rather than fabricating a red
                # loss marker. Green only on a measured profit, red on a
                # measured non-profit.
                raw_pnl = row.get(pnl_col) if pnl_col else None
                try:
                    pnl = None if raw_pnl is None or pd.isna(raw_pnl) else float(raw_pnl)
                except (TypeError, ValueError):
                    pnl = None
                color = _TV_TEXT if pnl is None else (_TV_GREEN if pnl > 0 else _TV_RED)
                markers.append({
                    "time":     int(row["ts_utc"].timestamp()),
                    "position": "aboveBar",
                    "color":    color,
                    "shape":    "arrowDown",
                    "text":     "Exit",
                })

    # Lightweight Charts requires markers sorted by time
    markers.sort(key=lambda m: m["time"])
    return markers


def _lc_price_lines(
    positions: list[dict] | None,
    df:        pd.DataFrame,
    symbol:    str,
) -> list[dict]:
    """TradingView-style horizontal price lines for the overview chart.

    Draws the current price (last candle close) plus, for every OPEN
    position on *symbol*, its entry / stop-loss / take-profit levels —
    the same overlay TradingView shows for a live position. Each is
    nullable on the bot side (older rows), so missing levels are simply
    skipped rather than drawn at 0.
    """
    lines: list[dict] = []

    # Current price — subtle dashed reference line.
    try:
        last_close = float(df["close"].iloc[-1])
        lines.append({
            "price": last_close, "color": "#7f8da3", "lineWidth": 1,
            "lineStyle": 2, "axisLabelVisible": True, "title": "last",
        })
    except (KeyError, IndexError, ValueError, TypeError):
        pass

    for p in positions or []:
        if p.get("symbol") and p.get("symbol") != symbol:
            continue
        side  = str(p.get("side", "")).upper()
        entry = p.get("entryPrice")
        sl    = p.get("stopLoss")
        tp    = p.get("takeProfit")
        if entry is not None:
            lines.append({
                "price": float(entry), "color": _TV_ENTRY, "lineWidth": 2,
                "lineStyle": 0, "axisLabelVisible": True,
                "title": f"{side or 'ENTRY'} entry",
            })
        if sl is not None:
            lines.append({
                "price": float(sl), "color": _TV_RED, "lineWidth": 1,
                "lineStyle": 2, "axisLabelVisible": True, "title": "SL",
            })
        if tp is not None:
            lines.append({
                "price": float(tp), "color": _TV_GREEN, "lineWidth": 1,
                "lineStyle": 2, "axisLabelVisible": True, "title": "TP",
            })
    return lines


def _lc_zone_lines(signals: list[dict] | None, symbol: str, limit: int = 1) -> list[dict]:
    """Price lines for the latest signal's ICT zones (FVG band + sweep).

    Draws only what the strategy itself recorded for its decision (the
    `zones` the bot's /api/bot/signals returns) — never a separately
    computed indicator. Limited to the most-recent `limit` signals so
    the chart shows the current setup rather than every historical zone.
    The lightweight-charts package can't fill boxes, so an FVG renders
    as its two bounding lines; a sweep as a single level.
    """
    if not signals:
        return []
    rows = [
        s for s in signals
        if (not s.get("symbol") or s.get("symbol") == symbol) and s.get("zones")
    ]
    rows.sort(key=lambda s: s.get("timestamp") or "", reverse=True)
    lines: list[dict] = []
    for s in rows[:limit]:
        for z in (s.get("zones") or []):
            kind = z.get("kind")
            if kind == "fvg" and z.get("low") is not None and z.get("high") is not None:
                for price, title in ((z["low"], "FVG ▾"), (z["high"], "FVG ▴")):
                    lines.append({
                        "price": float(price), "color": _TV_FVG, "lineWidth": 1,
                        "lineStyle": 2, "axisLabelVisible": True, "title": title,
                    })
            elif kind == "sweep" and z.get("price") is not None:
                lines.append({
                    "price": float(z["price"]), "color": _TV_SWEEP, "lineWidth": 1,
                    "lineStyle": 1, "axisLabelVisible": True, "title": "sweep",
                })
    return lines


def _lc_ema_data(df: pd.DataFrame, period: int) -> list[dict]:
    """EMA(period) over close as a Lightweight Charts line series."""
    ema = df["close"].astype(float).ewm(span=period, adjust=False).mean()
    out = []
    for ts, v in zip(df["timestamp"], ema):
        t = ts if isinstance(ts, pd.Timestamp) else pd.Timestamp(ts)
        out.append({"time": int(t.timestamp()), "value": float(v)})
    return out


def _lc_volume_data(df: pd.DataFrame) -> list[dict]:
    """Per-bar volume as a Lightweight Charts histogram (green up / red down)."""
    out = []
    for _, row in df.iterrows():
        ts = row["timestamp"]
        t = ts if isinstance(ts, pd.Timestamp) else pd.Timestamp(ts)
        up = float(row["close"]) >= float(row["open"])
        out.append({
            "time": int(t.timestamp()),
            "value": float(row.get("volume") or 0.0),
            "color": "rgba(38,166,154,0.5)" if up else "rgba(239,83,80,0.5)",
        })
    return out


# ── Custom TradingView (lightweight-charts v4) embed ────────────────────────────
#
# A self-contained embed of TradingView's lightweight-charts v4 via
# st.components.v1.html — no npm/React build, the library loads from a CDN.
# Built because the `streamlit-lightweight-charts` wrapper silently drops
# per-series priceLines; the v4 API gives us native createPriceLine() +
# setMarkers(), on-canvas overlay checkboxes (localStorage-persisted) and a
# real fullscreen button — all inside the component, so it doesn't fight
# Streamlit's page layout.

_TV_CHART_HTML = """<!doctype html>
<html><head><meta charset="utf-8">
<script src="https://cdn.jsdelivr.net/npm/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"></script>
<style>
  html,body{margin:0;padding:0;background:__BG__;}
  #wrap{position:relative;width:100%;height:__HEIGHT__px;}
  #chart{position:absolute;inset:0;}
  #ctrl{position:absolute;top:8px;left:8px;z-index:6;display:flex;gap:10px;flex-wrap:wrap;
        background:rgba(13,22,40,0.72);padding:5px 9px;border:1px solid #1a2840;border-radius:7px;
        font:12px -apple-system,Segoe UI,Roboto,sans-serif;color:#b2b5be;}
  #ctrl label{cursor:pointer;user-select:none;display:inline-flex;align-items:center;gap:4px;}
  #ctrl input{accent-color:#3d7aed;margin:0;}
  #fs{position:absolute;top:8px;right:64px;z-index:6;width:28px;height:28px;cursor:pointer;
      background:rgba(13,22,40,0.72);border:1px solid #1a2840;border-radius:6px;color:#b2b5be;
      font-size:15px;line-height:26px;text-align:center;padding:0;}
  #fs:hover{color:#f0f3fa;border-color:#3d7aed;}
  #err{position:absolute;top:50%;left:0;right:0;text-align:center;color:#ef5350;
       font:13px sans-serif;}
  /* Mobile-portrait force-landscape: when in fullscreen on a portrait
     viewport, rotate the chart 90° so the long edge runs across the
     screen. iOS Safari ignores screen.orientation.lock() so this CSS
     trick is the only way to flip the chart without the user physically
     rotating the device. View-only — pan/zoom touch coords inside the
     canvas don't re-map after rotation, so this is a "glance at it" mode. */
  #wrap.rotate{position:fixed;top:0;left:0;width:100vh;height:100vw;
               transform-origin:0 0;transform:rotate(90deg) translateY(-100vh);}
</style></head>
<body><div id="wrap">
  <div id="ctrl"></div>
  <button id="fs" title="Fullscreen">&#9974;</button>
  <div id="chart"></div>
  <div id="err"></div>
</div>
<script>
(function(){
  var D = __PAYLOAD__;
  // Per-symbol localStorage namespace so multiple charts on one page (the
  // Overview renders one chart per active symbol) keep independent scroll
  // position + overlay-toggle state instead of clobbering a shared key.
  var SK = D.storageKey || 'tvc';
  var el = document.getElementById('chart');
  if (typeof LightweightCharts === 'undefined') {
    document.getElementById('err').textContent = 'Chart library failed to load.';
    return;
  }
  var chart, candle, ema, vol;
  var posLines = [], zoneLines = [];
  try {
    chart = LightweightCharts.createChart(el, {
      autoSize: true,
      layout: { background: {type:'solid', color: D.theme.bg}, textColor: D.theme.text },
      grid: { vertLines: {color: D.theme.gridV}, horzLines: {color: D.theme.gridH} },
      crosshair: { mode: 1 },
      rightPriceScale: { borderColor: '#2a364a' },
      timeScale: { borderColor: '#2a364a', timeVisible: true, secondsVisible: false },
    });
    candle = chart.addCandlestickSeries({
      upColor: D.theme.green, downColor: D.theme.red, borderVisible: false,
      wickUpColor: D.theme.green, wickDownColor: D.theme.red,
    });
    candle.setData(D.candles || []);
    ema = chart.addLineSeries({ color: D.theme.ema, lineWidth: 2,
      priceLineVisible: false, lastValueVisible: false });
    ema.setData(D.ema || []);
    vol = chart.addHistogramSeries({ priceFormat: {type:'volume'}, priceScaleId: '' });
    vol.priceScale().applyOptions({ scaleMargins: {top: 0.82, bottom: 0} });
    vol.setData(D.volume || []);
    // Show the most-recent ~150 bars by default but keep the full history
    // scrollable; persist the scroll position across the 10s auto-refresh so
    // scrolling back doesn't snap to "now" on every reload.
    var TS = chart.timeScale();
    var saved = localStorage.getItem(SK + '_lrange');
    var applied = false;
    if (saved) { try { TS.setVisibleLogicalRange(JSON.parse(saved)); applied = true; } catch (e) {} }
    if (!applied) {
      var n = (D.candles || []).length;
      if (n) TS.setVisibleLogicalRange({ from: Math.max(0, n - 150), to: n + 2 });
    }
    TS.subscribeVisibleLogicalRangeChange(function(r){
      if (r) { try { localStorage.setItem(SK + '_lrange', JSON.stringify(r)); } catch (e) {} }
    });
  } catch (e) {
    document.getElementById('err').textContent = 'Chart error: ' + e;
    return;
  }

  function pref(k, d){ var v = localStorage.getItem(SK+'_'+k); return v === null ? d : v === '1'; }
  function setPref(k, v){ localStorage.setItem(SK+'_'+k, v ? '1' : '0'); }

  function mkLine(pl){
    return candle.createPriceLine({
      price: pl.price, color: pl.color, lineWidth: pl.lineWidth || 1,
      lineStyle: (pl.lineStyle == null ? 0 : pl.lineStyle),
      axisLabelVisible: true, title: pl.title || '',
    });
  }
  function rebuildLines(){
    posLines.forEach(function(l){ candle.removePriceLine(l); }); posLines = [];
    zoneLines.forEach(function(l){ candle.removePriceLine(l); }); zoneLines = [];
    if (pref('live', true)) (D.priceLines || []).forEach(function(pl){ posLines.push(mkLine(pl)); });
    if (pref('zones', true)) (D.zoneLines || []).forEach(function(pl){ zoneLines.push(mkLine(pl)); });
  }
  function applyMarkers(){
    var m = [];
    if (pref('signals', true)) m = m.concat(D.signalMarkers || []);
    if (pref('closed', false)) m = m.concat(D.tradeMarkers || []);
    m.sort(function(a,b){ return a.time - b.time; });
    candle.setMarkers(m);
  }
  function applyAll(){
    ema.applyOptions({ visible: pref('ema', true) });
    vol.applyOptions({ visible: pref('volume', true) });
    rebuildLines();
    applyMarkers();
  }

  var defs = {live:true, signals:true, closed:false, zones:true, ema:true, volume:true};
  var labels = [['live','Live'],['signals','Signals'],['closed','Closed'],
                ['zones','Zones'],['ema','EMA'],['volume','Volume']];
  var ctrl = document.getElementById('ctrl');
  labels.forEach(function(c){
    var k = c[0], on = pref(k, defs[k]);
    var lab = document.createElement('label');
    var box = document.createElement('input');
    box.type = 'checkbox'; box.checked = on;
    box.addEventListener('change', function(){ setPref(k, box.checked); applyAll(); });
    lab.appendChild(box); lab.appendChild(document.createTextNode(' ' + c[1]));
    ctrl.appendChild(lab);
  });
  applyAll();

  // Fullscreen + force-landscape:
  //   - Try the standard Fullscreen API (works on desktop, iOS Safari
  //     16.4+, recent Android).
  //   - Try screen.orientation.lock('landscape') for true device-rotation
  //     on Android. iOS Safari ignores this — for portrait iOS the
  //     `.rotate` CSS hack visually flips the chart so it still fills
  //     landscape (view-only; pan/zoom touch coords don't re-map).
  //   - Auto-resize the chart on every transition + on viewport
  //     resize/orientation change while fullscreen, so lightweight-charts
  //     fills the new bounds.
  var wrap = document.getElementById('wrap');
  function isPortrait(){ return window.innerHeight > window.innerWidth; }
  function updateRotate(){
    var fs = !!document.fullscreenElement;
    wrap.classList.toggle('rotate', fs && isPortrait());
    // give the lightweight-charts ResizeObserver a beat to pick up the
    // rotated bounding box, then nudge it explicitly as a belt-and-braces.
    if (chart) { setTimeout(function(){ try { chart.timeScale().fitContent(); } catch(e){} }, 60); }
  }
  document.addEventListener('fullscreenchange', updateRotate);
  document.addEventListener('webkitfullscreenchange', updateRotate);
  window.addEventListener('resize', updateRotate);
  if (window.screen && window.screen.orientation) {
    try { window.screen.orientation.addEventListener('change', updateRotate); } catch (e) {}
  }
  document.getElementById('fs').addEventListener('click', function(){
    try {
      if (document.fullscreenElement) {
        document.exitFullscreen();
        if (window.screen && window.screen.orientation && window.screen.orientation.unlock) {
          try { window.screen.orientation.unlock(); } catch (e) {}
        }
      } else {
        var p = wrap.requestFullscreen();
        if (p && p.then) p.then(function(){
          if (window.screen && window.screen.orientation && window.screen.orientation.lock) {
            try { window.screen.orientation.lock('landscape').catch(function(){}); } catch (e) {}
          }
        }).catch(function(){});
      }
    } catch (e) { /* iframe may disallow fullscreen — already best-effort */ }
  });
})();
</script></body></html>"""


def render_tv_chart(
    df: pd.DataFrame,
    signals:   list[dict] | None,
    trades:    list[dict] | None,
    symbol:    str,
    positions: list[dict] | None = None,
    *,
    height:     int = _LC_HEIGHT,
    ema_period: int = 20,
) -> None:
    """Render the live chart via the custom lightweight-charts v4 embed.

    All series + overlays are sent to the component; the on-canvas checkboxes
    (Live / Signals / Closed / Zones / EMA / Volume) toggle them client-side
    (persisted in localStorage), and the ⤢ button requests fullscreen."""
    candle_data = _lc_candle_data(df)
    if not candle_data:
        st.caption("No candle data.")
        return
    payload = {
        "candles": candle_data,
        "volume": _lc_volume_data(df),
        "ema": _lc_ema_data(df, ema_period),
        "signalMarkers": _lc_markers(signals, None, symbol),
        "tradeMarkers": _lc_markers(None, trades, symbol),
        "priceLines": _lc_price_lines(positions, df, symbol),
        "zoneLines": _lc_zone_lines(signals, symbol),
        # Namespace the chart's localStorage (scroll range + overlay toggles)
        # per symbol so the Overview's stacked per-symbol charts persist
        # independently instead of sharing one global key.
        "storageKey": "tvc_" + re.sub(r"[^A-Za-z0-9]", "", symbol),
        "theme": {
            "bg": _TV_BG, "text": _TV_TEXT, "gridH": _LC_GRID_H, "gridV": _LC_GRID_V,
            "green": _TV_GREEN, "red": _TV_RED, "ema": _TV_EMA20,
        },
    }
    html = (
        _TV_CHART_HTML
        .replace("__PAYLOAD__", json.dumps(payload))
        .replace("__HEIGHT__", str(int(height)))
        .replace("__BG__", _TV_BG)
    )
    components.html(html, height=int(height) + 4, scrolling=False)


def _position_upnl(p: dict, last_price: float | None) -> float:
    """Unrealised PnL for a position — broker-truth first, else computed.

    The bot's `/api/bot/positions` endpoint sources `unrealizedPnl` from
    the broker (Bybit / IB `unrealised_pnl`) and tags each row with
    `unrealizedPnlSource ∈ {"broker", "unavailable"}` (ict-trading-bot
    PR #2953, 2026-06-07). When the broker call lands, the wire value
    is the truth — including a real $0.00 (price at exact entry); we
    must not treat that as "unset".

    Fallback when the source is `"unavailable"` (or the field is
    missing — legacy API): compute mark-to-market from the latest
    candle close.
    """
    source = str(p.get("unrealizedPnlSource") or "").lower()
    raw = p.get("unrealizedPnl")
    if source == "broker" and raw is not None:
        try:
            return float(raw)
        except (TypeError, ValueError):
            pass
    # Legacy / pre-#2953 API didn't tag the source. Trust a non-zero
    # value as broker truth; treat 0/null as "compute fallback" so the
    # dashboard remains usable against an older bot deploy.
    if not source:
        try:
            if raw is not None and float(raw) != 0.0:
                return float(raw)
        except (TypeError, ValueError):
            pass
    if last_price is None:
        return 0.0
    try:
        entry = float(p.get("entryPrice"))
        qty = float(p.get("qty") or 0.0)
        sign = 1.0 if str(p.get("side", "")).lower() in ("buy", "long") else -1.0
        return (last_price - entry) * qty * sign
    except (TypeError, ValueError):
        return 0.0


# ── Overview analytics (trade-performance visualizations) ───────────────────────
#
# Five widgets, all driven by ONE fetch of /api/bot/trades/closed (the endpoint
# caps at 200 rows — ample for this bot's volume) aggregated client-side, so this
# needs no new bot endpoint. A shared "All / per-strategy" filter gates the 24h
# scorecard, the monthly P&L calendar, and the win/loss bar. The per-strategy pie
# is the cross-strategy distribution itself, so it ignores that filter and carries
# its own time-window selector.

ANALYTICS_LOOKBACK_DAYS = 92          # one fetch feeds every widget below
ANALYTICS_MAX_ROWS = 200              # mirrors trades_closed MAX_LIMIT on the bot
_PNL_CALENDAR_SCALE = [[0.0, _TV_RED], [0.5, "#16203a"], [1.0, _TV_GREEN]]


def _style_plotly(fig: go.Figure, height: int) -> go.Figure:
    fig.update_layout(
        height=height,
        paper_bgcolor=_TV_BG,
        plot_bgcolor=_TV_BG,
        font=dict(color=_TV_TEXT, size=12),
        margin=dict(l=8, r=8, t=34, b=8),
        legend=dict(orientation="h", yanchor="bottom", y=1.02,
                    xanchor="right", x=1, bgcolor="rgba(0,0,0,0)"),
    )
    return fig


def _parse_trade_ts(value: Any) -> dt.datetime | None:
    """Parse an ISO-8601 trade timestamp into a tz-naive UTC datetime."""
    if not value:
        return None
    try:
        d = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if d.tzinfo is not None:
        d = d.astimezone(dt.timezone.utc).replace(tzinfo=None)
    return d


def _closed_trades_frame(trades: list[dict]) -> pd.DataFrame:
    """One row per closed trade — strategy, pnl, ts (UTC), outcome, isDemo.

    ``realizedPnl`` is nullable on the wire (bot emits ``null`` for the
    reconciler-incomplete close shape, see ict-trading-bot #2759). Keep
    null as ``NaN`` so pandas aggregations skip those rows by default
    (``sum``/``mean`` with ``skipna=True``), and mark ``outcome='unknown'``
    so the wins/losses/breakeven counts don't fold null rows into
    "breakeven". 2026-06-04 reporting-cleanup follow-up.
    """
    import math

    cols = ["strategy", "pnl", "ts", "outcome", "isDemo"]
    records = []
    for t in trades or []:
        ts = _parse_trade_ts(t.get("closedAt") or t.get("openedAt"))
        if ts is None:
            continue
        raw = t.get("realizedPnl")
        if raw is None:
            pnl = math.nan
        else:
            try:
                pnl = float(raw)
            except (TypeError, ValueError):
                pnl = math.nan
        if math.isnan(pnl):
            outcome = "unknown"
        elif pnl > 0:
            outcome = "win"
        elif pnl < 0:
            outcome = "loss"
        else:
            outcome = "breakeven"
        records.append({
            "strategy": t.get("pattern") or "unknown",
            "pnl": pnl,
            "ts": ts,
            "outcome": outcome,
            "isDemo": bool(t.get("isDemo", False)),
        })
    if not records:
        return pd.DataFrame(columns=cols)
    return pd.DataFrame.from_records(records)[cols]


def _format_closed_trades_df(df: pd.DataFrame) -> pd.DataFrame:
    """Apply the canonical render formatting to a raw closed-trade table.

    Renders nullable PnL columns via :func:`fmt_usd` / :func:`fmt_pct` so
    ``null`` realizedPnl shows as "—" rather than "None" / "0.0". Returns
    a new DataFrame; the input is not mutated.
    """
    out = df.copy()
    if "realizedPnl" in out.columns:
        out["realizedPnl"] = out["realizedPnl"].apply(fmt_usd)
    if "realizedPnlPct" in out.columns:
        out["realizedPnlPct"] = out["realizedPnlPct"].apply(fmt_pct)
    return out


# 2026-06-04 reporting-cleanup — live/demo segment helpers.
#
# Every reporting surface that mixes live + demo accounts now offers
# a "Live money / Demo / All" picker. The bot API ships an ``isDemo``
# flag per trade/position/order-package row (see ict-trading-bot PR
# #2759) so we fetch with ``?include_demo=true`` and filter client-side.
# Default segment is **Live money** — operators see live by default
# and opt into demo when they explicitly want it.

_SEGMENT_CHOICES: list[str] = ["Live money", "Demo", "All"]
_SEGMENT_SLUG: dict[str, str] = {"Live money": "live", "Demo": "demo", "All": "all"}


def _segment_picker(key: str) -> str:
    """Render a Live / Demo / All radio at the top of a reporting page.

    Returns ``"live"`` / ``"demo"`` / ``"all"`` so callers can pass it
    through to ``_segment_filter`` and to API ``include_demo`` params.
    """
    label = st.radio(
        "Segment",
        _SEGMENT_CHOICES,
        index=0,  # Live money by default
        horizontal=True,
        key=key,
        help=(
            "Live money = real-money accounts. Demo = the bybit_1 demo "
            "account (configured ``demo: true`` in accounts.yaml). All "
            "merges both."
        ),
    )
    return _SEGMENT_SLUG[label]


def _segment_filter_rows(rows: list[dict], segment: str) -> list[dict]:
    """Filter a list of row-dicts by segment using each row's ``isDemo``.

    Rows missing the ``isDemo`` key are treated as live (False) — the
    bot returns ``isDemo: false`` for non-demo accounts, but older API
    versions or other sources may omit it entirely.
    """
    if segment == "all":
        return rows
    want_demo = (segment == "demo")
    return [r for r in (rows or []) if bool(r.get("isDemo", False)) == want_demo]


def _segment_filter_frame(df: pd.DataFrame, segment: str) -> pd.DataFrame:
    """Same as :func:`_segment_filter_rows` for a pandas DataFrame with
    an ``isDemo`` column."""
    if segment == "all" or "isDemo" not in df.columns:
        return df
    want_demo = (segment == "demo")
    return df[df["isDemo"] == want_demo].reset_index(drop=True)


def _filter_strategy(df: pd.DataFrame, strategy: str) -> pd.DataFrame:
    if strategy and strategy != "All":
        return df[df["strategy"] == strategy]
    return df


def _summary_window(df: pd.DataFrame, hours: int) -> dict[str, float]:
    if df.empty:
        return {"trades": 0, "wins": 0, "losses": 0, "pnl": 0.0}
    cutoff = dt.datetime.utcnow() - dt.timedelta(hours=hours)
    recent = df[df["ts"] >= cutoff]
    return {
        "trades": int(len(recent)),
        "wins": int((recent["pnl"] > 0).sum()),
        "losses": int((recent["pnl"] < 0).sum()),
        "pnl": float(recent["pnl"].sum()),
    }


def _recent_months(n: int) -> list[tuple[int, int]]:
    """The last *n* calendar months as (year, month), current first."""
    today = dt.datetime.utcnow()
    out: list[tuple[int, int]] = []
    y, m = today.year, today.month
    for _ in range(n):
        out.append((y, m))
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    return out


def _month_pnl(df: pd.DataFrame, year: int, month: int) -> dict[int, float]:
    if df.empty:
        return {}
    m = df[(df["ts"].dt.year == year) & (df["ts"].dt.month == month)]
    if m.empty:
        return {}
    daily = m.groupby(m["ts"].dt.day)["pnl"].sum()
    return {int(k): float(v) for k, v in daily.items()}


def _daily_winloss(df: pd.DataFrame, days: int) -> pd.DataFrame:
    """Per-calendar-day win/loss counts over the last *days* days (gaps filled)."""
    cols = ["date", "wins", "losses"]
    end = pd.Timestamp(dt.datetime.utcnow().date())
    start = end - pd.Timedelta(days=days - 1)
    full = pd.date_range(start, end, freq="D")
    if df.empty:
        return pd.DataFrame({"date": full, "wins": 0, "losses": 0})[cols]
    d = df.copy()
    d["date"] = d["ts"].dt.normalize()
    d = d[d["date"] >= start]
    if d.empty:
        return pd.DataFrame({"date": full, "wins": 0, "losses": 0})[cols]
    grp = d.groupby("date")["pnl"]
    out = pd.DataFrame({
        "wins": grp.apply(lambda s: int((s > 0).sum())),
        "losses": grp.apply(lambda s: int((s < 0).sum())),
    }).reindex(full, fill_value=0).rename_axis("date").reset_index()
    return out[cols]


def build_pnl_calendar(df: pd.DataFrame, year: int, month: int) -> go.Figure:
    """Month grid heat-map: green = profit, red = loss, dark = near-zero / no trades."""
    weeks = calendar.monthcalendar(year, month)   # Monday-first; 0 = padding day
    pnl = _month_pnl(df, year, month)
    z, text, hover = [], [], []
    for week in weeks:
        zr, tr, hr = [], [], []
        for day in week:
            if day == 0:
                zr.append(None)
                tr.append("")
                hr.append("")
                continue
            p = pnl.get(day)
            zr.append(0.0 if p is None else p)
            if p is None:
                tr.append(f"<b>{day}</b>")
                hr.append(f"{year}-{month:02d}-{day:02d} · no trades")
            else:
                tr.append(f"<b>{day}</b><br>{p:+,.0f}")
                hr.append(f"{year}-{month:02d}-{day:02d} · P&L {p:+,.2f}")
        z.append(zr)
        text.append(tr)
        hover.append(hr)
    mags = [abs(v) for v in pnl.values()]
    cmax = max(mags) if mags else 1.0
    fig = go.Figure(go.Heatmap(
        z=z, text=text, customdata=hover,
        texttemplate="%{text}", textfont=dict(size=11),
        hovertemplate="%{customdata}<extra></extra>",
        x=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
        y=[f"W{i + 1}" for i in range(len(weeks))],
        colorscale=_PNL_CALENDAR_SCALE, zmid=0, zmin=-cmax, zmax=cmax,
        xgap=3, ygap=3, showscale=True,
        colorbar=dict(title="P&L $", thickness=10, len=0.9),
    ))
    fig.update_xaxes(side="top", showgrid=False, fixedrange=True)
    fig.update_yaxes(autorange="reversed", showgrid=False,
                     showticklabels=False, fixedrange=True)
    return _style_plotly(fig, 300)


def build_winloss_bar(daily: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_bar(x=daily["date"], y=daily["wins"], name="Wins", marker_color=_TV_GREEN)
    fig.add_bar(x=daily["date"], y=daily["losses"], name="Losses", marker_color=_TV_RED)
    fig.update_layout(barmode="stack")
    fig.update_xaxes(showgrid=False, fixedrange=True)
    fig.update_yaxes(showgrid=True, gridcolor=_LC_GRID_H, fixedrange=True,
                     rangemode="tozero", dtick=1)
    return _style_plotly(fig, 320)


def build_strategy_pie(df: pd.DataFrame, days: int) -> tuple[go.Figure, int]:
    cutoff = dt.datetime.utcnow() - dt.timedelta(days=days)
    d = df[df["ts"] >= cutoff]
    counts = d.groupby("strategy").size().sort_values(ascending=False)
    fig = go.Figure(go.Pie(
        labels=counts.index.tolist(), values=[int(v) for v in counts.values],
        hole=0.45, textinfo="label+percent",
        hovertemplate="%{label}: %{value} trades (%{percent})<extra></extra>",
    ))
    return _style_plotly(fig, 340), int(counts.sum())


def build_daily_pnl_fig(rows: list[dict], height: int = 240) -> go.Figure | None:
    """Daily realised-P&L bars + cumulative line from /api/pnl/history rows
    (`[{date, pnl, trades}]`). Returns None when the rows lack the fields."""
    if not rows:
        return None
    df = pd.DataFrame(rows)
    if not {"date", "pnl"}.issubset(df.columns):
        return None
    df = df.copy()
    df["pnl"] = pd.to_numeric(df["pnl"], errors="coerce").fillna(0.0)
    df["cumulative"] = df["pnl"].cumsum()
    fig = go.Figure()
    fig.add_bar(
        x=df["date"], y=df["pnl"], name="Daily P&L",
        marker_color=[_TV_GREEN if v >= 0 else _TV_RED for v in df["pnl"]],
    )
    fig.add_scatter(
        x=df["date"], y=df["cumulative"], name="Cumulative",
        line={"color": _TV_EMA20, "width": 2},
    )
    fig.update_xaxes(showgrid=False, fixedrange=True)
    fig.update_yaxes(showgrid=True, gridcolor=_LC_GRID_H, fixedrange=True,
                     zeroline=True, zerolinecolor="#2a3a5a")
    return _style_plotly(fig, height)


def build_cumulative_pnl_fig(frame: pd.DataFrame, height: int = 220) -> go.Figure | None:
    """Cumulative realised-P&L trajectory from a `_closed_trades_frame`."""
    if frame.empty:
        return None
    d = frame.sort_values("ts").copy()
    d["cum"] = d["pnl"].cumsum()
    fig = go.Figure(go.Scatter(
        x=d["ts"], y=d["cum"], mode="lines",
        line={"color": _TV_EMA20, "width": 2},
        fill="tozeroy", fillcolor="rgba(245,166,35,0.08)",
        hovertemplate="%{x|%Y-%m-%d %H:%M}<br>cum P&L %{y:,.2f}<extra></extra>",
    ))
    fig.update_xaxes(showgrid=False, fixedrange=True)
    fig.update_yaxes(showgrid=True, gridcolor=_LC_GRID_H, fixedrange=True,
                     zeroline=True, zerolinecolor="#2a3a5a")
    return _style_plotly(fig, height)


def _strategy_breakdown(df: pd.DataFrame) -> pd.DataFrame:
    """Per-strategy performance table over the supplied closed-trade frame."""
    cols = ["Strategy", "Trades", "Win rate %", "Expectancy $", "Total P&L $"]
    if df.empty:
        return pd.DataFrame(columns=cols)
    rows = []
    for name, sub in df.groupby("strategy"):
        n = len(sub)
        total = float(sub["pnl"].sum())
        rows.append({
            "Strategy": name,
            "Trades": n,
            "Win rate %": round(int((sub["pnl"] > 0).sum()) / n * 100, 1) if n else 0.0,
            "Expectancy $": round(total / n, 2) if n else 0.0,
            "Total P&L $": round(total, 2),
        })
    return (pd.DataFrame(rows)
            .sort_values("Total P&L $", ascending=False)
            .reset_index(drop=True))


@st.cache_data(ttl=POLL_INTERVAL_S, show_spinner=False)
def _analytics_frame(include_demo: bool = False) -> tuple[pd.DataFrame, int, str | None]:
    """One closed-trade fetch (capped) → tidy frame, for the analytics widgets.

    ``include_demo=True`` opts into the live+demo response so the page
    can offer a Live / Demo / All segment picker over a single fetch.
    """
    since = (dt.datetime.utcnow()
             - dt.timedelta(days=ANALYTICS_LOOKBACK_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    params: dict[str, str] = {"limit": str(ANALYTICS_MAX_ROWS), "since": since}
    if include_demo:
        params["include_demo"] = "true"
    trades, err = _fetch("/api/bot/trades/closed?" + urlencode(params))
    if err:
        return pd.DataFrame(columns=["strategy", "pnl", "ts", "outcome", "isDemo"]), 0, err
    trades = trades or []
    return _closed_trades_frame(trades), len(trades), None


def render_trade_analytics() -> None:
    """The performance deep-dive: filter + headline metrics + equity curve +
    calendar + win/loss bar + strategy pie + per-strategy breakdown.

    Renders a Live / Demo / All segment picker first so the operator can
    inspect each segment in isolation without mixing real-money KPIs with
    demo activity.
    """
    segment = _segment_picker("perf_segment")
    df, raw_count, err = _analytics_frame(include_demo=True)
    if err:
        st.info(f"Trade analytics unavailable: {err}")
        return
    df = _segment_filter_frame(df, segment)
    if df.empty:
        if segment == "live":
            st.caption("No closed live-money trades yet — analytics will populate as trades close.")
        elif segment == "demo":
            st.caption("No closed demo trades in the lookback window.")
        else:
            st.caption("No closed trades yet — analytics will populate as trades close.")
        return

    strategies = sorted(df["strategy"].unique().tolist())
    choice = st.radio(
        "Strategy", ["All"] + strategies, horizontal=True, key="perf_strat",
        help="Filters the headline metrics, the equity curve, the monthly P&L "
             "calendar and the win/loss bar. The pie + per-strategy table below "
             "always show the full cross-strategy split.",
    )
    fdf = _filter_strategy(df, choice)

    n = len(fdf)
    total_pnl = float(fdf["pnl"].sum())
    wr = round(int((fdf["pnl"] > 0).sum()) / n * 100, 1) if n else 0.0
    exp = round(total_pnl / n, 2) if n else 0.0
    m = st.columns(4)
    m[0].metric(f"Trades · {ANALYTICS_LOOKBACK_DAYS}d", n)
    m[1].metric("Win rate", f"{wr:.1f}%")
    m[2].metric("Expectancy", fmt_usd(exp))
    m[3].metric("Total P&L", fmt_usd(total_pnl))
    s24 = _summary_window(fdf, 24)
    g = st.columns(4)
    g[0].metric("Trades · 24h", s24["trades"])
    g[1].metric("Wins · 24h", s24["wins"])
    g[2].metric("Losses · 24h", s24["losses"])
    g[3].metric("P&L · 24h", fmt_usd(s24["pnl"]))
    if raw_count >= ANALYTICS_MAX_ROWS:
        st.caption(
            f"Aggregating the most recent {ANALYTICS_MAX_ROWS} closed trades "
            "(bot endpoint cap) — older trades in the window are not included."
        )

    st.markdown("**Equity curve · cumulative realised P&L**")
    eq = build_cumulative_pnl_fig(fdf, height=260)
    if eq is not None:
        st.plotly_chart(eq, use_container_width=True, config={"displayModeBar": False})
    else:
        st.caption("No trades for the selected strategy.")

    cal_col, bar_col = st.columns(2)
    with cal_col:
        st.markdown("**Monthly P&L calendar**")
        months = _recent_months(3)
        ym = st.selectbox(
            "Month", months, key="perf_month",
            format_func=lambda v: f"{calendar.month_name[v[1]]} {v[0]}",
        )
        st.plotly_chart(
            build_pnl_calendar(fdf, ym[0], ym[1]),
            use_container_width=True, config={"displayModeBar": False},
        )
        st.caption("Green = net-profit day · red = net-loss day · "
                   "darker = closer to flat.")
    with bar_col:
        st.markdown("**Wins vs losses per day**")
        win = st.selectbox("Window (days)", [7, 14, 30, 60, 90], index=0,
                           key="perf_barwin")
        st.plotly_chart(
            build_winloss_bar(_daily_winloss(fdf, win)),
            use_container_width=True, config={"displayModeBar": False},
        )

    pie_col, tbl_col = st.columns(2)
    with pie_col:
        st.markdown("**Trades by strategy**")
        pwin = st.selectbox(
            "Window", ["Last 24h", "Last 7 days", "Last 30 days", "Last 90 days"],
            index=1, key="perf_piewin",
        )
        pwin_days = {"Last 24h": 1, "Last 7 days": 7,
                     "Last 30 days": 30, "Last 90 days": 90}[pwin]
        pie_fig, total = build_strategy_pie(df, pwin_days)
        if total == 0:
            st.caption("No trades in the selected window.")
        else:
            st.plotly_chart(pie_fig, use_container_width=True,
                            config={"displayModeBar": False})
    with tbl_col:
        st.markdown(f"**Per-strategy breakdown · {ANALYTICS_LOOKBACK_DAYS}d**")
        st.dataframe(_strategy_breakdown(df), hide_index=True,
                     use_container_width=True)


# ── Overview ──────────────────────────────────────────────────────────────────

def _render_strategy_snapshot(frame: pd.DataFrame) -> None:
    """Compact per-strategy line for the Overview snapshot."""
    data, err = _fetch("/api/bot/strategies")
    strategies = (data or {}).get("strategies") or []
    if err or not strategies:
        st.caption("Strategy data unavailable.")
        return
    rows = []
    for strat in strategies:
        name = strat.get("name", "")
        sstats = strat.get("stats") or {}
        t24 = (_summary_window(_filter_strategy(frame, name), 24)["trades"]
               if not frame.empty else 0)
        rows.append({
            "Strategy": name,
            "24h": t24,
            "Trades": sstats.get("total_trades", 0),
            "Win %": sstats.get("win_rate_pct"),
            "P&L $": sstats.get("total_pnl"),
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)


def page_overview(stats: dict | None, stats_err: str | None) -> None:
    st.header("Overview")
    if stats_err:
        st.warning(f"Stats endpoint error: {stats_err}")
    s  = stats or {}
    vm = s.get("vmHealth") or {}

    # M13 S1: surface the latest analyst summary at the top of the page.
    # Silent no-op when /api/bot/insights/* isn't deployed yet OR the
    # generator hasn't written its first cache file — see
    # _render_overview_insight_card for the placeholder handling.
    _render_overview_insight_card()

    # ── Live charts (top of page) ──────────────────────────────────────────────
    # One chart per ACTIVE symbol (anything a strategy is paper/live-trading,
    # enumerated live via _discover_symbols()). Symbols with an OPEN POSITION are
    # floated to the top so what's at risk right now is seen first; the rest keep
    # config-declaration order. A single interval selector drives every chart.
    positions, _ = _fetch("/api/bot/positions")
    ov_symbols = _overview_chart_symbols(positions)

    ov_interval = st.selectbox(
        "Interval", CHART_INTERVALS,
        index=CHART_INTERVALS.index("15m") if "15m" in CHART_INTERVALS else 0,
        key="ov_interval",
    )

    # Trade-context overlays are symbol-agnostic on the wire — fetch each once
    # and let render_tv_chart filter per symbol, rather than re-fetching per chart.
    sig_data, _ = _fetch("/api/bot/signals")
    trade_data, _ = _fetch(f"/api/bot/trades/closed?limit={DEFAULT_LIMIT}")

    def _pos_caption(p: dict) -> str:
        # "SIDE qty @ entry · strategy · acct" — pattern is nullable per the
        # API contract, so fall back to "?" rather than silently dropping it.
        # Account is always shown next to the strategy for an open trade.
        side = str(p.get("side", "")).upper()
        qty = p.get("qty", "?")
        entry = p.get("entryPrice", "?")
        strat = p.get("pattern") or "?"
        acct = p.get("account") or "?"
        return f"{side} {qty} @ {entry} · {strat} · acct {acct}"

    if not ov_symbols:
        st.caption("No active symbols — the bot isn't trading any instrument.")

    # Last candle close per symbol, reused by the open-positions snapshot below
    # to mark-to-market off-chart rows (each symbol's own price, not just one).
    last_price_by_symbol: dict[str, float] = {}

    for ov_symbol in ov_symbols:
        sym_positions = [p for p in (positions or []) if p.get("symbol") == ov_symbol]
        df, candles_err = _fetch_candles(ov_symbol, ov_interval, limit=1000)
        last_price = None
        if df is not None and not df.empty:
            try:
                last_price = float(df["close"].iloc[-1])
            except (KeyError, IndexError, ValueError, TypeError):
                last_price = None
        if last_price is not None:
            last_price_by_symbol[ov_symbol] = last_price

        # Header: symbol name + an "open" badge when it carries a live position;
        # when open, the net live PnL + a per-position summary line.
        badge = " · 🟢 open" if sym_positions else ""
        st.markdown(f"#### {ov_symbol}{badge}")
        if sym_positions:
            net_pnl = sum(_position_upnl(p, last_price) for p in sym_positions)
            pc1, pc2 = st.columns([1, 3])
            pc1.metric(f"Live PnL · {ov_symbol}", fmt_usd(net_pnl),
                       delta=round(net_pnl, 2))
            pc2.caption(" · ".join(_pos_caption(p) for p in sym_positions))

        if candles_err:
            st.warning(f"{ov_symbol}: candles unavailable: {candles_err}")
        elif df is None or df.empty:
            st.caption(f"{ov_symbol}: no candle data.")
        else:
            # All overlays sent to the component; its on-canvas checkboxes
            # toggle them. Overlays are filtered to this symbol inside the embed.
            render_tv_chart(df, sig_data, trade_data, ov_symbol,
                            positions=sym_positions)
            st.caption(
                f"{ov_symbol} · {ov_interval} · candles from the bot's exchange "
                f"feed (yfinance fallback) · overlay toggles + fullscreen on the "
                f"chart · auto-refreshes every {POLL_INTERVAL_S}s"
            )

    st.divider()

    # ââ Snapshot (below the chart) ââââââââââââââââââââââââââââââââââââââââââââââ
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("24h PnL",     fmt_usd(s.get("pnl24h")))
    c2.metric("Total PnL",   fmt_usd(s.get("totalPnL")))
    c3.metric("Open trades", s.get("openTrades", 0))
    c4.metric("Win rate",    fmt_pct(s.get("winRate")))

    odf, _, _ = _analytics_frame()
    s24 = _summary_window(odf, 24)

    left, right = st.columns(2)
    with left:
        st.markdown("**Last 24h**")
        a1, a2, a3 = st.columns(3)
        a1.metric("Trades", s24["trades"])
        a2.metric("Wins",   s24["wins"])
        a3.metric("Losses", s24["losses"])
        st.markdown("**System health**")
        h1, h2, h3 = st.columns(3)
        h1.metric("CPU",    fmt_pct(vm.get("cpu")))
        h2.metric("Memory", fmt_pct(vm.get("memory")))
        h3.metric("Disk",   fmt_pct(vm.get("disk")))
    with right:
        st.markdown("**Realised P&L · 30d**")
        pnl30, _ = _fetch("/api/pnl/history?days=30")
        fig30 = build_daily_pnl_fig(pnl30 or [], height=230)
        if fig30 is not None:
            st.plotly_chart(fig30, use_container_width=True,
                            config={"displayModeBar": False})
        else:
            st.caption("No realised P&L in the last 30 days.")

    pos_col, strat_col = st.columns(2)
    with pos_col:
        st.markdown("**Open positions**")
        if positions:
            pdf = pd.DataFrame(positions)
            # Per-row uPnL via _position_upnl so broker-truth values
            # (ict-trading-bot #2953) or computed-from-mark fallbacks
            # display consistently. Each row marks to its OWN symbol's last
            # candle close (captured per chart above); rows whose symbol had
            # no candle data fall through to the broker value, else $0.
            pdf["uPnL"] = [
                _position_upnl(p, last_price_by_symbol.get(p.get("symbol")))
                for p in positions
            ]
            cmap = {"symbol": "Symbol", "side": "Side", "qty": "Qty",
                    "entryPrice": "Entry", "uPnL": "uPnL",
                    "pattern": "Strategy", "account": "Account"}
            cols = [c for c in cmap if c in pdf.columns]
            st.dataframe(pdf[cols].rename(columns=cmap), hide_index=True,
                         use_container_width=True)
        else:
            st.caption("No open positions.")
    with strat_col:
        st.markdown("**Strategies · 24h**")
        _render_strategy_snapshot(odf)


# ── Chart interval choices (shared by the Overview chart) ──────────────────────
# Symbols are NOT listed here — both the Overview selector and the
# Performance per-symbol tabs enumerate them live via _discover_symbols().

CHART_INTERVALS = list(_YF_PARAMS.keys())




# ── Performance Overview (per-symbol live trade context) ──────────────────────────
#
# One tab per traded symbol (from _discover_symbols()). Each renders the live
# price chart for that symbol with TradingView-style trade context overlaid:
#   * strategy signal entry markers          (/api/bot/signals, symbol-filtered)
#   * live/open trade entry + TP + SL lines  (/api/bot/positions, symbol-filtered)
#   * live PnL for the open position(s)       (Position.unrealizedPnl)
#   * recent closed-trade entry/exit markers  (/api/bot/trades/closed)
# Candles: bot exchange feed first, Yahoo Finance fallback (_yf_ticker map).

PERF_INTERVALS = ["5m", "15m", "1h", "4h", "1d"]


def _positions_for_symbol(symbol: str) -> tuple[list[dict], str | None]:
    rows, err = _fetch("/api/bot/positions")
    if err:
        return [], err
    return [p for p in (rows or []) if str(p.get("symbol")) == symbol], None


def _render_open_trade_header(
    symbol: str, positions: list[dict], last_price: float | None,
) -> None:
    if not positions:
        st.info(
            f"No open {symbol} position right now — the chart below still shows "
            "strategy signals and recent closed-trade context."
        )
        return
    # Broker-truth uPnL when /api/bot/positions tagged the source
    # (ict-trading-bot #2953); computed-from-mark fallback otherwise.
    net_pnl = sum(_position_upnl(p, last_price) for p in positions)
    p = positions[0]  # primary leg for the detail metrics
    side = str(p.get("side", "")).upper() or "—"
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Open legs", len(positions))
    c2.metric(
        "Live PnL", fmt_usd(net_pnl),
        delta=round(net_pnl, 2) if net_pnl else None,
    )
    c3.metric("Side · Qty", f"{side} · {p.get('qty', '—')}")
    c4.metric("Entry", fmt_num(p.get("entryPrice")))
    c5.metric("SL · TP", f"{fmt_num(p.get('stopLoss'))} · {fmt_num(p.get('takeProfit'))}")
    pat = p.get("pattern")
    acct = p.get("account")
    if pat or acct:
        st.caption(
            f"Active strategy on primary leg: **{pat or '?'}** · "
            f"account **{acct or '?'}**"
        )


def _add_signal_markers(fig: go.Figure, symbol: str, last_price: float) -> None:
    signals, sig_err = _fetch("/api/bot/signals")
    if sig_err or not signals:
        return
    sdf = pd.DataFrame(signals)
    if "symbol" in sdf.columns:
        sdf = sdf[sdf["symbol"] == symbol]
    if sdf.empty or "timestamp" not in sdf.columns:
        return
    sdf = sdf.copy()
    sdf["timestamp"] = pd.to_datetime(sdf["timestamp"], errors="coerce", utc=True)
    sdf["timestamp"] = sdf["timestamp"].dt.tz_localize(None)
    sdf = sdf.dropna(subset=["timestamp"])
    for side_val, marker_sym, color, label in [
        ("buy",  "triangle-up",   _TV_GREEN, "Long signal"),
        ("sell", "triangle-down", _TV_RED,   "Short signal"),
    ]:
        sub = sdf[sdf["side"] == side_val] if "side" in sdf.columns else pd.DataFrame()
        if sub.empty:
            continue
        prices = (
            sub["price"].fillna(last_price)
            if "price" in sub.columns else pd.Series([last_price] * len(sub))
        )
        hover = (
            sub["pattern"].fillna("").astype(str)
            if "pattern" in sub.columns else pd.Series([""] * len(sub))
        )
        fig.add_trace(go.Scatter(
            x=sub["timestamp"], y=prices, mode="markers", name=label, text=hover,
            marker=dict(symbol=marker_sym, size=13, color=color,
                        line=dict(width=1, color="white")),
            hovertemplate=f"{label} %{{text}}: %{{y:.4g}}<extra></extra>",
        ))


def _add_closed_trade_markers(fig: go.Figure, symbol: str) -> None:
    trades, tr_err = _fetch(f"/api/bot/trades/closed?limit={DEFAULT_LIMIT}")
    if tr_err or not trades:
        return
    tdf = pd.DataFrame(trades)
    if "symbol" in tdf.columns:
        tdf = tdf[tdf["symbol"] == symbol]
    if tdf.empty:
        return
    pnl_col = "realizedPnl" if "realizedPnl" in tdf.columns else None
    if "openedAt" in tdf.columns and "entryPrice" in tdf.columns:
        sub = tdf.copy()
        sub["openedAt"] = pd.to_datetime(sub["openedAt"], errors="coerce", utc=True).dt.tz_localize(None)
        sub = sub.dropna(subset=["openedAt", "entryPrice"])
        if not sub.empty:
            fig.add_trace(go.Scatter(
                x=sub["openedAt"], y=sub["entryPrice"], mode="markers", name="Trade entry",
                marker=dict(symbol="circle", size=8, color=_TV_ENTRY,
                            line=dict(width=1, color="white")),
                hovertemplate="Entry: %{y:.4g}<extra></extra>",
            ))
    if "closedAt" in tdf.columns and "exitPrice" in tdf.columns:
        sub = tdf.copy()
        sub["closedAt"] = pd.to_datetime(sub["closedAt"], errors="coerce", utc=True).dt.tz_localize(None)
        sub = sub.dropna(subset=["closedAt", "exitPrice"])
        if not sub.empty:
            # realizedPnl is nullable (ict-trading-bot #2759) — paint an
            # unmeasured close neutral grey, not a fabricated red loss.
            def _exit_color(r: dict) -> str:
                raw = r.get(pnl_col) if pnl_col else None
                try:
                    pnl = None if raw is None or pd.isna(raw) else float(raw)
                except (TypeError, ValueError):
                    pnl = None
                if pnl is None:
                    return _TV_TEXT
                return _TV_GREEN if pnl > 0 else _TV_RED
            colors = [_exit_color(r) for _, r in sub.iterrows()]
            fig.add_trace(go.Scatter(
                x=sub["closedAt"], y=sub["exitPrice"], mode="markers", name="Trade exit",
                marker=dict(symbol="x", size=9, color=colors, line=dict(width=2)),
                hovertemplate="Exit: %{y:.4g}<extra></extra>",
            ))


def _add_open_trade_lines(fig: go.Figure, positions: list[dict]) -> None:
    """Draw entry / TP / SL price-lines for each open position leg."""
    for p in positions:
        entry = p.get("entryPrice")
        tp    = p.get("takeProfit")
        sl    = p.get("stopLoss")
        side  = str(p.get("side", "")).upper()
        if entry is not None:
            fig.add_hline(
                y=float(entry), line_dash="solid", line_width=1.5, line_color=_TV_ENTRY,
                annotation_text=f"Entry {fmt_num(entry)} ({side})",
                annotation_position="top left",
                annotation_font_color=_TV_ENTRY,
            )
        if tp is not None:
            fig.add_hline(
                y=float(tp), line_dash="dash", line_width=1.5, line_color=_TV_GREEN,
                annotation_text=f"TP {fmt_num(tp)}",
                annotation_position="top left",
                annotation_font_color=_TV_GREEN,
            )
        if sl is not None:
            fig.add_hline(
                y=float(sl), line_dash="dash", line_width=1.5, line_color=_TV_RED,
                annotation_text=f"SL {fmt_num(sl)}",
                annotation_position="bottom left",
                annotation_font_color=_TV_RED,
            )


def render_performance_tab(symbol: str) -> None:
    cc1, cc2, cc3 = st.columns([2, 1, 1])
    with cc1:
        interval = st.selectbox(
            "Interval", PERF_INTERVALS, index=1, key=f"perf_int_{symbol}"
        )
    with cc2:
        show_signals = st.toggle("Signals", value=True, key=f"perf_sig_{symbol}")
    with cc3:
        show_trades = st.toggle("Closed trades", value=True, key=f"perf_tr_{symbol}")

    positions, pos_err = _positions_for_symbol(symbol)
    if pos_err:
        st.warning(f"Positions unavailable: {pos_err}")

    df, candles_err = _fetch_candles(symbol, interval)
    if candles_err:
        st.warning(f"Candles unavailable: {candles_err}")
        return
    if df is None or df.empty:
        st.caption("No candle data.")
        return

    last_price = float(df["close"].iloc[-1])
    # last_price ready — header can now fall back to computed PnL when
    # the broker-truth value is "unavailable".
    _render_open_trade_header(symbol, positions, last_price)

    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=df["timestamp"],
        open=df["open"], high=df["high"], low=df["low"], close=df["close"],
        name=symbol,
        increasing=dict(line=dict(color=_TV_GREEN, width=1), fillcolor=_TV_GREEN),
        decreasing=dict(line=dict(color=_TV_RED, width=1), fillcolor=_TV_RED),
    ))

    if show_signals:
        _add_signal_markers(fig, symbol, last_price)
    if show_trades:
        _add_closed_trade_markers(fig, symbol)
    # Live/open trade context (entry + TP + SL) always overlaid when present.
    _add_open_trade_lines(fig, positions)

    _axis = dict(
        gridcolor=_TV_GRID, gridwidth=1, color=_TV_TEXT,
        tickfont=dict(color=_TV_TEXT, size=10),
        linecolor=_TV_GRID, zerolinecolor=_TV_GRID,
        showspikes=True, spikemode="across", spikesnap="cursor",
        spikecolor=_TV_TEXT, spikethickness=1, spikedash="dot",
    )
    fig.update_layout(
        template="plotly_dark",
        plot_bgcolor=_TV_BG, paper_bgcolor=_TV_BG,
        hovermode="x unified", height=620,
        margin=dict(l=0, r=70, t=10, b=0),
        dragmode="pan", xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", y=1.02, x=0,
                    font=dict(size=11, color=_TV_TEXT), bgcolor="rgba(0,0,0,0)"),
        font=dict(color=_TV_TEXT, size=11),
        hoverlabel=dict(bgcolor="#1e2634", bordercolor=_TV_GRID,
                        font=dict(color=_TV_TEXT, size=12)),
    )
    fig.update_xaxes(**_axis)
    fig.update_yaxes(**_axis, side="right")

    st.plotly_chart(
        fig, use_container_width=True, config=_CHART_CONFIG,
        key=f"perf_chart_{symbol}",
    )
    st.caption(
        f"{symbol} · {interval} · candles from the bot's exchange feed "
        f"(yfinance fallback) · signals + open-trade entry/TP/SL + live PnL · "
        f"auto-refreshes every {POLL_INTERVAL_S}s"
    )


def page_performance() -> None:
    st.header("Performance")
    st.caption(
        "Detailed system + per-strategy performance, plus per-symbol trade "
        "context. Filter by strategy and time window below."
    )
    render_trade_analytics()

    st.divider()
    st.subheader("Trade context · per symbol")
    st.caption(
        "Signals, open-trade entry/TP/SL and closed-trade markers on price — "
        "recent (~24h) context. Refreshes each cycle (not tick-live)."
    )
    perf_symbols = _discover_symbols()
    for tab, sym in zip(st.tabs(perf_symbols), perf_symbols):
        with tab:
            render_performance_tab(sym)


# ── Accounts ────────────────────────────────────────────────────────────────────

def page_accounts() -> None:
    st.header("Accounts")
    st.caption(
        "Every configured account — live/dry status, balance, PnL, and a "
        "recent-trades log. All values are read live from the bot; nothing here "
        "is hardcoded."
    )

    cfg, cfg_err = _fetch("/api/bot/config")
    if cfg_err:
        st.warning(f"Config endpoint error: {cfg_err}")
        return
    cfg = cfg or {}
    accounts = cfg.get("accounts") or []
    trading_mode = cfg.get("trading_mode") or {}
    live_map = trading_mode.get("live_per_account") or {}
    if trading_mode.get("halted"):
        st.error("⛔ Trading halted — a halt flag is present on the VM.")
    if not accounts:
        st.info("No accounts configured.")
        return

    bal_env, _ = _fetch("/api/bot/accounts/balances")
    bal_env = bal_env or {}
    balances = bal_env.get("balances") or {}
    if bal_env.get("as_of"):
        st.caption(f"Balances tracked by the bot · snapshot as of {bal_env['as_of']}")

    positions, _ = _fetch("/api/bot/positions")
    positions = positions or []

    since_7d = (dt.datetime.utcnow() - dt.timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")

    for acc in accounts:
        aid       = acc.get("id", "?")
        is_live   = bool(live_map.get(aid, False))
        exchange  = acc.get("exchange", "—")
        market    = acc.get("market_type", "—")
        strategies = acc.get("strategies") or []

        bal_val = (balances.get(aid) or {}).get("balance")
        acc_positions = [p for p in positions if p.get("account") == aid]
        # Broker-truth uPnL when /api/bot/positions tagged the source
        # (ict-trading-bot #2953). last_price=None here means the
        # client-side computed fallback returns 0 for any position
        # whose broker value is "unavailable" — acceptable for the
        # account-level summary; the per-symbol Performance header has
        # the candle context for a richer fallback.
        unrealized = sum(_position_upnl(p, None) for p in acc_positions)

        # 30-day realised-PnL history via the no-session, account-filtered
        # endpoint. Rows are `{date, pnl, trades}` — `pnl`, not `realizedPnl`
        # (renamed in S-063; the old key silently summed to zero).
        realized = None
        trades_30d = 0
        ph, _ = _fetch(f"/api/pnl/history?days=30&account_id={aid}")
        ph = ph or []
        if ph:
            try:
                realized = sum(float(r.get("pnl") or 0) for r in ph)
                trades_30d = sum(int(r.get("trades") or 0) for r in ph)
            except (TypeError, ValueError):
                realized = None

        dot = _row_dot("live" if is_live else "dry")
        label = (f"{dot}  **{aid}**  ·  {'LIVE' if is_live else 'DRY'}  ·  "
                 f"30d {fmt_usd(realized)}  ·  {len(acc_positions)} open")
        with st.expander(label):
            st.caption(
                f"{exchange} · {market} · "
                f"strategies: {', '.join(strategies) if strategies else '— (none assigned)'}"
            )
            m1, m2, m3, m4, m5 = st.columns(5)
            m1.metric("Balance",        fmt_usd(bal_val) if bal_val is not None else "—")
            m2.metric("Realized · 30d", fmt_usd(realized))
            m3.metric("Unrealized",     fmt_usd(unrealized) if acc_positions else "—")
            m4.metric("Open trades",    len(acc_positions))
            m5.metric("Trades · 30d",   trades_30d)

            fig = build_daily_pnl_fig(ph, height=220)
            if fig is not None:
                st.plotly_chart(fig, use_container_width=True,
                                config={"displayModeBar": False})
            else:
                st.caption("No realised P&L in the last 30 days.")

            st.markdown("**Recent trades · 7d**")
            trades, terr = _fetch(
                f"/api/bot/trades/closed?limit=100&account_id={aid}&since={since_7d}"
            )
            if terr:
                st.warning(terr)
            elif not trades:
                st.caption("No closed trades in the last 7 days.")
            else:
                tdf = _format_closed_trades_df(pd.DataFrame(trades))
                col_map = {
                    "symbol": "Symbol", "side": "Side", "pattern": "Strategy",
                    "entryPrice": "Entry", "exitPrice": "Exit",
                    "realizedPnl": "PnL", "realizedPnlPct": "PnL %",
                    "closeReason": "Close", "openedAt": "Opened", "closedAt": "Closed",
                }
                cols = [c for c in col_map if c in tdf.columns]
                disp = tdf[cols].rename(columns=col_map) if cols else tdf
                _capped_table(disp, key=f"acc_log_all_{aid}")


# ── Positions ───────────────────────────────────────────────────────────────────

_CLOSED_WINDOWS = {"Last 24h": 1, "Last 7 days": 7, "Last 30 days": 30}


def page_positions() -> None:
    st.header("Positions")
    st.caption("Live open positions on top; the closed-position history below. "
               "Use the segment picker to switch between live and demo.")

    segment = _segment_picker("pos_segment")

    # Join data for the trade cards — all fast journal/DB pulls now that the
    # per-model ML scores are persisted ON the order package (modelScores),
    # so there's no slow shadow-log recompile. order-packages carries the
    # reasoning AND the model scores; signals adds the triggering-signal
    # correlation. Fetched concurrently, time-boxed.
    _op_path = "/api/bot/order-packages?" + urlencode({"limit": 50, "include_demo": "true"})
    _sig_path = "/api/bot/signals"
    _joins = _fetch_parallel([_op_path, _sig_path], timeout=6.0)
    op_map = _order_package_map(_joins.get(_op_path, (None, None))[0])
    signals = _joins.get(_sig_path, (None, None))[0] or []

    st.subheader("Open")
    rows, err = _fetch("/api/bot/positions?include_demo=true")
    if err:
        st.warning(err)
    else:
        rows = _segment_filter_rows(rows or [], segment)
        if not rows:
            st.caption(f"No open {segment if segment != 'all' else ''} positions.".strip())
        else:
            # One detail card per open position. uPnL uses the broker-truth
            # value the bot already provides (Position.unrealizedPnl); we
            # deliberately do NOT fetch candles here — per-symbol candle pulls
            # (especially MES→IBKR through the bot) made the page slow to load.
            for p in rows:
                _render_trade_card(
                    p, is_open=True, op_map=op_map,
                    signals=signals, last_price=None,
                )

    st.subheader("Closed positions")
    wlabel = st.selectbox("History window", list(_CLOSED_WINDOWS), index=1,
                          key="pos_closed_win")
    days = _CLOSED_WINDOWS[wlabel]
    since = (dt.datetime.utcnow() - dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    closed, cerr = _fetch(
        "/api/bot/trades/closed?" + urlencode({
            "limit": ANALYTICS_MAX_ROWS, "since": since, "include_demo": "true",
        })
    )
    closed = _segment_filter_rows(closed or [], segment)
    if cerr:
        st.warning(cerr)
    elif not closed:
        st.caption(f"No trades closed in the {wlabel.lower()}.")
    else:
        # _format_closed_trades_df preserves row order, so the dataframe's
        # selection index maps 1:1 back to `closed` → click a row for its card.
        cdf = _format_closed_trades_df(pd.DataFrame(closed))
        col_map = {
            "closedAt": "Closed", "openedAt": "Opened", "account": "Account",
            "symbol": "Symbol", "side": "Side", "pattern": "Strategy",
            "qty": "Qty", "entryPrice": "Entry", "exitPrice": "Exit",
            "realizedPnl": "PnL", "realizedPnlPct": "PnL %", "closeReason": "Close",
        }
        cols = [c for c in col_map if c in cdf.columns]
        disp = cdf[cols].rename(columns=col_map) if cols else cdf
        sel_idx: int | None = None
        if _df_row_selection_supported():
            st.caption(f"{len(closed)} closed trade(s) · {wlabel.lower()}"
                       + (f" · capped at {ANALYTICS_MAX_ROWS}" if len(closed) >= ANALYTICS_MAX_ROWS else "")
                       + " · click a row for the full trade card")
            event = st.dataframe(
                disp, hide_index=True, use_container_width=True,
                on_select="rerun", selection_mode="single-row", key="pos_closed_df",
            )
            try:
                rows_sel = event.selection.rows  # type: ignore[union-attr]
            except AttributeError:
                rows_sel = []
            if rows_sel:
                sel_idx = rows_sel[0]
        else:
            # Older Streamlit without dataframe row-selection — render the
            # table plus a selectbox so the full card is still reachable.
            st.caption(f"{len(closed)} closed trade(s) · {wlabel.lower()}"
                       + (f" · capped at {ANALYTICS_MAX_ROWS}" if len(closed) >= ANALYTICS_MAX_ROWS else "")
                       + " · pick a trade below for the full card")
            st.dataframe(disp, hide_index=True, use_container_width=True)
            pick = st.selectbox(
                "Open full card for…", [None, *range(len(closed))],
                format_func=lambda i: "—" if i is None else (
                    f"{closed[i].get('symbol')} "
                    f"{str(closed[i].get('side', '')).upper()} · "
                    f"{closed[i].get('closedAt') or ''}"
                ),
                key="pos_closed_pick",
            )
            sel_idx = pick
        if sel_idx is not None and 0 <= sel_idx < len(closed):
            st.markdown("#### Selected trade")
            _render_trade_card(
                closed[sel_idx], is_open=False, op_map=op_map, signals=signals,
            )


# ── Signals ────────────────────────────────────────────────────────────────────

def page_signals() -> None:
    st.header("Signals")
    rows, err = _fetch("/api/bot/signals")
    if err:
        st.warning(err)
        return
    if not rows:
        st.caption("No recent signals.")
        return
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)


# ── Order Packages ─────────────────────────────────────────────────────────────────

def _short_model(model_id: str | None) -> str:
    """`btc-regime-5m-baseline-v1` → `btc-regime-5m` for compact display."""
    if not model_id:
        return "?"
    i = model_id.find("-baseline")
    return model_id[:i] if i > 0 else model_id


def _trade_score_map() -> dict[str, str]:
    """trade_id → compact per-model shadow-score string, from /api/bot/trades/scores."""
    payload, _ = _fetch("/api/bot/trades/scores?limit=200&include_open=true")
    out: dict[str, str] = {}
    for t in (payload or {}).get("trades", []):
        parts = []
        for sc in t.get("scores", []):
            v = sc.get("score_last")
            if v is None:
                v = sc.get("score_mean")
            if v is None:
                continue
            try:
                parts.append(f"{_short_model(sc.get('model_id'))}={float(v):.2f}")
            except (TypeError, ValueError):
                continue
        if parts:
            out[str(t.get("trade_id"))] = " · ".join(sorted(parts))
    return out


def _claude_cell(cs: dict | None) -> str:
    if not cs:
        return "—"
    grade, score = cs.get("grade"), cs.get("score")
    if grade is None and score is None:
        return "—"
    txt = str(grade) if grade is not None else ""
    if isinstance(score, (int, float)):
        txt = f"{txt} ({score:.2f})".strip()
    return txt or "—"


# ── Trade detail card (shared by open + closed trades) ─────────────────────────
#
# A single rich card per trade, joining everything the public API can supply for
# one trade id:
#   * /api/bot/positions (open) or /api/bot/trades/closed (closed) — the leg
#   * /api/bot/order-packages   — the decision (confidence, status, reasoning:
#                                  signalLogic + meta{setup_type,killzone,bias},
#                                  Claude review) joined by linkedTradeId == id
#   * /api/bot/trades/scores    — the shadow MODELS scored on the trade, by
#                                  trade_id == id
#   * /api/bot/signals          — the triggering signal, best-effort correlated
#                                  by symbol+strategy+time (no id-level link
#                                  exists on the public surface)
# Account is always shown next to the strategy. SL/TP carry an "set at entry"
# note because the bot doesn't trail/modify them post-open (no modification
# history exists anywhere — verified, so we don't fabricate a "last update").


def _df_row_selection_supported() -> bool:
    """True when this Streamlit build supports ``st.dataframe(on_select=…)``
    (added 1.35). Streamlit Community Cloud may run an older build than the
    pin requests during a rollout window, and calling the kwarg there raises —
    so feature-detect and fall back to a selectbox instead of crashing the page.
    """
    import inspect
    try:
        return "on_select" in inspect.signature(st.dataframe).parameters
    except (TypeError, ValueError):
        return False


def _order_package_map(payload: Any) -> dict[str, dict]:
    """linkedTradeId → its order package (newest wins). Pure builder over an
    already-fetched /api/bot/order-packages payload."""
    out: dict[str, dict] = {}
    for p in (payload or {}).get("rows", []):
        ltid = p.get("linkedTradeId")
        if ltid is not None:
            out.setdefault(str(ltid), p)  # rows are newest-first → first wins
    return out


def _correlated_signal(
    signals: list[dict] | None, symbol: str, strategy: str | None, opened_at: Any,
) -> dict | None:
    """Best-effort triggering signal for a trade. No id ties a signal to a
    position/order-package on the public surface, so this matches by symbol
    (+ strategy when both sides name one) and picks the signal nearest the
    open time, preferring one at/just-before the open."""
    if not signals:
        return None
    cands = []
    for s in signals:
        if s.get("symbol") != symbol:
            continue
        if strategy and s.get("strategy") and s.get("strategy") != strategy:
            continue
        cands.append(s)
    if not cands:
        return None
    t0 = _parse_trade_ts(opened_at)
    if t0 is None:
        return cands[0]

    def _key(s: dict) -> tuple[int, float]:
        ts = _parse_trade_ts(s.get("timestamp"))
        if ts is None:
            return (2, 0.0)
        delta = (t0 - ts).total_seconds()
        # bucket 0: at/just-before open (within 5 min after counts too), nearest first
        return (0, abs(delta)) if delta >= -300 else (1, abs(delta))

    return sorted(cands, key=_key)[0]


def _trade_geometry(
    entry: Any, sl: Any, tp: Any
) -> tuple[float | None, float | None, float | None]:
    """(risk:reward, stop-distance %, target-distance %) from the trade's
    levels — all None-safe. Distances are absolute % moves from entry, so a
    user can size up the trade without doing the arithmetic."""
    try:
        e = float(entry)
    except (TypeError, ValueError):
        return None, None, None
    if not e:
        return None, None, None
    risk = reward = None
    try:
        if sl is not None:
            risk = abs(e - float(sl))
    except (TypeError, ValueError):
        risk = None
    try:
        if tp is not None:
            reward = abs(float(tp) - e)
    except (TypeError, ValueError):
        reward = None
    rr = (reward / risk) if (risk and reward and risk > 0) else None
    risk_pct = (risk / e * 100.0) if risk is not None else None
    reward_pct = (reward / e * 100.0) if reward is not None else None
    return rr, risk_pct, reward_pct


def _signal_logic_text(sl: Any) -> str | None:
    """Human-readable one-liner from an order package's ``signalLogic`` —
    handles the plain-string and structured-dict shapes the writer may use."""
    if sl is None:
        return None
    if isinstance(sl, str):
        return sl.strip() or None
    if isinstance(sl, dict):
        for k in ("reason", "logic", "summary", "note", "explanation"):
            v = sl.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        flat = ", ".join(
            f"{k}={v}" for k, v in sl.items()
            if not isinstance(v, (dict, list))
        )
        return flat[:300] or None
    return None


def _render_trade_card(
    trade: dict,
    *,
    is_open: bool,
    op_map: dict[str, dict],
    signals: list[dict] | None,
    last_price: float | None = None,
) -> None:
    """Render one trade as a bordered, scannable detail card (open or closed).

    Model scores come straight off the linked order package's ``modelScores``
    (persisted at decision time — a cheap read), not a per-request recompile.
    """
    sym = trade.get("symbol", "?")
    side_raw = str(trade.get("side", "")).lower()
    if side_raw in ("buy", "long"):
        side_lbl, side_dot = "LONG", "🟢"
    elif side_raw in ("sell", "short"):
        side_lbl, side_dot = "SHORT", "🔴"
    else:
        side_lbl, side_dot = (side_raw.upper() or "—"), "⚪"
    strat = trade.get("pattern") or "?"
    account = trade.get("account") or "?"
    tid = str(trade["id"]) if trade.get("id") is not None else None
    op = op_map.get(tid) if tid else None
    # Per-model ML scores persisted on the order package at decision time:
    # {model_id: {stage, score}}. Cheap read — no shadow-log recompile.
    model_scores = op.get("modelScores") if isinstance(op, dict) else None

    entry, sl_lvl, tp_lvl = trade.get("entryPrice"), trade.get("stopLoss"), trade.get("takeProfit")
    rr, risk_pct, reward_pct = _trade_geometry(entry, sl_lvl, tp_lvl)

    with st.container(border=True):
        # ── Header: symbol + side, PnL on the right ────────────────────
        demo = " · 🧪 demo" if trade.get("isDemo") else ""
        h1, h2 = st.columns([3, 1])
        h1.markdown(f"### {side_dot} {sym} · {side_lbl}")
        if is_open:
            upnl = _position_upnl(trade, last_price)
            h2.metric("Unrealized PnL", fmt_usd(upnl),
                      delta=round(upnl, 2) if upnl else None)
        else:
            rp = trade.get("realizedPnl")
            h2.metric("Realized PnL", fmt_usd(rp) if rp is not None else "—")
        st.caption(
            f"strategy **{strat}** · account **{account}** · "
            + ("🟢 open" if is_open else "⚪ closed")
            + (f" · pkg {op['status']}" if op and op.get("status") else "")
            + demo
        )

        # ── Levels ─────────────────────────────────────────────────────
        lv = st.columns(4)
        lv[0].metric("Entry", fmt_num(entry))
        if is_open:
            lv[1].metric("Stop loss", fmt_num(sl_lvl))
            lv[2].metric("Take profit", fmt_num(tp_lvl))
        else:
            lv[1].metric("Exit", fmt_num(trade.get("exitPrice")))
            lv[2].metric("Stop / TP", f"{fmt_num(sl_lvl)} / {fmt_num(tp_lvl)}")
        lv[3].metric("Qty", fmt_num(trade.get("qty")))

        # ── Evaluation row — R:R, distances, confidence/PnL% ───────────
        ev = st.columns(4)
        ev[0].metric("Risk : Reward", f"1 : {rr:.2f}" if rr else "—")
        ev[1].metric("Stop dist", f"{risk_pct:.2f}%" if risk_pct is not None else "—")
        ev[2].metric("Target dist", f"{reward_pct:.2f}%" if reward_pct is not None else "—")
        if is_open:
            conf = op.get("confidence") if op else None
            ev[3].metric("Confidence", f"{conf:.2f}" if isinstance(conf, (int, float)) else "—")
        else:
            ev[3].metric("PnL %", fmt_pct(trade.get("realizedPnlPct")))

        if is_open:
            st.caption(
                f"opened {trade.get('openedAt') or '—'} · SL/TP set at entry "
                "(not trailed or modified post-open)"
            )
        else:
            st.caption(
                f"opened {trade.get('openedAt') or '—'} · closed "
                f"{trade.get('closedAt') or '—'} · close reason: "
                f"**{trade.get('closeReason') or '—'}**"
            )

        st.divider()

        # ── Decision & reasoning (fast pull from order_packages) ───────
        st.markdown("**🧠 Decision & reasoning**")
        if op:
            meta = op.get("meta") if isinstance(op.get("meta"), dict) else {}
            chips = []
            for label, key in (("Setup", "setup_type"), ("Killzone", "killzone"),
                               ("Bias", "bias"), ("Session", "session")):
                v = meta.get(key)
                if v:
                    chips.append(f"**{label}:** {v}")
            if chips:
                st.markdown(" &nbsp;·&nbsp; ".join(chips))
            logic = _signal_logic_text(op.get("signalLogic"))
            if logic:
                st.markdown(f"> {logic}")
            claude = op.get("claudeScore") or {}
            if claude.get("grade") or claude.get("rationale"):
                grade = _claude_cell(claude)
                rat = claude.get("rationale") or ""
                st.markdown(f"**Claude review — {grade}** · {rat}" if rat
                            else f"**Claude review — {grade}**")
            if not chips and not logic and not (claude.get("grade") or claude.get("rationale")):
                st.caption("No reasoning recorded for this decision.")
        else:
            st.caption("No linked order package found for this trade.")

        # ── Models scored (persisted on the order package — cheap read) ─
        st.markdown("**🤖 Models scored**")
        if isinstance(model_scores, dict) and model_scores:
            mdf = pd.DataFrame([{
                "Model": _short_model(mid),
                "Stage": (sc or {}).get("stage") or "—",
                "Score": (sc or {}).get("score"),
            } for mid, sc in model_scores.items()])
            st.dataframe(mdf, hide_index=True, use_container_width=True)
        else:
            st.caption("No model scores recorded for this trade.")

        # ── Triggering signal (best-effort correlation) ───────────────
        sig = _correlated_signal(signals, sym, trade.get("pattern"),
                                 trade.get("openedAt"))
        if sig:
            sbits = []
            if sig.get("pattern"):
                sbits.append(f"**{sig['pattern']}**")
            if sig.get("confidence") is not None:
                sbits.append(f"conf {sig['confidence']}")
            if sig.get("price") is not None:
                sbits.append(f"@ {fmt_num(sig['price'])}")
            if sig.get("timestamp"):
                sbits.append(str(sig["timestamp"]))
            zones = sig.get("zones") or []
            zbits = []
            for z in zones:
                kind = z.get("kind")
                if kind == "fvg":
                    zbits.append(f"FVG {fmt_num(z.get('low'))}–{fmt_num(z.get('high'))}")
                elif kind == "sweep":
                    zbits.append(f"sweep {fmt_num(z.get('price'))}")
                elif kind:
                    zbits.append(str(kind))
            line = "**📡 Triggering signal:** " + " · ".join(sbits)
            if zbits:
                line += "  ·  zones: " + " · ".join(zbits)
            st.caption(line + "  _(matched by symbol+strategy+time)_")

        # ── Raw drill-down ─────────────────────────────────────────────
        with st.expander("Raw order package"):
            st.json(op or {"note": "no linked order package"})


def page_order_packages() -> None:
    st.header("Order Packages")
    st.caption(
        "Each row is an order package — the bot's actual decision (which "
        "strategy proposed what), with the shadow-model scores and the Claude "
        "decision grade. The decision level, not the fill level."
    )

    segment = _segment_picker("op_segment")
    payload, err = _fetch(
        "/api/bot/order-packages?" + urlencode({
            "limit": ANALYTICS_MAX_ROWS, "include_demo": "true",
        })
    )
    if err:
        st.info(
            f"Order-packages endpoint unavailable ({err}). This tab needs the "
            "bot's `/api/bot/order-packages` route — pending a VM pull-and-deploy."
        )
        return
    packages = (payload or {}).get("rows", [])
    packages = _segment_filter_rows(packages, segment)
    if not packages:
        if segment == "live":
            st.caption("No live-money order packages recorded yet.")
        elif segment == "demo":
            st.caption("No demo order packages recorded yet.")
        else:
            st.caption("No order packages recorded yet.")
        return

    score_map = _trade_score_map()

    strategies = sorted({p.get("strategy") for p in packages if p.get("strategy")})
    choice = st.radio("Strategy", ["All"] + strategies, horizontal=True,
                      key="op_strat")
    if choice != "All":
        packages = [p for p in packages if p.get("strategy") == choice]

    rows = []
    for p in packages:
        rows.append({
            "Created": p.get("createdAt"),
            "Strategy": p.get("strategy"),
            "Symbol": p.get("symbol"),
            "Dir": p.get("direction"),
            "Entry": p.get("entry"),
            "SL": p.get("sl"),
            "TP": p.get("tp"),
            "Status": p.get("status"),
            "PnL": p.get("pnl"),
            "Model scores": score_map.get(str(p.get("linkedTradeId")), "—"),
            "Claude": _claude_cell(p.get("claudeScore")),
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
    if not (payload or {}).get("claude_log_present"):
        st.caption(
            "Claude decision scores populate as `/health-review` runs score each "
            "package — the column shows — until then."
        )


# ── Models & Training ──────────────────────────────────────────────────────────────

_STAGE_ICON = {
    "live_approved": "\U0001f7e2", "limited_live": "\U0001f7e1", "shadow": "\U0001f535",
    "backtest_approved": "\U0001f7e4", "candidate": "⚪", "research_only": "⚫",
}

# Operator's 3-bucket deployment view (2026-05-18; default-flip update
# 2026-05-19). Collapses the 7 registry stages into "is this model
# influencing real money, just observing, or parked?":
#   LIVE    — predictions influence trade decisions on live accounts
#             (stages: advisory / limited_live / live_approved).
#   SHADOW  — predictions logged in real time but decisions unchanged.
#             SHADOW is the default for any freshly-trained model since
#             the 2026-05-19 default flip; the lifecycle is
#             register-into-shadow → backtest gate → promote to LIVE.
#   OFFLINE — operator-parked: stages research_only / candidate /
#             backtest_approved. Reached only by explicit demotion
#             from shadow; not a default state for new models.
#
# Source of truth: the bot's /api/bot/ml/registry endpoint returns
# ``deployment_bucket`` per row (PR #1391). The dashboard prefers that
# field but falls back to a legacy stage→bucket mapping when the bot
# API hasn't been upgraded yet — this keeps the dashboard rendering
# correctly during a rollout window.
_BUCKET_PILL = {
    "LIVE":    "🟢 LIVE",
    "SHADOW":  "🔵 SHADOW",
    "OFFLINE": "⚫ OFFLINE",
}
_BUCKET_LEGEND = (
    "🟢 LIVE = influencing trade decisions · "
    "🔵 SHADOW = predictions logged real-time, decisions unchanged "
    "(default for fresh models) · "
    "⚫ OFFLINE = operator-parked, not in the shadow channel."
)


def _normalize_bucket(row: dict) -> str:
    """Resolve the deployment bucket for a registry row.

    Prefer the bot's `deployment_bucket` field (added in PR #1391).
    Fall back to a legacy stage→bucket map for backward compat while
    the new bot API rolls out.
    """
    bucket = row.get("deployment_bucket")
    if bucket in _BUCKET_PILL:
        return bucket
    stage = row.get("target_deployment_stage") or row.get("stage") or ""
    if stage in ("live_approved", "limited_live", "advisory"):
        return "LIVE"
    if stage == "shadow":
        return "SHADOW"
    return "OFFLINE"


def _format_pill(bucket: str) -> str:
    return _BUCKET_PILL.get(bucket, "❔ UNKNOWN")


def _fmt_age(seconds: float | int | None) -> str:
    if seconds is None:
        return "—"
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m {s % 60}s"
    if s < 86400:
        return f"{s // 3600}h {(s % 3600) // 60}m"
    return f"{s // 86400}d {(s % 86400) // 3600}h"


def _trainer_status_banner(payload: dict) -> None:
    """Top-of-page banner summarizing trainer VM state.

    The trainer runs on a once-a-day systemd timer (``ict-trainer.timer``);
    between cycles the oneshot ``ict-trainer.service`` is ``inactive
    (dead)`` and that is normal, not idle. The banner only flags problems
    when the timer itself is missing/inactive OR the most recent
    completed cycle failed OR the mirror has gone stale far beyond a
    normal between-cycles window.

    State priorities (most-severe first):
      1. ``mirror_missing`` → red (trainer has never published).
      2. ``last_cycle_failed`` → red (last cycle's overall_rc != 0).
      3. ``stale_no_timer`` → red (mirror age > 36 h AND timer not
         active/enabled — really broken).
      4. ``idle_no_timer`` → yellow (no cycles in 24 h AND timer
         inactive — really paused).
      5. ``waiting_for_timer`` → blue/info (timer active, no cycle yet
         today, last cycle succeeded — the normal between-cycles state).
      6. ``healthy`` → green (recent successful cycle and timer active).
    """
    if not payload.get("mirror_present"):
        st.error(
            "🛑 **Trainer mirror missing.** The trainer VM has never published "
            "state, or the publisher (`ict-trainer-publish.timer`) is not "
            "running. Until it does, this page has no visibility."
        )
        return

    status = payload.get("status") or {}
    age = payload.get("mirror_age_seconds")
    age_str = _fmt_age(age)

    svc = (status.get("service") or {})
    timer = (status.get("timer") or {})
    last_cycle = status.get("last_cycle") or {}
    last_rc = status.get("last_cycle_outcome")
    cycles_24h = status.get("cycles_24h", 0)

    svc_active = svc.get("active_state")
    svc_enabled = svc.get("unit_file_state")
    timer_state = timer.get("active_state")
    timer_enabled = timer.get("unit_file_state")

    # Daily-timer architecture: service inactive + timer active+enabled
    # = normal between-cycles waiting state. Only flag if the timer is
    # also missing — that's the real "paused" signal.
    timer_running = timer_state == "active" and timer_enabled == "enabled"
    really_stale = age is not None and age > 36 * 3600  # 36 h
    last_failed = isinstance(last_rc, int) and last_rc != 0
    waiting_for_next_cycle = timer_running and cycles_24h == 0 and not last_failed
    truly_idle = (not timer_running) and cycles_24h == 0

    # The trainer service is a *oneshot* run by ict-trainer.timer, so its
    # steady state between scheduled cycles is `inactive` — that is healthy,
    # not stopped. Showing the raw "inactive / enabled" alarmed at a glance
    # (it reads like the trainer is down when it's just waiting for its
    # timer). Relabel to a self-explanatory value and keep the raw systemd
    # state in the tooltip.
    if svc_active == "active":
        svc_display = "running"
    elif svc_active == "inactive" and timer_running:
        svc_display = "idle · scheduled"
    else:
        svc_display = svc_active or "?"

    cols = st.columns(4)
    cols[0].metric("Mirror age", age_str)
    cols[1].metric("Cycles (24 h)", cycles_24h)
    cols[2].metric(
        "Service",
        svc_display,
        help=(
            f"systemd `ict-trainer.service`: {svc_active or '?'} / {svc_enabled or '?'}. "
            "It's a oneshot launched by `ict-trainer.timer`, so `inactive` between "
            "scheduled cycles is the normal resting state — not a fault."
        ),
    )
    cols[3].metric("Timer", f"{timer_state or '?'} / {timer_enabled or '?'}")

    if last_failed:
        st.error(
            f"❌ **Last cycle failed** at {last_cycle.get('ts', '?')} with rc={last_rc}. "
            "See the Cycle Events table below for which manifest tripped."
        )
    elif really_stale and not timer_running:
        st.error(
            f"⏳ **Trainer silent and timer down** — last publish was {age_str} "
            "ago and `ict-trainer.timer` is not active+enabled. The pipeline "
            "is genuinely paused."
        )
    elif truly_idle:
        st.warning(
            f"💤 **Trainer paused.** Timer is `{timer_state or '?'}/{timer_enabled or '?'}` "
            "and no cycle ran in 24 h. Re-enable via `trainer-vm-diag-request` "
            "(`systemctl enable --now ict-trainer.timer`)."
        )
    elif waiting_for_next_cycle:
        next_trigger = (
            timer.get("next_elapse")
            or timer.get("trigger")
            or timer.get("next_run")
            or "—"
        )
        last_ts = last_cycle.get("ts") or "—"
        st.info(
            f"⏱ **Trainer waiting for next daily cycle.** Timer active; "
            f"next trigger **{next_trigger}**. Last successful cycle at "
            f"`{last_ts}` ({age_str} ago). Service `inactive` between "
            "cycles is normal — this is a oneshot triggered by the timer."
        )
    else:
        st.success(
            f"✅ Trainer healthy — last publish {age_str} ago, "
            f"{cycles_24h} cycle(s) in 24 h."
        )

    head_sha = (status.get("trainer_vm") or {}).get("head_sha")
    role = (status.get("trainer_vm") or {}).get("role")
    if head_sha or role:
        st.caption(f"Trainer VM: `{role or '?'}` · repo HEAD `{head_sha or '?'}`")


def _render_cycle_events(rows: list[dict]) -> None:
    if not rows:
        st.caption("No cycle events mirrored yet.")
        return
    df = pd.DataFrame(rows)
    show_cols = [c for c in (
        "ts", "status", "manifest", "model_id", "exit_code",
        "overall_rc", "head", "stderr_tail",
    ) if c in df.columns]
    if not show_cols:
        st.dataframe(df, hide_index=True, use_container_width=True)
        return
    # Newest first for the table.
    df = df[show_cols].iloc[::-1].reset_index(drop=True)
    st.dataframe(df, hide_index=True, use_container_width=True, height=320)


def _render_build_health(rows: list[dict]) -> None:
    if not rows:
        st.caption("No dataset-build events mirrored yet.")
        return

    # If the most recent ``build_end`` event reports overall_rc=0, the
    # most recent build cycle SUCCEEDED — any earlier `failed` rows in
    # the tail are historical and don't reflect the current state.
    # Render those as an info expander rather than red errors so the
    # page doesn't lie about the trainer being broken when it isn't.
    last_build_end = next(
        (r for r in reversed(rows) if r.get("status") == "build_end"), None
    )
    most_recent_ok = (
        last_build_end is not None
        and (last_build_end.get("overall_rc") in (0, "0", None))
    )

    failed = [r for r in rows if r.get("status") == "failed"]
    skipped = [r for r in rows if r.get("status") == "skipped"]

    if failed and most_recent_ok:
        # Historical context only — the current pipeline is healthy.
        with st.expander(
            f"ℹ️ {len(failed)} historical build failure(s) in the log "
            "(current cycle succeeded — these are resolved)"
        ):
            for row in failed[-5:]:
                family = row.get("family", "?")
                tail = (row.get("stderr_tail") or "").strip()
                st.markdown(f"- **{family}** ({row.get('ts', '?')}) — `{tail[:200]}`")
    elif failed:
        # Most recent cycle had failures — these are live issues.
        st.error(f"❌ {len(failed)} dataset build failure(s) in the recent log. "
                 "These block the manifests that depend on them.")
        for row in failed[-5:]:  # newest 5
            family = row.get("family", "?")
            tail = (row.get("stderr_tail") or "").strip()
            st.markdown(f"- **{family}** ({row.get('ts', '?')}) — `{tail[:200]}`")
    elif last_build_end is None and len(rows) > 0:
        # No build_end marker yet but builds are happening — building
        # right now (cycle in progress) or builds haven't completed.
        st.caption(f"Build cycle in progress — {len(rows)} event(s) so far.")
    else:
        st.success(
            f"✅ Most recent dataset-build cycle succeeded "
            f"({last_build_end.get('ts', '?')})."
        )

    if skipped:
        with st.expander(f"Skipped families ({len(skipped)})"):
            for row in skipped[-10:]:
                st.markdown(
                    f"- **{row.get('family', '?')}** ({row.get('ts', '?')}) — "
                    f"{row.get('detail', '?')}"
                )
    df = pd.DataFrame(rows)
    show_cols = [c for c in ("ts", "status", "family", "exit_code", "stderr_tail", "detail")
                 if c in df.columns]
    if show_cols:
        with st.expander(f"Full build log ({len(rows)} rows)"):
            st.dataframe(df[show_cols].iloc[::-1].reset_index(drop=True),
                         hide_index=True, use_container_width=True, height=240)


def _short_callable(qualname: str | None) -> str:
    """`ml.trainers.lightgbm.LightGBMClassifierTrainer` → `LightGBMClassifierTrainer`."""
    if not isinstance(qualname, str) or not qualname:
        return "—"
    return qualname.rsplit(".", 1)[-1]


def _render_model_card(model_id: str, rows: list[dict]) -> None:
    """One per-model card: deployment pill + linked strategy + about-this-model
    summary + latest run metrics + training history + stage history.

    The card consumes the enriched fields from `/api/bot/ml/registry`
    (PR #1391 in the bot repo): `deployment_bucket`, `linked_strategies`,
    `model_family`, `trainer`, `evaluator`, `dataset_ref`, `latest_run`.
    Falls back gracefully when the bot API hasn't been deployed with
    those fields yet — `_normalize_bucket` derives the bucket from the
    registry stage as a backstop.
    """
    latest = rows[-1]
    bucket = _normalize_bucket(latest)
    stage = latest.get("target_deployment_stage") or latest.get("stage") or "—"
    family = latest.get("model_family") or latest.get("family") or "—"
    linked = latest.get("linked_strategies") or []

    dot_state = {"LIVE": "live", "SHADOW": "shadow", "OFFLINE": "off"}.get(bucket, "unknown")
    label = (f"{_row_dot(dot_state)}  **{model_id}**  ·  {bucket}  ·  {stage}"
             + (f"  ·  used by {len(linked)}" if linked else ""))
    with st.expander(label):
        if linked:
            st.caption(f"**Used by:** {', '.join(linked)}")
        else:
            st.caption("**Used by:** — (no strategy references this model)")

        # Human-readable description from the model's manifest (`description`),
        # surfaced via /api/bot/ml/registry. Absent for rows whose manifest
        # predates the field (re-populates on the trainer's next registration).
        description = latest.get("description")
        if description:
            st.markdown(description)

        st.markdown("**About**")
        about_l, about_r = st.columns(2)
        with about_l:
            st.markdown(f"- **Family:** `{family}`")
            trainer = latest.get("trainer")
            if trainer:
                st.markdown(f"- **Trainer:** `{_short_callable(trainer)}`")
            evaluator = latest.get("evaluator")
            if evaluator:
                st.markdown(f"- **Evaluator:** `{_short_callable(evaluator)}`")
        with about_r:
            ds = latest.get("dataset_ref") or latest.get("dataset") or {}
            if isinstance(ds, dict) and ds:
                st.markdown(
                    f"- **Trained on:** `{ds.get('family')}/"
                    f"{ds.get('symbol_scope')}/{ds.get('timeframe')}/{ds.get('version')}`"
                )
            if latest.get("created_at"):
                st.markdown(f"- **First registered:** {latest['created_at']}")
            if latest.get("code_revision"):
                rev = str(latest["code_revision"])[:8]
                st.markdown(f"- **Code revision:** `{rev}`")

        notes = latest.get("notes")
        if notes:
            st.markdown(f"**Notes:** {notes}")

        # Latest-run metrics — inline (nested expanders aren't allowed inside
        # the row expander). Prefer the enriched `latest_run` field (PR #1391);
        # fall back to the per-run endpoint.
        latest_run = latest.get("latest_run")
        if isinstance(latest_run, dict) and latest_run:
            st.markdown("**Latest run**")
            rc1, rc2 = st.columns(2)
            rc1.caption(f"Run: `{latest_run.get('run_id', '—')}`")
            rc2.caption(f"At: {latest_run.get('at', '—')}")
            metrics = latest_run.get("metrics") or {}
            if metrics:
                st.json(metrics)
            else:
                st.caption("No metrics recorded for this run.")
        else:
            run_id = (
                latest.get("run_id")
                or (latest.get("metrics_path") or "").split("/")[-2]
                or None
            )
            if run_id:
                run_payload, run_err = _fetch(f"/api/bot/ml/runs/{model_id}/{run_id}")
                if run_err:
                    st.caption(f"Run metrics: not mirrored yet ({run_err})")
                else:
                    metrics = (run_payload or {}).get("metrics") or {}
                    if metrics:
                        st.markdown("**Latest run**")
                        st.json(metrics)

        # Logs — open by default, newest-first, capped at 10 with a Show-all toggle.
        runs = latest.get("runs") or []
        if isinstance(runs, list) and len(runs) > 1:
            st.markdown(f"**Training history · {len(runs)} runs**")
            history_rows = [
                {"run_id": r.get("run_id"), "at": r.get("at"), **(r.get("metrics") or {})}
                for r in reversed(runs)
            ]
            _capped_table(pd.DataFrame(history_rows), key=f"model_runs_{model_id}")
        if len(rows) > 1:
            st.markdown(f"**Stage history · {len(rows)} rows**")
            _capped_table(pd.DataFrame(list(reversed(rows))), key=f"model_stage_{model_id}")

        # Config — always shown, at the bottom.
        cfg = latest.get("trainer_config") or {}
        if cfg:
            st.markdown("**Trainer config**")
            st.json(cfg, expanded=False)


def _render_registry(registry_rows: list[dict]) -> None:
    if not registry_rows:
        st.info(
            "📭 **Model registry is empty.** No model has been promoted into "
            "`ml/registry-store/registry.jsonl` yet. This is expected on a "
            "trainer that has not completed a successful training cycle."
        )
        return

    # Group by model_id — the registry is append-only with one row per
    # stage-history event, so a single model may appear N times.
    by_model: dict[str, list[dict]] = {}
    for row in registry_rows:
        mid = row.get("model_id") or "?"
        by_model.setdefault(mid, []).append(row)

    # Roll-up counters for the operator's two-bucket view.
    bucket_counts = {"LIVE": 0, "SHADOW": 0, "OFFLINE": 0}
    for _mid, rows in by_model.items():
        bucket = _normalize_bucket(rows[-1])
        bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Models", len(by_model))
    c2.metric("🟢 LIVE", bucket_counts["LIVE"])
    c3.metric("🔵 SHADOW", bucket_counts["SHADOW"])
    c4.metric("⚫ OFFLINE", bucket_counts["OFFLINE"])
    st.caption(_BUCKET_LEGEND)

    # Render OFFLINE last so the operator sees the actively-deployed
    # models first.
    def _sort_key(item: tuple[str, list[dict]]) -> tuple[int, str]:
        bucket = _normalize_bucket(item[1][-1])
        order = {"LIVE": 0, "SHADOW": 1, "OFFLINE": 2}.get(bucket, 3)
        return (order, item[0])

    for model_id, rows in sorted(by_model.items(), key=_sort_key):
        _render_model_card(model_id, rows)


def page_models() -> None:
    st.header("Models & Training Center")

    # Graceful degradation (2026-05-18): a failed /status fetch used to
    # `return` and blank the whole page. Now we surface a warning and
    # render whatever subsections can fetch — operator still sees the
    # registry, cycle events, and build health even when one endpoint
    # is unreachable.
    status_payload, status_err = _fetch("/api/bot/ml/status")
    if status_err:
        st.warning(
            f"⚠️ Trainer status endpoint unreachable: {status_err}. "
            "Status banner skipped — the rest of the page will still render "
            "with whatever data the other endpoints can fetch."
        )
    else:
        _trainer_status_banner(status_payload or {})

    st.divider()

    # ── Cycle events ────────────────────────────────────────────────
    st.subheader("Cycle Events")
    cycle_payload, cycle_err = _fetch("/api/bot/ml/cycle?limit=100")
    if cycle_err:
        st.caption(f"Cycle log unavailable ({cycle_err}).")
    else:
        rows = (cycle_payload or {}).get("rows", [])
        _render_cycle_events(rows)

    # ── Per-manifest sessions ───────────────────────────────────────
    sess_payload, sess_err = _fetch("/api/bot/ml/sessions")
    if not sess_err:
        sessions = (sess_payload or {}).get("sessions", [])
        ok = [s for s in sessions if s.get("status") == "manifest_ok"]
        bad = [s for s in sessions if s.get("status") == "manifest_failed"]
        skipped = [s for s in sessions if s.get("status") == "manifest_skipped"]
        missing = [s for s in sessions if s.get("status") == "manifest_missing"]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Manifest OK (recent)", len(ok))
        c2.metric("Manifest failed", len(bad))
        c3.metric("Manifest skipped", len(skipped))
        c4.metric("Manifest missing", len(missing))
        if bad:
            with st.expander(f"Recent failed manifests ({len(bad)})", expanded=True):
                for row in bad[-10:]:
                    st.error(
                        f"**{row.get('manifest', '?')}** "
                        f"(rc={row.get('exit_code', '?')}, {row.get('ts', '?')}) — "
                        f"`{(row.get('stderr_tail') or '').strip()[:240]}`"
                    )
        if skipped:
            # Skipped is not a failure — render as info, not red.
            # Common reason today: dataset has 0 rows (live trader hasn't
            # produced enough closed-trade history yet, or no health-review
            # answers exist for the review_journal family).
            with st.expander(f"Recently skipped manifests ({len(skipped)})"):
                for row in skipped[-10:]:
                    reason = row.get("reason") or "skipped"
                    detail = row.get("detail") or row.get("dataset_path") or ""
                    st.info(
                        f"**{row.get('manifest', '?')}** "
                        f"({row.get('ts', '?')}) — {reason}: `{detail}`"
                    )

    st.divider()

    # ── Dataset build health ────────────────────────────────────────
    st.subheader("Dataset Build Health")
    builds_payload, builds_err = _fetch("/api/bot/ml/builds?limit=100")
    if builds_err:
        st.caption(f"Build log unavailable ({builds_err}).")
    else:
        _render_build_health((builds_payload or {}).get("rows", []))

    # ── DB pull freshness ───────────────────────────────────────────
    pulls_payload, pulls_err = _fetch("/api/bot/ml/db_pulls?limit=20")
    if not pulls_err:
        pull_rows = (pulls_payload or {}).get("rows", [])
        last_done = next(
            (r for r in reversed(pull_rows)
             if r.get("status") == "sync_done" and r.get("overall_rc") == 0),
            None,
        )
        if last_done:
            st.caption(
                f"Last live-VM → trainer DB sync: **{last_done.get('ts', '?')}**"
            )
        elif pull_rows:
            st.caption("DB sync history present but no successful `sync_done` row.")

    st.divider()

    # ── Model registry ──────────────────────────────────────────────
    st.subheader("Model Registry")
    registry_payload, registry_err = _fetch("/api/bot/ml/registry")
    if registry_err:
        st.caption(f"Registry unavailable ({registry_err}).")
        return
    _render_registry((registry_payload or {}).get("rows", []))


# ── Promotion Readiness (shadow tracker) ──────────────────────────────────────────

# Promotion rubric thresholds — a shadow model is "ready to evaluate" only
# once it has logged enough informative predictions over enough calendar
# time that drift + outcome signal are meaningful. Tunable here.
PROMO_MIN_DAYS = 7        # calendar days a model must shadow before evaluation
PROMO_MIN_PREDS = 200     # prediction volume floor over its lifetime
PROMO_FRESH_HOURS = 24    # last prediction must be within this window to be "live"
PROMO_FLAT_EPS = 1e-6     # score range below this = a constant (no information)


def _parse_iso(s: str | None) -> dt.datetime | None:
    if not s:
        return None
    try:
        d = dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return d


def _is_regime_model(model_id: str) -> bool:
    return "regime" in (model_id or "").lower()


def _promotion_verdict(s: dict) -> tuple[str, str, dict]:
    """Grade one shadow/stats row → (emoji_label, severity, facts).

    severity ∈ {ok, warn, bad, idle} drives ordering + colour. `facts`
    carries the derived numbers the table renders so they're computed once.
    """
    now = dt.datetime.now(dt.timezone.utc)
    count = int(s.get("count") or 0)
    first = _parse_iso(s.get("first_seen"))
    last = _parse_iso(s.get("last_seen"))
    smin = s.get("score_min")
    smax = s.get("score_max")
    row_keys = s.get("row_keys_seen") or []
    days = (now - first).total_seconds() / 86400 if first else 0.0
    fresh_h = (now - last).total_seconds() / 3600 if last else None
    rng = (
        float(smax) - float(smin)
        if smin is not None and smax is not None else None
    )
    regime = _is_regime_model(s.get("model_id", ""))
    wired = (not regime) or ("vol_bucket" in row_keys)
    live = fresh_h is not None and fresh_h <= PROMO_FRESH_HOURS
    informative = rng is not None and rng > PROMO_FLAT_EPS
    mature = days >= PROMO_MIN_DAYS and count >= PROMO_MIN_PREDS

    facts = {
        "count": count, "days": days, "fresh_h": fresh_h, "range": rng,
        "wired": wired, "informative": informative, "mature": mature,
        "live": live, "regime": regime, "score_mean": s.get("score_mean"),
    }

    if count == 0 or not live:
        return "⚪ No recent predictions", "idle", facts
    if regime and not wired:
        return "🔴 Not wired — no vol_bucket (retrain+deploy)", "bad", facts
    if not informative:
        return "🔴 Constant score — not informative", "bad", facts
    if not mature:
        return f"🟡 Maturing ({days:.0f}d · {count} preds)", "warn", facts
    return "🟢 Ready to evaluate for promotion", "ok", facts


_SEVERITY_ORDER = {"ok": 0, "warn": 1, "bad": 2, "idle": 3}


def _render_outcome_coverage() -> None:
    """Per-model coverage from /api/bot/trades/scores — how many trades each
    shadow model has scored, split winners vs losers where the closed-trades
    join supplies a realised PnL. Sparse by design until trades accrue."""
    scores_payload, err = _fetch("/api/bot/trades/scores?limit=200&include_open=false")
    if err:
        st.caption(f"Outcome coverage unavailable: {err}")
        return
    trades = (scores_payload or {}).get("trades") or []
    if not trades:
        st.caption(
            "No closed trades carry shadow scores yet — the prediction↔outcome "
            "correlation lights up as live trades accrue."
        )
        return
    # Win/loss lookup from closed trades (realisedPnl sign).
    closed, _ = _fetch("/api/bot/trades/closed?limit=200")
    pnl_by_id: dict[str, float] = {}
    for t in (closed or []):
        tid = str(t.get("id") or t.get("trade_id") or "")
        pnl = t.get("realizedPnl")
        if tid and pnl is not None:
            try:
                pnl_by_id[tid] = float(pnl)
            except (TypeError, ValueError):
                pass
    agg: dict[str, dict] = {}
    for tr in trades:
        tid = str(tr.get("trade_id") or "")
        pnl = pnl_by_id.get(tid)
        for sc in tr.get("scores") or []:
            mid = sc.get("model_id") or "?"
            a = agg.setdefault(mid, {"n": 0, "win_s": [], "loss_s": []})
            a["n"] += 1
            mean = sc.get("score_mean")
            if pnl is not None and mean is not None:
                (a["win_s"] if pnl > 0 else a["loss_s"]).append(float(mean))
    if not agg:
        st.caption("Shadow scores present but not yet joined to a closed trade.")
        return
    rows = []
    for mid, a in sorted(agg.items()):
        win_m = sum(a["win_s"]) / len(a["win_s"]) if a["win_s"] else None
        loss_m = sum(a["loss_s"]) / len(a["loss_s"]) if a["loss_s"] else None
        edge = (
            win_m - loss_m if win_m is not None and loss_m is not None else None
        )
        rows.append({
            "Model": mid,
            "Trades scored": a["n"],
            "Winners": len(a["win_s"]),
            "Losers": len(a["loss_s"]),
            "Mean score · win": fmt_num(win_m),
            "Mean score · loss": fmt_num(loss_m),
            "Score edge (win−loss)": fmt_num(edge),
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    st.caption(
        "“Score edge” > 0 means the model scored eventual winners higher than "
        "losers — the basic signal that its predictions track real outcomes. "
        "Needs a meaningful sample before it's trustworthy."
    )


def page_promotion() -> None:
    st.header("Promotion Readiness")
    st.caption(
        "Shadow models log predictions against the live trader but never "
        "influence orders. This page tracks whether each is producing "
        "**real, informative** predictions and is mature enough to evaluate "
        "for the operator-gated shadow → advisory promotion."
    )

    payload, err = _fetch("/api/bot/shadow/stats")
    if err:
        st.error(f"⚠️ Shadow stats unavailable: {err}")
        return
    if not (payload or {}).get("log_present"):
        st.info(
            "No shadow-prediction log on the live VM yet. Once shadow models "
            "are deployed and the trader ticks, predictions accrue here."
        )
        return
    records = (payload or {}).get("records") or []
    if not records:
        st.info("Shadow log present but empty — no predictions recorded yet.")
        return

    graded = []
    for s in records:
        label, sev, facts = _promotion_verdict(s)
        graded.append((s, label, sev, facts))
    graded.sort(key=lambda g: (_SEVERITY_ORDER.get(g[2], 9), g[0].get("model_id", "")))

    ready = sum(1 for _, _, sev, _ in graded if sev == "ok")
    broken = sum(1 for _, _, sev, _ in graded if sev == "bad")
    c1, c2, c3 = st.columns(3)
    c1.metric("Shadow models", len(graded))
    c2.metric("Ready to evaluate", ready)
    c3.metric("Needs attention", broken)

    if broken:
        st.warning(
            "Models flagged 🔴 are logging a **constant** score (no live "
            "`vol_bucket`) — they carry no information until the regime "
            "feature-wiring fix is deployed to the live trader and the model "
            "is retrained with frozen bucket edges."
        )

    table = []
    for s, label, _sev, f in graded:
        table.append({
            "Model": s.get("model_id", "?"),
            "Stage": s.get("stage", "?"),
            "Readiness": label,
            "Predictions": f["count"],
            "Days in shadow": f"{f['days']:.1f}",
            "Last seen": (
                _fmt_age(f["fresh_h"] * 3600) if f["fresh_h"] is not None else "—"
            ),
            "Score range": fmt_num(f["range"]),
            "Score mean": fmt_num(f["score_mean"]),
            "Wired": "✅" if f["wired"] else "❌",
        })
    st.dataframe(pd.DataFrame(table), use_container_width=True, hide_index=True)
    st.caption(
        f"Ready rubric: ≥ {PROMO_MIN_DAYS} days in shadow, ≥ {PROMO_MIN_PREDS} "
        "predictions, a non-constant score range, and (for regime models) a "
        "live `vol_bucket` feature. “Wired” ❌ on a regime model is the "
        "constant-score bug signature."
    )

    st.divider()
    st.subheader("Score drift (recent vs reference window)")
    model_ids = [s.get("model_id", "") for s, *_ in graded if s.get("model_id")]
    if model_ids:
        sel = st.selectbox("Model", model_ids, key="promo_drift_model")
        d, derr = _fetch(f"/api/bot/shadow/drift?model_id={sel}")
        if derr:
            st.caption(f"Drift unavailable: {derr}")
        elif d:
            verdict = d.get("verdict", "?")
            if verdict == "insufficient_data":
                st.caption(
                    f"Not enough data in both windows yet "
                    f"(ref={d.get('reference_count', 0)}, "
                    f"cur={d.get('current_count', 0)})."
                )
            else:
                vcol = {"stable": "🟢", "watch": "🟡", "drift": "🔴"}.get(
                    str(verdict).lower(), "⚪"
                )
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Verdict", f"{vcol} {verdict}")
                m2.metric("KS", fmt_num(d.get("ks")))
                m3.metric("PSI", fmt_num(d.get("psi")))
                m4.metric(
                    "Mean shift",
                    fmt_num(
                        (d.get("current_mean") or 0) - (d.get("reference_mean") or 0)
                    ),
                )
                st.caption(
                    f"Reference {fmt_num(d.get('reference_mean'))}±"
                    f"{fmt_num(d.get('reference_stdev'))} "
                    f"→ current {fmt_num(d.get('current_mean'))}±"
                    f"{fmt_num(d.get('current_stdev'))}. A near-zero current "
                    "stdev means the model is emitting a constant."
                )

    st.divider()
    st.subheader("Prediction ↔ outcome coverage")
    _render_outcome_coverage()


# ── Backtesting ──────────────────────────────────────────────────────────────────

def _render_backtest_sweeps() -> None:
    """Strategy-improvement / validation sweeps mirrored from the trainer VM.

    These are the real backtests the operator runs (`run_backtest_sweep.sh`
    on the trainer → `all_metrics.json` + `SUMMARY.md` per UTC date,
    published to the live VM via the trainer mirror). SUMMARY.md is a
    schema-stable comparable table, so it is the primary render; the raw
    per-variant metrics sit behind a drill-down expander.
    """
    data, err = _fetch("/api/bot/backtests/sweeps")
    if err:
        st.warning(f"Backtest sweeps endpoint error: {err}")
        return

    env = data or {}
    sweeps = env.get("sweeps") or []
    if not env.get("present") or not sweeps:
        st.info(
            "No backtest sweeps mirrored yet. The strategy-improvement harness "
            "(`scripts/ops/run_backtest_sweep.sh`) runs on the trainer VM and "
            "publishes results to the dashboard via the trainer mirror — they "
            "appear here once the next mirror cycle lands."
        )
        return

    age = env.get("mirror_age_seconds")
    if age is not None:
        st.caption(f"Trainer mirror · updated {_fmt_age(age)} ago · {len(sweeps)} sweep(s)")

    for i, sw in enumerate(sweeps):
        date = sw.get("date", "—")
        gen = sw.get("generated_at") or ""
        label = f"\U0001f4ca  {date}" + (f"  ·  generated {gen}" if gen else "")
        with st.expander(label, expanded=(i == 0)):
            summary = sw.get("summary_md")
            if summary:
                st.markdown(summary)
            else:
                st.caption("No SUMMARY.md in this sweep.")

            metrics = sw.get("metrics")
            extra = sw.get("extra_metrics") or {}
            if metrics is not None or extra:
                with st.expander("Raw metrics (per-variant)"):
                    if metrics is not None:
                        st.json(metrics)
                    for name, payload in extra.items():
                        st.caption(name)
                        st.json(payload)


def page_backtesting() -> None:
    st.header("Backtesting")

    _render_backtest_sweeps()

    st.divider()
    st.subheader("On-demand `/test` runs")
    st.caption(
        "Ad-hoc Telegram `/test <strategy>` backtests (the M5 consumer). "
        "Empty unless the on-demand consumer is enabled on the live VM."
    )

    col_f, col_l = st.columns([3, 1])
    with col_f:
        strategy_filter = st.text_input("Filter by strategy", placeholder="e.g. ict-v1")
    with col_l:
        limit = st.selectbox("Show", [25, 50, 100, 200], index=1)

    path = f"/api/bot/backtests?limit={limit}"
    if strategy_filter.strip():
        path += f"&strategy={strategy_filter.strip()}"

    rows, err = _fetch(path)
    if err:
        st.warning(f"Backtests endpoint error: {err}")
        return
    if not rows:
        st.caption("No on-demand `/test` runs recorded.")
        return

    df = pd.DataFrame(rows)

    st.subheader("Summary")
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Total runs", len(df))
    m2.metric("Avg win rate",      fmt_pct(df["winRate"].mean()       if "winRate"      in df else None))
    m3.metric("Avg profit factor",
              _fmt_num_or_dash(df["profitFactor"].mean()) if "profitFactor" in df else "—")
    m4.metric("Best PnL",  fmt_usd(df["totalPnl"].max() if "totalPnl" in df else None))
    m5.metric("Worst PnL", fmt_usd(df["totalPnl"].min() if "totalPnl" in df else None))

    if {"winRate", "runDate"}.issubset(df.columns):
        st.subheader("Win Rate Over Runs")
        chart_df = df[["runDate", "winRate", "totalPnl"]].sort_values("runDate")
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=chart_df["runDate"], y=chart_df["winRate"],
            name="Win Rate %", line=dict(color="#3d7aed", width=2),
            mode="lines+markers", marker=dict(size=6),
        ))
        fig.add_trace(go.Bar(
            x=chart_df["runDate"], y=chart_df["totalPnl"],
            name="Total PnL",
            marker_color=["#22c55e" if v >= 0 else "#ef4444" for v in chart_df["totalPnl"]],
            yaxis="y2", opacity=0.5,
        ))
        fig.update_layout(
            template="plotly_dark", plot_bgcolor="#060c1a", paper_bgcolor="#060c1a",
            height=300, margin=dict(l=0, r=0, t=10, b=0),
            yaxis=dict(title="Win Rate %"),
            yaxis2=dict(title="PnL", overlaying="y", side="right"),
            legend=dict(orientation="h", y=1.05),
        )
        st.plotly_chart(fig, use_container_width=True)

    st.subheader("All Runs")
    col_map = {
        "id": "ID", "strategy": "Strategy", "runDate": "Run Date",
        "startDate": "Start", "endDate": "End", "totalTrades": "Trades",
        "winRate": "Win %", "profitFactor": "PF", "expectancy": "Expectancy",
        "sharpeRatio": "Sharpe", "maxDrawdownPct": "Max DD %", "totalPnl": "PnL",
    }
    display_cols = [c for c in col_map if c in df.columns]
    st.dataframe(df[display_cols].rename(columns=col_map), hide_index=True, use_container_width=True)

    if "id" in df.columns:
        st.subheader("Run Detail")
        selected_id = st.selectbox("Select run ID", df["id"].tolist())
        if selected_id:
            row = df[df["id"] == selected_id].iloc[0].to_dict()
            d1, d2, d3, d4 = st.columns(4)
            d1.metric("Total Trades",  row.get("totalTrades", "—"))
            d2.metric("Win Rate",      fmt_pct(row.get("winRate")))
            d3.metric("Total PnL",    fmt_usd(row.get("totalPnl")))
            d4.metric("Profit Factor", _fmt_num_or_dash(row.get("profitFactor")))
            d5, d6, d7, d8 = st.columns(4)
            d5.metric("Winning",    row.get("winningTrades", "—"))
            d6.metric("Losing",     row.get("losingTrades",  "—"))
            d7.metric("Expectancy", fmt_usd(row.get("expectancy")))
            d8.metric("Max DD %",   fmt_pct(row.get("maxDrawdownPct")))


# ── Strategies ───────────────────────────────────────────────────────────────────

# Colour key for the M7 gate's proposed_action. The hex values come from
# the existing _TV_GREEN family palette to stay visually consistent with
# the live/dry status dots above. `tune` is the M8 hand-off — neutral
# yellow, neither alarming nor reassuring.
_M7_ACTION_COLOR = {
    "kill":          "#d04848",  # red — disable the strategy
    "demote_shadow": "#d68e1f",  # orange — flip execution: shadow
    "tune":          "#d6c01f",  # yellow — point at the M8 parameter sweep
    "promote":       "#2eaa4e",  # green  — flip execution: live (shadow → live)
    "hold":          "#6b7488",  # grey   — no change recommended
}


def _fmt_pct_or_dash(v: Optional[float]) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v):.1%}"
    except (TypeError, ValueError):
        return "—"


def _fmt_num_or_dash(v: Optional[float], decimals: int = 2) -> str:
    if v is None:
        return "—"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "—"
    if f != f:  # NaN (e.g. an all-null column's .mean())
        return "—"
    return f"{f:.{decimals}f}"


def _render_strategy_review(name: str) -> None:
    """Render the latest M7 review packet for *name* (if one exists).

    Reads ``GET /api/bot/strategies/{name}/review`` — Tier 1, returns a
    ``{present, packet, …}`` envelope. When ``present: false`` (the
    bot's packet generator has never been run for this strategy), this
    helper renders a short ghost caption pointing at the
    ``generate-strategy-review-packets`` operator action instead of
    leaving the section blank. When ``present: true`` it surfaces:

    - ``proposed_action`` as a coloured badge.
    - Headline numbers (n_closed, win_rate, expectancy, pnl_total).
    - Tier-3 SLA due-by when the action is ``demote_shadow`` / ``kill``.
    - Reasons list — the matrix's explanation.

    The full packet JSON is offered in a collapsed ``st.json`` for
    drill-down without leaving the page.
    """
    review, err = _fetch(f"/api/bot/strategies/{quote(name)}/review")
    st.markdown("**M7 review packet**")
    if err:
        st.caption(f"_review endpoint error: {err}_")
        return
    review = review or {}
    if not review.get("present"):
        st.caption(
            "_No packet yet. Run `generate-strategy-review-packets` "
            "(`docs/strategy-review-gate.md`)._"
        )
        return

    packet = review.get("packet") or {}
    action = str(packet.get("proposed_action") or "hold").lower()
    colour = _M7_ACTION_COLOR.get(action, "#6b7488")
    h = packet.get("headline") or {}
    sla = packet.get("sla_due_by")
    generated_at = (packet.get("generated_at") or "")[:19]

    badge_html = (
        f"<span style='display:inline-block;background:{colour};"
        f"color:white;font-weight:600;letter-spacing:0.04em;"
        f"padding:3px 12px;border-radius:4px;font-size:0.85rem;'>"
        f"{action.upper()}</span>"
    )
    sla_html = (
        f"<br><span style='color:#aeb6c6;font-size:0.78rem;'>Tier-3 SLA due `{sla[:10]}`</span>"
        if sla else ""
    )
    st.markdown(badge_html + sla_html, unsafe_allow_html=True)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("n_closed", h.get("n_closed", 0))
    m2.metric("win_rate", _fmt_pct_or_dash(h.get("win_rate")))
    m3.metric("expectancy", _fmt_num_or_dash(h.get("expectancy"), 4))
    m4.metric("pnl_total", _fmt_num_or_dash(h.get("pnl_total")))

    reasons = packet.get("reasons") or []
    for r in reasons:
        st.caption(f"• {r}")

    # Brief footer with the window + generation timestamp so the
    # operator can tell at a glance how fresh the verdict is.
    win_start = (packet.get("window_start") or "")[:10]
    win_end = (packet.get("window_end") or "")[:10]
    if win_start and win_end:
        st.caption(
            f"_window {win_start} → {win_end} · packet generated {generated_at}Z_"
        )

    # Drill-down — the full packet, collapsed by default.
    if st.checkbox(f"Show full packet JSON · {name}", key=f"m7_full_{name}"):
        st.json(packet)


# M8 tune-result recommendation colours (advisory action → badge).
_M8_TUNE_COLOR = {
    "propose_value": "#2e9e5b",        # green — an OOS/k-fold-validated improvement
    "hold_current": "#6b7488",         # grey — current value already best
    "insufficient_evidence": "#d6c01f",  # yellow — widen the grid/window
}


def _render_strategy_tune(name: str) -> None:
    """Render the latest M8 parameter-sweep results for *name* (if any).

    Reads ``GET /api/bot/strategies/{name}/tune`` — Tier 1, returns a
    ``{present, date, results:[strategy_tune_result/v1, …]}`` envelope (one entry
    per tuned param). For each result it surfaces the advisory recommendation
    (proposed value + the exact Tier-3 YAML line), an OOS/robustness summary, a
    compact metric grid, and a collapsed full-JSON drill-down. ``present:false``
    → a ghost caption pointing at the bot's tune harness. Advisory only — every
    value change is an operator-gated Tier-3 config edit; the dashboard never
    initiates one.
    """
    tune, err = _fetch(f"/api/bot/strategies/{quote(name)}/tune")
    st.markdown("**M8 tune results**")
    if err:
        st.caption(f"_tune endpoint error: {err}_")
        return
    tune = tune or {}
    if not tune.get("present"):
        st.caption(
            "_No tune sweep yet. Run `scripts/ml/strategy_tune_sweep.py` "
            "(`docs/strategy-tuning.md`)._"
        )
        return

    date = tune.get("date") or ""
    for res in tune.get("results") or []:
        param = res.get("param") or "?"
        rec = res.get("recommendation") or {}
        action = str(rec.get("action") or "hold_current").lower()
        colour = _M8_TUNE_COLOR.get(action, "#6b7488")
        basis = str(rec.get("metric_basis") or res.get("metric_basis") or "full_sample")
        cur = res.get("current_value")
        proposed = rec.get("proposed_value")

        badge = (
            f"<span style='display:inline-block;background:{colour};color:white;"
            f"font-weight:600;letter-spacing:0.03em;padding:2px 10px;border-radius:4px;"
            f"font-size:0.8rem;'>{action.upper()}</span>"
            f"<span style='color:#aeb6c6;font-size:0.78rem;'> &nbsp;`{param}` · "
            f"basis: {basis}</span>"
        )
        st.markdown(badge, unsafe_allow_html=True)

        if proposed is not None:
            flags = []
            if rec.get("robust") is not None:
                fp, nf = rec.get("folds_positive"), rec.get("n_folds")
                flags.append(f"robust {rec['robust']} ({fp}/{nf} folds)" if nf else f"robust {rec['robust']}")
            if rec.get("train_oos_consistent") is not None:
                flags.append(f"train/OOS-consistent {rec['train_oos_consistent']}")
            flag_str = (" · " + " · ".join(flags)) if flags else ""
            st.caption(
                f"current `{cur}` → proposed **`{proposed}`** · "
                f"beats baseline {rec.get('beats_baseline')}{flag_str}"
            )
            st.caption(f"⚠ Tier-3 (operator-gated): `{rec.get('yaml_line', '')}`")
        else:
            st.caption(rec.get("detail") or "_no actionable pick._")

        # Compact grid — value vs net_total / expectancy / (folds+ if k-fold).
        grid = res.get("grid") or []
        if grid:
            kfold = any("folds_positive" in r for r in grid)
            rows = []
            for r in grid:
                row = {
                    "value": r.get("value"),
                    "trades": r.get("trades"),
                    "net_total": _fmt_num_or_dash(r.get("net_total")),
                    "net_exp": _fmt_num_or_dash(r.get("net_expectancy"), 3),
                    "maxDD": _fmt_num_or_dash(r.get("max_drawdown")),
                }
                if kfold:
                    row["folds+"] = f"{r.get('folds_positive')}/{r.get('n_folds')}"
                rows.append(row)
            try:
                import pandas as _pd
                st.dataframe(_pd.DataFrame(rows), hide_index=True, use_container_width=True)
            except Exception:
                st.json(rows)

        if st.checkbox(f"Show full tune JSON · {name}.{param}", key=f"m8_full_{name}_{param}"):
            st.json(res)
    if date:
        st.caption(f"_tune run {date}_")


def page_strategies() -> None:
    st.header("Strategies")
    data, err = _fetch("/api/bot/strategies")
    if err:
        st.warning(err)
        return
    data = data or {}
    strategies = data.get("strategies") or []
    runtime = data.get("runtime") or {}
    if not strategies:
        st.caption("No strategy data available.")
        return

    # Live-runtime banner — what the VM is actually running right now,
    # not just what the YAML enables. st.success/st.warning carry their own
    # status glyph, so no emoji prefix needed.
    tick_age = runtime.get("tick_age_seconds")
    if runtime.get("bot_running"):
        loaded = ", ".join(runtime.get("loaded_strategies") or []) or "—"
        st.success(f"Pipeline running · last tick {_fmt_age(tick_age)} ago · loaded: {loaded}")
    else:
        last = runtime.get("last_tick_utc") or "unknown"
        st.warning(
            f"Pipeline not confirmed running · last tick {last}"
            f"{f' ({_fmt_age(tick_age)} ago)' if tick_age is not None else ''}. "
            "Per-strategy status below reflects config; the bot may be between restarts."
        )

    # One closed-trade fetch feeds every strategy's 24h count + cumulative
    # P&L curve below (aggregated client-side, same source as the Overview
    # analytics). Lifetime stats still come from /api/bot/strategies.
    an_since = (dt.datetime.utcnow()
                - dt.timedelta(days=ANALYTICS_LOOKBACK_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    an_trades, _ = _fetch(
        "/api/bot/trades/closed?" + urlencode({"limit": ANALYTICS_MAX_ROWS, "since": an_since})
    )
    an_df = _closed_trades_frame(an_trades or [])

    for strat in strategies:
        name      = strat.get("name", "")
        enabled   = strat.get("enabled", True)
        loaded    = strat.get("loaded", False)
        running   = strat.get("running", False)
        accounts  = strat.get("accounts") or []
        risk_pct  = strat.get("risk_pct")
        timeframe = strat.get("timeframe", "—")
        stats     = strat.get("stats") or {}
        desc      = strat.get("description") or {}
        changelog = strat.get("changelog") or []

        if not enabled:
            state, status_label = "bad", "Disabled"
        elif running:
            state, status_label = "live", "Running"
        elif loaded:
            state, status_label = "stale", "Loaded · stale"
        else:
            state, status_label = "off", "Not loaded"

        sdf = _filter_strategy(an_df, name) if not an_df.empty else an_df
        trades_24h = _summary_window(sdf, 24)["trades"] if not sdf.empty else 0

        label = (f"{_row_dot(state)}  **{name}**  ·  {status_label}  ·  "
                 f"24h {trades_24h}  ·  {fmt_usd(stats.get('total_pnl'))}")
        with st.expander(label):
            if desc.get("short"):
                st.caption(desc["short"])

            if accounts:
                chips = " · ".join(
                    _status_dot(_TV_GREEN if a.get("live") else "#6b7488") + str(a.get("id"))
                    for a in accounts
                )
                st.markdown(
                    f"<div style='font-size:0.8rem;color:#aeb6c6;'>Routes to: {chips}</div>",
                    unsafe_allow_html=True,
                )
            else:
                st.caption("Routes to: — (no account routes this strategy)")

            m1, m2, m3, m4, m5, m6 = st.columns(6)
            m1.metric("Timeframe",     timeframe)
            m2.metric("Risk/trade",    f"{risk_pct}%" if risk_pct is not None else "—")
            m3.metric("Total trades",  stats.get("total_trades", 0))
            m4.metric("Trades · 24h",  trades_24h)
            m5.metric("Win rate",      fmt_pct(stats.get("win_rate_pct")))
            m6.metric("Total PnL",     fmt_usd(stats.get("total_pnl")))

            perf = build_cumulative_pnl_fig(sdf) if not sdf.empty else None
            if perf is not None:
                st.plotly_chart(perf, use_container_width=True,
                                config={"displayModeBar": False})
                st.caption(f"Cumulative realised P&L · last {ANALYTICS_LOOKBACK_DAYS}d "
                           f"(up to {ANALYTICS_MAX_ROWS} trades)")

            exit_reasons = stats.get("exit_reasons") or {}
            if exit_reasons:
                total = stats.get("total_trades") or 1
                reason_cols = st.columns(len(exit_reasons))
                for col, (reason, count) in zip(reason_cols, sorted(exit_reasons.items())):
                    col.metric(reason, count, f"{count / total * 100:.0f}%")

            if desc.get("how_it_works"):
                st.markdown("**How it works**")
                st.write(desc["how_it_works"])

            # Update log — open by default, capped at 10 with a Show-all toggle.
            st.markdown(f"**Update log · {len(changelog)} entries**")
            if changelog:
                _capped_table(pd.DataFrame(changelog), key=f"strat_log_{name}")
            else:
                st.caption("No changelog entries.")

            # M7 review packet — the mechanical gate's verdict on this strategy,
            # served by GET /api/bot/strategies/{name}/review. The bot-side
            # ict-trading-bot/docs/strategy-review-gate.md is the canonical
            # rubric; this card renders proposed_action + reasons + the
            # headline numbers the matrix consumed.
            _render_strategy_review(name)

            # M8 tune results — the parameter-sweep harness's OOS / k-fold
            # evidence for this strategy (GET /api/bot/strategies/{name}/tune,
            # from runtime_logs/strategy_tunes/). Advisory only — any value
            # change is an operator-gated Tier-3 config edit.
            _render_strategy_tune(name)

            # Config — always shown, at the bottom.
            if strat.get("config"):
                st.markdown("**Config parameters**")
                st.json(strat["config"], expanded=False)


# ── Data Explorer ─────────────────────────────────────────────────────────────

def page_data_explorer() -> None:
    st.header("Data Explorer")
    st.caption(
        "Read-only browse of the **federated canonical store** — the live "
        "trader's `trade_journal.db` and the trainer-store sidecar "
        "`trainer_store.db` (trainer/ML lifecycle data). Pick a table, filter "
        "by a column, and page through rows. Nothing here can write."
    )

    meta, err = _fetch("/api/bot/db/tables")
    if err:
        st.warning(f"DB tables endpoint error: {err}")
        return
    meta = meta or {}
    if not meta.get("present"):
        st.info("Database not available.")
        return
    tables = meta.get("tables") or []
    if not tables:
        st.caption("No tables found.")
        return

    st.subheader("Schema")
    dbs = meta.get("dbs") or [meta.get("db", "trade_journal")]
    st.caption(
        f"{len(tables)} tables across {len(dbs)} DB(s) ({', '.join(dbs)}) · "
        "the `[db]` tag shows which DB owns each table · expand a table to "
        "see its exact columns. ⚠️ marks empty tables."
    )
    for t in tables:
        rows = t.get("rows")
        tcols = t.get("columns") or []
        flag = "  ⚠️ empty" if rows == 0 else ""
        db_tag = t.get("db", "trade_journal")
        with st.expander(
            f"{t['name']}  `[{db_tag}]` — {rows if rows is not None else '?'} rows · {len(tcols)} cols{flag}"
        ):
            st.dataframe(
                pd.DataFrame([
                    {"Column": c.get("name"), "Type": c.get("type")} for c in tcols
                ]),
                hide_index=True, use_container_width=True,
            )
    st.divider()

    names = [t["name"] for t in tables]
    sel = st.selectbox("Table", names, key="dx_table")
    tinfo = next((t for t in tables if t["name"] == sel), {})
    cols = [c["name"] for c in (tinfo.get("columns") or [])]
    st.caption(
        f"{tinfo.get('rows', '?')} rows · "
        + ", ".join(f"{c['name']} `{c['type']}`" for c in (tinfo.get("columns") or []))
    )

    c1, c2, c3 = st.columns(3)
    with c1:
        order_by = st.selectbox("Order by", ["(none)"] + cols, key="dx_order")
    with c2:
        order_dir = st.selectbox("Direction", ["desc", "asc"], key="dx_dir")
    with c3:
        limit = st.selectbox("Rows/page", [25, 50, 100, 200, 500], index=2, key="dx_limit")

    f1, f2, f3 = st.columns(3)
    with f1:
        filter_col = st.selectbox("Filter column", ["(none)"] + cols, key="dx_fcol")
    with f2:
        filter_op = st.selectbox(
            "Op", ["eq", "ne", "gt", "lt", "gte", "lte", "like"], key="dx_fop",
        )
    with f3:
        filter_val = st.text_input("Value", key="dx_fval")

    page = int(st.number_input("Page", min_value=1, value=1, step=1, key="dx_page"))
    offset = (page - 1) * int(limit)

    params: dict[str, Any] = {"limit": limit, "offset": offset}
    # Route the read to the DB that owns the selected table (federation).
    if tinfo.get("db"):
        params["db"] = tinfo["db"]
    if order_by != "(none)":
        params["order_by"] = order_by
        params["order_dir"] = order_dir
    if filter_col != "(none)" and filter_val.strip():
        params["filter_col"] = filter_col
        params["filter_op"] = filter_op
        params["filter_val"] = filter_val.strip()

    data, derr = _fetch(f"/api/bot/db/table/{quote(sel)}?{urlencode(params)}")
    if derr:
        st.warning(derr)
        return
    data = data or {}
    rows = data.get("rows") or []
    total = data.get("total", 0)
    st.caption(f"Showing {len(rows)} of {total} rows · page {page}")
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
    else:
        st.caption("No rows match.")


# ── Insights (AI Analyst — server-side LLM, M13 S1) ──────────────────────────
#
# Backed by /api/bot/insights/{summary,recent,strategy/<name>,health}. The
# bot serves these from runtime_logs/insights/<endpoint>.json — files written
# every ~10 min by the ict-insights-generator.service systemd timer. The
# dashboard is a pure read-only consumer; nothing here calls Anthropic.
#
# The router returns a 200 placeholder envelope (cache_present=false) when
# the cache hasn't been written yet — typical right after a fresh activation
# or when the operator has set INSIGHTS_ENABLED=0. Render that gracefully
# rather than treating it as an error.

_INSIGHTS_GRADE_BADGE = {
    "good":       ("🟢", "#26a69a"),
    "mixed":      ("🟡", "#f5a623"),
    "concerning": ("🔴", "#ef5350"),
}
_INSIGHTS_SIGNAL_BADGE = {
    "low":  ("•",  "#888"),
    "med":  ("◆",  "#f5a623"),
    "high": ("●",  "#ef5350"),
}


def _format_cache_age(seconds: int | None) -> str:
    if seconds is None:
        return "no cache yet"
    if seconds < 90:
        return f"{seconds}s ago"
    if seconds < 60 * 90:
        return f"{seconds // 60} min ago"
    if seconds < 60 * 60 * 36:
        return f"{seconds // 3600}h {(seconds % 3600) // 60}m ago"
    return f"{seconds // (60 * 60 * 24)}d ago"


def _render_insight_envelope(payload: dict, *, compact: bool = False) -> None:
    """Render one insight envelope (any endpoint).

    ``compact=True`` is the Overview-card variant — no signals table,
    no raw row-counts, just the grade pill + summary + freshness line.
    """
    grade = (payload.get("grade") or "good").lower()
    emoji, color = _INSIGHTS_GRADE_BADGE.get(grade, ("⚪", "#888"))
    summary_md = payload.get("summary_md") or "_(empty)_"
    cache_present = payload.get("cache_present", True)
    cache_age = _format_cache_age(payload.get("cache_age_seconds"))
    model_id = payload.get("model_id") or "—"

    # Header strip: grade pill + freshness + model
    head_cols = st.columns([1, 2, 2])
    with head_cols[0]:
        st.markdown(
            f"<div style='font-size:1.3em;line-height:1;'>{emoji} "
            f"<span style='color:{color};font-weight:600'>{grade}</span></div>",
            unsafe_allow_html=True,
        )
    with head_cols[1]:
        if cache_present:
            st.caption(f"Cache: {cache_age}")
        else:
            st.caption("Cache not yet written")
    with head_cols[2]:
        st.caption(f"Model: `{model_id}`")

    st.markdown(summary_md)

    if compact:
        return

    # Signals — render only when present and the cache is real.
    signals = payload.get("signals") or []
    if signals and cache_present:
        st.markdown("**Signals**")
        for sig in signals:
            sev = (sig.get("severity") or "low").lower()
            mark, _ = _INSIGHTS_SIGNAL_BADGE.get(sev, ("•", "#888"))
            st.markdown(
                f"{mark} **{sig.get('kind', '?')}** "
                f"<span style='color:#888'>[{sev}]</span> — "
                f"{sig.get('note', '')}",
                unsafe_allow_html=True,
            )

    # Row counts + data window — transparency for the operator (so they can
    # see what window the LLM actually summarised).
    counts = payload.get("row_counts") or {}
    window = payload.get("data_window") or {}
    if counts or window:
        with st.expander("Data window + row counts", expanded=False):
            if window:
                st.json(window)
            if counts:
                st.json(counts)


def _render_overview_insight_card() -> None:
    """Compact 'Latest Analyst Read' card for the Overview page.

    Calls /api/bot/insights/summary. If the analyst hasn't been activated
    yet, the router returns the placeholder envelope and we render a
    one-line "no analyst data yet" hint rather than scaring the operator.
    """
    payload, err = _fetch("/api/bot/insights/summary")
    if err is not None:
        # The /insights router landed in M13 PR B — older bot deploys
        # return 404 here. That's fine; the overview card stays silent
        # until the bot's catch up.
        return
    if not isinstance(payload, dict):
        return
    cache_present = payload.get("cache_present", False)
    summary_md = (payload.get("summary_md") or "").strip()
    if not cache_present and not summary_md:
        return

    with st.container(border=True):
        st.markdown("**🧭 Latest Analyst Read**")
        _render_insight_envelope(payload, compact=True)


def _render_usage_panel() -> None:
    """Monthly spend + per-endpoint split + budget bar.

    Calls /api/bot/insights/usage (M13 S1 PR F). Silent no-op when the
    endpoint 404s (older bot deploys) or the table doesn't exist yet
    (fresh DB with no generator runs).
    """
    payload, err = _fetch("/api/bot/insights/usage")
    if err is not None or not isinstance(payload, dict):
        return
    if not payload.get("table_present"):
        return

    spent = float(payload.get("current_month_usd") or 0.0)
    budget = float(payload.get("budget_usd") or 0.0)
    tokens = int(payload.get("current_month_tokens") or 0)
    calls = int(payload.get("current_month_calls") or 0)
    pct = (spent / budget * 100) if budget > 0 else 0.0
    by_endpoint = payload.get("by_endpoint") or []

    with st.container(border=True):
        st.markdown("**💸 Analyst usage — this calendar month**")
        cols = st.columns(4)
        cols[0].metric("Spent", f"${spent:.2f}")
        cols[1].metric("Budget", f"${budget:.2f}")
        cols[2].metric("Tokens", f"{tokens:,}")
        cols[3].metric("Calls", f"{calls:,}")
        if budget > 0:
            st.progress(min(pct / 100.0, 1.0), text=f"{pct:.1f}% of budget")
        if by_endpoint:
            with st.expander("By endpoint", expanded=False):
                for row in by_endpoint:
                    ep = row.get("endpoint", "?")
                    sp = float(row.get("spent") or 0.0)
                    ca = int(row.get("calls") or 0)
                    st.markdown(f"- `{ep}` — ${sp:.4f} ({ca} calls)")


def _render_history_panel(endpoint: str, strategy_name: str | None = None) -> None:
    """Show the last N runs of an endpoint's analyst output.

    Each row is a collapsed expander label = `<grade dot> <ts> — <first 80 chars
    of summary_md>`; expanding shows the full envelope. Silent no-op when the
    history endpoint isn't deployed yet.
    """
    qs = f"endpoint={endpoint}&hours=24&limit=20"
    if strategy_name:
        qs += f"&strategy_name={quote(strategy_name, safe='')}"
    payload, err = _fetch(f"/api/bot/insights/history?{qs}")
    if err is not None or not isinstance(payload, dict):
        return
    if not payload.get("table_present"):
        return
    rows = payload.get("rows") or []
    if not rows:
        st.caption("_No historical runs yet (the generator has not landed a row in the last 24h)._")
        return

    with st.expander(f"📜 History — last {len(rows)} runs (24h)", expanded=False):
        for row in rows:
            grade = (row.get("grade") or "good").lower()
            emoji, _ = _INSIGHTS_GRADE_BADGE.get(grade, ("⚪", "#888"))
            ts = (row.get("generated_at") or "").replace("T", " ")[:19]
            snippet = (row.get("summary_md") or "").strip().splitlines()
            first_line = (snippet[0] if snippet else "")[:80]
            label = f"{emoji} {ts} — {first_line}"
            inner_payload = row.get("payload") or {}
            # Streamlit forbids nested expanders, so we use a checkbox to
            # toggle the full envelope inline instead.
            if st.checkbox(label, key=f"hist_{endpoint}_{strategy_name or ''}_{row.get('id')}"):
                _render_insight_envelope(inner_payload)


def page_insights() -> None:
    st.header("Insights")
    st.caption(
        "AI-generated narrative + grades over the bot's live trading data. "
        "Refreshed every ~10 min by the `ict-insights-generator` systemd "
        "timer on the bot VM; this page reads the cached output via "
        "`/api/bot/insights/*`."
    )

    # Usage / cost panel at the top — operator's at-a-glance "is the
    # budget gate biting?" signal. Hidden cleanly on older deploys.
    _render_usage_panel()

    # Endpoint picker — one subheader per call, so the operator can compare
    # the four narratives without leaving the page.
    summary_payload, summary_err = _fetch("/api/bot/insights/summary")
    recent_payload, recent_err = _fetch("/api/bot/insights/recent?limit=20")
    health_payload, health_err = _fetch("/api/bot/insights/health")

    st.subheader("Overall (last 24h)")
    if summary_err:
        st.warning(f"Insights summary unavailable: {summary_err}")
    elif isinstance(summary_payload, dict):
        _render_insight_envelope(summary_payload)
    else:
        st.info("No summary payload.")
    _render_history_panel("summary")

    st.divider()

    st.subheader("Recent closed trades")
    if recent_err:
        st.warning(f"Insights recent unavailable: {recent_err}")
    elif isinstance(recent_payload, dict):
        _render_insight_envelope(recent_payload)
    else:
        st.info("No recent payload.")
    _render_history_panel("recent")

    st.divider()

    # Per-strategy view. Discover strategy names from /api/bot/strategies
    # so the picker stays in sync with whatever is configured on the bot;
    # fall back to a small hardcoded list if that endpoint is unreachable.
    st.subheader("Per-strategy")
    strategies_payload, strategies_err = _fetch("/api/bot/strategies")
    strategy_names: list[str] = []
    if isinstance(strategies_payload, dict):
        # /api/bot/strategies returns `strategies` as a LIST of dicts, each
        # with a `name` (same shape page_strategies + _render_strategy_snapshot
        # consume). The strategy-insight endpoint only accepts [a-z0-9_]+ names.
        per = strategies_payload.get("strategies") or []
        if isinstance(per, list):
            strategy_names = sorted(
                name for s in per
                if isinstance(s, dict)
                for name in [s.get("name")]
                if isinstance(name, str)
                and name.replace("_", "").isalnum()
                and name.islower()
            )
    if not strategy_names:
        strategy_names = [
            "turtle_soup", "vwap", "ict_scalp_5m",
            "trend_donchian", "fade_breakout_4h", "squeeze_breakout_4h",
        ]
    selected = st.selectbox(
        "Strategy",
        options=strategy_names,
        key="insights_strategy_select",
    )
    if selected:
        strat_payload, strat_err = _fetch(
            f"/api/bot/insights/strategy/{quote(selected, safe='')}"
        )
        if strat_err:
            st.warning(f"Strategy insight unavailable: {strat_err}")
        elif isinstance(strat_payload, dict):
            _render_insight_envelope(strat_payload)
        _render_history_panel("strategy", strategy_name=selected)

    st.divider()

    st.subheader("Health snapshot narrative")
    if health_err:
        st.warning(f"Insights health unavailable: {health_err}")
    elif isinstance(health_payload, dict):
        _render_insight_envelope(health_payload)
    else:
        st.info("No health payload.")
    _render_history_panel("health")


# ── Health ────────────────────────────────────────────────────────────────────

def page_health() -> None:
    st.header("System Health")
    services, services_err = _fetch("/api/bot/health/services")
    latest, latest_err     = _fetch("/api/bot/health/latest")

    st.subheader("Systemd services")
    if services_err:
        st.warning(services_err)
    elif services and services.get("services"):
        st.dataframe(pd.DataFrame(services["services"]), hide_index=True, use_container_width=True)
    else:
        st.caption("No service data.")

    st.subheader("Latest health snapshot")
    if latest_err:
        st.warning(latest_err)
    elif latest and latest.get("present") and latest.get("snapshot"):
        snap = latest["snapshot"]
        s1, s2, s3 = st.columns(3)
        s1.metric("CPU",    fmt_pct(snap.get("cpu_percent")))
        s2.metric("Memory", fmt_pct(snap.get("memory_percent")))
        s3.metric("Disk",   fmt_pct(snap.get("disk_percent")))
        with st.expander("Raw snapshot"):
            st.json(snap)
    else:
        st.caption("No snapshot available.")


# ── Logs ──────────────────────────────────────────────────────────────────────

def page_news() -> None:
    """M9 news layer — what the news/event filter decided per actionable signal.

    Reads the bot's shadow-soak log via `/api/bot/news/recent`. Activation is
    source-driven since 2026-06-10 (the legacy `NEWS_ENABLED` flag was removed):
    the layer is active when `NEWS_SOURCE=rss`, or `NEWS_SOURCE=newsapi` with a
    `NEWS_API_KEY`. Until then the log is empty and this page renders a clear
    "not active" state.
    """
    st.header("News")
    st.caption(
        "M9 news layer: per-signal news sentiment + economic-event decisions. "
        "Veto blocks a trade on adverse high-impact news; the reductive influence "
        "downsizes when news/events oppose the trade direction (default-off)."
    )
    payload, err = _fetch("/api/bot/news/recent?limit=200")
    if err:
        st.warning(err)
        return
    if not isinstance(payload, dict) or not payload.get("present"):
        st.info(
            "News layer not active yet — no decisions logged. It begins recording "
            "once the bot selects a usable feed source: `NEWS_SOURCE=rss` "
            "(keyless), or `NEWS_SOURCE=newsapi` plus a `NEWS_API_KEY`."
        )
        return
    records = payload.get("records") or []
    if not records:
        st.caption("No news decisions recorded yet.")
        return

    df = pd.DataFrame(records)
    # Headline counts over the decision rows (skip the influence-applied rows).
    decisions = df[df.get("decision").notna()] if "decision" in df else df
    if "decision" in df and len(decisions):
        counts = decisions["decision"].value_counts().to_dict()
        vetoes = int(decisions["veto"].fillna(False).sum()) if "veto" in decisions else 0
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Decisions", len(decisions))
        c2.metric("Vetoes", vetoes)
        c3.metric("Boost / Reduce", f"{counts.get('boost', 0)} / {counts.get('reduce', 0)}")
        c4.metric("Neutral", counts.get("neutral", 0))

    # Friendly column order when present; tolerate missing keys across row kinds.
    preferred = ["ts", "symbol", "side", "strategy", "decision", "adjustment",
                 "veto", "event_risk", "factor", "action", "query", "reason"]
    cols = [c for c in preferred if c in df.columns]
    cols += [c for c in df.columns if c not in cols]
    st.dataframe(df[cols], hide_index=True, use_container_width=True, height=560)


def page_logs() -> None:
    st.header("Logs")
    rows, err = _fetch("/api/bot/logs")
    if err:
        st.warning(err)
        return
    if not rows:
        st.caption("No log entries.")
        return
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True, height=600)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    # Render the sidebar first — it owns the "Live data" toggle that decides
    # whether we auto-poll. When Live data is OFF (default on the preview app)
    # we skip the auto-refresh entirely, so the app only hits the bot when you
    # load or navigate, rather than polling it as a second always-on client.
    page = render_sidebar()
    live = bool(st.session_state.get("live_data", _DEFAULT_LIVE))

    # Non-blocking poll via a frontend timer (streamlit-autorefresh) so nav
    # clicks take effect immediately instead of waiting out a blocking sleep.
    if live and _AUTOREFRESH_AVAILABLE:
        st_autorefresh(interval=POLL_INTERVAL_S * 1000, key="poll")

    stats, stats_err = _fetch("/api/bot/stats")

    dispatch = {
        "Overview":      lambda: page_overview(stats, stats_err),
        "Performance":   page_performance,
        "Insights":      page_insights,
        "Accounts":      page_accounts,
        "Positions":     page_positions,
        "Signals":       page_signals,
        "News":          page_news,
        "Order Packages": page_order_packages,
        "Models":        page_models,
        "Promotion":     page_promotion,
        "Backtesting":   page_backtesting,
        "Strategies":    page_strategies,
        "Data Explorer": page_data_explorer,
        "Health":        page_health,
        "Logs":          page_logs,
    }
    dispatch.get(page, page_overview)()

    if live and not _AUTOREFRESH_AVAILABLE:
        time.sleep(POLL_INTERVAL_S)
        st.rerun()


if __name__ == "__main__":
    main()
