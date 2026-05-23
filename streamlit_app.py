"""ICT Trader Dashboard — Streamlit version with sidebar navigation.

Read-only dashboard for the ICT Trading Bot's FastAPI on the VPS.
Sidebar navigation is collapsible (hamburger on mobile) and the
pages render one at a time so there is no wasted network round-trip
for hidden tabs.

Local dev: `pip install -r requirements.txt && streamlit run streamlit_app.py`
Override the upstream with the BOT_API_URL env var.
"""
from __future__ import annotations

import datetime as dt
import os
import time
from typing import Any
from urllib.parse import quote, urlencode

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
import yfinance as yf

try:
    from streamlit_lightweight_charts import renderLightweightCharts as _render_lc
    _LC_AVAILABLE = True
except ImportError:
    _LC_AVAILABLE = False

BOT_API = os.environ.get("BOT_API_URL", "http://158.178.210.252:8001")
TIMEOUT_S = 10.0
POLL_INTERVAL_S = 10
DEFAULT_LIMIT = 50

# Yahoo Finance ticker mapping (dashboard uses bot symbol style for signal matching).
# MES (Micro E-mini S&P 500, IBKR) maps to the full-size continuous E-mini
# front-month `ES=F`, which tracks the identical S&P index level as MES and
# carries far deeper Yahoo history than the micro contract `MES=F`.
_YF_SYMBOL: dict[str, str] = {
    "BTCUSDT": "BTC-USD",
    "ETHUSDT": "ETH-USD",
    "SOLUSDT": "SOL-USD",
    "BNBUSDT": "BNB-USD",
    "XRPUSDT": "XRP-USD",
    "MES": "ES=F",
}

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
  [data-testid="stSidebar"] {
      background: linear-gradient(180deg, #050c1a 0%, #091428 100%);
      border-right: 1px solid #182040;
  }
  [data-testid="stSidebar"] .stRadio > div { gap: 2px; }
  [data-testid="stSidebar"] .stRadio label { padding: 6px 8px; border-radius: 6px; }
  [data-testid="stSidebar"] .stRadio label:hover { background: #182040; }
  [data-testid="stMetric"] {
      background: #0d1628;
      border: 1px solid #1a2840;
      border-radius: 8px;
      padding: 0.6rem 0.8rem;
  }
  .main .block-container { padding-top: 1.2rem; }
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


@st.cache_data(ttl=30, show_spinner=False)
def _fetch_candles(
    symbol: str, interval: str, limit: int = 200
) -> tuple[pd.DataFrame | None, str | None]:
    try:
        params = _YF_PARAMS.get(interval, _YF_PARAMS["15m"])
        yf_symbol = _YF_SYMBOL.get(symbol, symbol.replace("USDT", "-USD"))

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
    "Overview", "Performance", "Accounts", "Positions", "Signals",
    "Closed Trades", "Models", "Promotion", "Backtesting", "Strategies",
    "Data Explorer", "Health", "Logs", "Demo",
]

PAGE_ICONS = {
    "Overview": "\U0001f3e0", "Performance": "\U0001f4c8", "Accounts": "\U0001f4b3",
    "Positions": "\U0001f4cb", "Signals": "⚡", "Closed Trades": "✅",
    "Models": "\U0001f9e0", "Promotion": "\U0001f6a6", "Backtesting": "\U0001f52c",
    "Strategies": "♟️", "Data Explorer": "\U0001f5c3", "Health": "\U0001f48a",
    "Logs": "\U0001f4dc", "Demo": "\U0001f9ea",
}


def render_sidebar() -> str:
    with st.sidebar:
        st.markdown("### \U0001f4c8 ICT Trader")
        st.divider()

        stats, err = _fetch("/api/bot/stats")
        if err:
            st.error("⚠️ Bot unreachable")
        elif stats:
            status = stats.get("status", "unknown")
            icon = {"running": "\U0001f7e2", "paused": "\U0001f7e1", "stopped": "\U0001f534"}.get(status, "⚪")
            st.caption(f"{icon} **{status.upper()}** · {stats.get('datasource', '?')}")

        st.caption(f"⏱ {dt.datetime.utcnow().strftime('%H:%M:%S')} UTC")
        st.divider()

        page = st.radio(
            "nav", PAGES,
            format_func=lambda p: f"{PAGE_ICONS.get(p, '')} {p}",
            label_visibility="collapsed",
        )
        st.divider()
        st.caption(f"Auto-refresh every {POLL_INTERVAL_S}s")
        # Deploy marker — bump on each release so a stale Streamlit Cloud
        # instance is obvious at a glance. If this date is old, the app
        # needs a reboot/redeploy.
        st.caption("build 2026-05-22 · Promotion Readiness tracker")

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
                pnl = row.get(pnl_col, 0) if pnl_col else 0
                markers.append({
                    "time":     int(row["ts_utc"].timestamp()),
                    "position": "aboveBar",
                    "color":    _TV_GREEN if (pnl or 0) > 0 else _TV_RED,
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


def render_overview_chart(
    df: pd.DataFrame,
    signals:   list[dict] | None,
    trades:    list[dict] | None,
    symbol:    str,
    positions: list[dict] | None = None,
    height:    int = _LC_HEIGHT,
    key:       str = "overview_lc_chart",
    show_zones: bool = False,
) -> None:
    """Render the single TradingView Lightweight Charts candlestick.

    Overlays live-trade context like TradingView: signal/trade markers,
    entry/SL/TP/current-price lines for open positions, and (when
    show_zones) the latest signal's ICT zones the strategy traded on.

    Extending:
      - Marker tweaks: edit _lc_markers() above.
      - Price-line tweaks: edit _lc_price_lines() / _lc_zone_lines() above.
      - Theme: change _TV_BG / _LC_GRID_* at the top.
    """
    if not _LC_AVAILABLE:
        st.warning(
            "Install `streamlit-lightweight-charts` to enable the chart.\n"
            "`pip install streamlit-lightweight-charts`"
        )
        return

    candle_data = _lc_candle_data(df)
    markers     = _lc_markers(signals, trades, symbol)
    price_lines = _lc_price_lines(positions, df, symbol)
    if show_zones:
        price_lines = price_lines + _lc_zone_lines(signals, symbol)

    chart_opts = [{
        "chart": {
            "height": height,
            "layout": {
                "background": {"type": "solid", "color": _TV_BG},
                "textColor":  _TV_TEXT,
            },
            "grid": {
                "vertLines": {"color": _LC_GRID_V},
                "horzLines": {"color": _LC_GRID_H},
            },
            "crosshair": {"mode": 1},
            "rightPriceScale": {"borderColor": "#2a364a", "visible": True},
            "timeScale": {
                "borderColor":    "#2a364a",
                "timeVisible":    True,
                "secondsVisible": False,
            },
            # Touch / mobile: enable horizontal drag and pinch-to-zoom.
            # vertTouchDrag=False prevents the chart stealing page scroll.
            "handleScroll": {
                "mouseWheel":       True,
                "pressedMouseMove": True,
                "horzTouchDrag":    True,
                "vertTouchDrag":    False,
            },
            "handleScale": {
                "axisPressedMouseMove": True,
                "axisDoubleClickReset": True,
                "mouseWheel":           True,
                "pinch":                True,
            },
        },
        "series": [{
            "type": "Candlestick",
            "data": candle_data,
            "options": {
                "upColor":       _TV_GREEN,
                "downColor":     _TV_RED,
                "borderVisible": False,
                "wickUpColor":   _TV_GREEN,
                "wickDownColor": _TV_RED,
            },
            "markers":    markers,
            "priceLines": price_lines,
        }],
    }]

    _render_lc(chart_opts, key=key)


# ── Overview ──────────────────────────────────────────────────────────────────

def page_overview(stats: dict | None, stats_err: str | None) -> None:
    st.header("Overview")

    s  = stats or {}
    vm = s.get("vmHealth") or {}

    if stats_err:
        st.warning(f"Stats endpoint error: {stats_err}")
    else:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("24h PnL",     fmt_usd(s.get("pnl24h")))
        c2.metric("Total PnL",   fmt_usd(s.get("totalPnL")))
        c3.metric("Open trades", s.get("openTrades", 0))
        c4.metric("Win rate",    fmt_pct(s.get("winRate")))

        st.subheader("VM Health")
        h1, h2, h3 = st.columns(3)
        h1.metric("CPU",    fmt_pct(vm.get("cpu")))
        h2.metric("Memory", fmt_pct(vm.get("memory")))
        h3.metric("Disk",   fmt_pct(vm.get("disk")))

    # ── Live price chart (single TradingView-style chart) ───────────────────────
    st.subheader("Price Chart")
    # Controls stack full-width on mobile (see the <640px CSS rule).
    oc1, oc2 = st.columns(2)
    with oc1:
        ov_symbol = st.selectbox("Symbol", CHART_SYMBOLS, key="ov_symbol")
    with oc2:
        ov_interval = st.selectbox(
            "Interval", CHART_INTERVALS,
            index=CHART_INTERVALS.index("1m") if "1m" in CHART_INTERVALS else 0,
            key="ov_interval",
        )
    tg1, tg2, tg3, tg4, tg5 = st.columns(5)
    with tg1:
        ov_live = st.toggle(
            "Live trades", value=True, key="ov_live",
            help="Overlay open-position entry / SL / TP / current-price lines",
        )
    with tg2:
        ov_signals = st.toggle("Signals", value=True, key="ov_signals")
    with tg3:
        ov_zones = st.toggle(
            "Zones", value=True, key="ov_zones",
            help="Draw the latest signal's ICT zones (FVG band + liquidity sweep) "
                 "that the strategy actually traded on",
        )
    with tg4:
        ov_trades = st.toggle(
            "Closed", value=False, key="ov_trades",
            help="Recent closed-trade entry/exit markers",
        )
    with tg5:
        ov_wide = st.toggle(
            "Widescreen", value=False, key="ov_wide",
            help="Near-fullscreen view — hides the sidebar so the chart fills the screen",
        )

    # Open positions drive both the live-trade overlay and the live-PnL readout.
    positions, _ = _fetch("/api/bot/positions")
    sym_positions = [p for p in (positions or []) if p.get("symbol") == ov_symbol]
    if sym_positions:
        net_pnl = sum((p.get("unrealizedPnl") or 0) for p in sym_positions)
        pc1, pc2 = st.columns([1, 3])
        pc1.metric(f"Live PnL · {ov_symbol}", fmt_usd(net_pnl), delta=round(net_pnl, 2))
        pc2.caption(" · ".join(
            f"{str(p.get('side', '')).upper()} {p.get('qty', '?')} @ {p.get('entryPrice', '?')}"
            for p in sym_positions
        ))

    if ov_wide:
        # Near-fullscreen: hide the sidebar + strip page padding so the chart
        # fills the viewport. Pure CSS (mobile-safe); re-evaluated each run, so
        # untoggling restores the sidebar on the next interaction.
        st.html(
            "<style>[data-testid='stSidebar']{display:none;}"
            ".main .block-container{padding:0.4rem 0.6rem;max-width:100%;}</style>"
        )
    chart_height = 820 if ov_wide else _LC_HEIGHT

    df, candles_err = _fetch_candles(ov_symbol, ov_interval)
    if candles_err:
        st.warning(f"Candles unavailable: {candles_err}")
    elif df is None or df.empty:
        st.caption("No candle data.")
    else:
        sig_data = None
        if ov_signals:
            sig_data, _ = _fetch("/api/bot/signals")
            # Per-strategy signal filter — only when the endpoint tags signals
            # with their strategy (added in the bot's /api/bot/signals route).
            strategies = sorted({
                s.get("strategy") for s in (sig_data or []) if s.get("strategy")
            })
            if strategies:
                chosen = st.multiselect(
                    "Signal strategies", strategies, default=strategies,
                    key="ov_sig_strats",
                    help="Toggle which strategies' entry signals are drawn",
                )
                sig_data = [
                    s for s in sig_data
                    if not s.get("strategy") or s.get("strategy") in chosen
                ]
        trade_data = None
        if ov_trades:
            trade_data, _ = _fetch(f"/api/bot/trades/closed?limit={DEFAULT_LIMIT}")

        render_overview_chart(
            df, sig_data, trade_data, ov_symbol,
            positions=sym_positions if ov_live else None,
            height=chart_height,
            show_zones=ov_zones,
        )
        st.caption(
            f"Yahoo Finance · {_YF_SYMBOL.get(ov_symbol, ov_symbol)} · {ov_interval} · "
            f"up to 200 candles · pinch to zoom · auto-refreshes every {POLL_INTERVAL_S}s"
        )

    # ── PnL history (secondary) ─────────────────────────────────────────────────
    with st.expander("Realised PnL — last 30 days"):
        pnl, pnl_err = _fetch("/api/pnl/history?days=30")
        if pnl_err:
            st.info(f"PnL history unavailable: {pnl_err}")
        elif not pnl:
            st.caption("No PnL history yet.")
        else:
            df_pnl = pd.DataFrame(pnl)
            if {"date", "realizedPnl"}.issubset(df_pnl.columns):
                st.line_chart(df_pnl.set_index("date")[["realizedPnl"]])
            else:
                st.json(pnl)


# ── Chart symbol / interval choices (shared by the Overview chart) ──────────────

CHART_SYMBOLS   = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]
CHART_INTERVALS = list(_YF_PARAMS.keys())




# ── Performance Overview (per-symbol live trade context) ──────────────────────────
#
# Two tabs (BTCUSDT, MES). Each renders the live price chart for that symbol
# with TradingView-style trade context overlaid:
#   * strategy signal entry markers          (/api/bot/signals, symbol-filtered)
#   * live/open trade entry + TP + SL lines  (/api/bot/positions, symbol-filtered)
#   * live PnL for the open position(s)       (Position.unrealizedPnl)
#   * recent closed-trade entry/exit markers  (/api/bot/trades/closed)
# Candles come from Yahoo Finance (BTCUSDT -> BTC-USD, MES -> ES=F).

PERF_SYMBOLS   = ["BTCUSDT", "MES"]
PERF_INTERVALS = ["5m", "15m", "1h", "4h", "1d"]


def _positions_for_symbol(symbol: str) -> tuple[list[dict], str | None]:
    rows, err = _fetch("/api/bot/positions")
    if err:
        return [], err
    return [p for p in (rows or []) if str(p.get("symbol")) == symbol], None


def _render_open_trade_header(symbol: str, positions: list[dict]) -> None:
    if not positions:
        st.info(
            f"No open {symbol} position right now — the chart below still shows "
            "strategy signals and recent closed-trade context."
        )
        return
    net_pnl = sum((p.get("unrealizedPnl") or 0) for p in positions)
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
    if pat:
        st.caption(f"Active strategy on primary leg: **{pat}**")


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
            colors = [
                _TV_GREEN if (pnl_col and (r.get(pnl_col) or 0) > 0) else _TV_RED
                for _, r in sub.iterrows()
            ]
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
    _render_open_trade_header(symbol, positions)

    df, candles_err = _fetch_candles(symbol, interval)
    if candles_err:
        st.warning(f"Candles unavailable: {candles_err}")
        return
    if df is None or df.empty:
        st.caption("No candle data.")
        return

    last_price = float(df["close"].iloc[-1])

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
        f"Yahoo Finance · {_YF_SYMBOL.get(symbol, symbol)} · {interval} · "
        f"signals + open-trade entry/TP/SL + live PnL · auto-refreshes every "
        f"{POLL_INTERVAL_S}s"
    )


def page_performance() -> None:
    st.header("Performance Overview")
    st.caption(
        "Live price + trade context per symbol. BTCUSDT (Bybit) and "
        "MES (IBKR paper) trade side by side through the same strategies."
    )
    tab_btc, tab_mes = st.tabs(["📈 BTCUSDT", "📊 MES"])
    with tab_btc:
        render_performance_tab("BTCUSDT")
    with tab_mes:
        render_performance_tab("MES")


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

        pill = "\U0001f7e2 LIVE" if is_live else "⚫ DRY"
        st.subheader(f"{pill} · {aid}")
        st.caption(
            f"{exchange} · {market} · "
            f"strategies: {', '.join(strategies) if strategies else '— (none assigned)'}"
        )

        bal_val = (balances.get(aid) or {}).get("balance")
        acc_positions = [p for p in positions if p.get("account") == aid]
        unrealized = sum((p.get("unrealizedPnl") or 0) for p in acc_positions)

        # Realized PnL (30d) via the no-session, account-filtered history endpoint.
        realized = None
        ph, _ = _fetch(f"/api/pnl/history?days=30&account_id={aid}")
        if ph:
            try:
                realized = sum(float(r.get("realizedPnl") or 0) for r in ph)
            except (TypeError, ValueError):
                realized = None

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Balance",        fmt_usd(bal_val) if bal_val is not None else "—")
        m2.metric("Realized (30d)", fmt_usd(realized))
        m3.metric("Unrealized",     fmt_usd(unrealized) if acc_positions else "—")
        m4.metric("Open trades",    len(acc_positions))

        with st.expander("Recent trades (last 7 days)"):
            trades, terr = _fetch(
                f"/api/bot/trades/closed?limit=100&account_id={aid}&since={since_7d}"
            )
            if terr:
                st.warning(terr)
            elif not trades:
                st.caption("No closed trades in the last 7 days.")
            else:
                tdf = pd.DataFrame(trades)
                col_map = {
                    "symbol": "Symbol", "side": "Side", "pattern": "Strategy",
                    "entryPrice": "Entry", "exitPrice": "Exit",
                    "realizedPnl": "PnL", "realizedPnlPct": "PnL %",
                    "closeReason": "Close", "openedAt": "Opened", "closedAt": "Closed",
                }
                cols = [c for c in col_map if c in tdf.columns]
                st.dataframe(
                    tdf[cols].rename(columns=col_map) if cols else tdf,
                    hide_index=True, use_container_width=True,
                )
        st.divider()


# ── Positions ───────────────────────────────────────────────────────────────────

def page_positions() -> None:
    st.header("Open Positions")
    rows, err = _fetch("/api/bot/positions")
    if err:
        st.warning(err)
        return
    if not rows:
        st.caption("No open positions.")
        return
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)


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


# ── Closed Trades ─────────────────────────────────────────────────────────────────

def page_trades() -> None:
    st.header("Closed Trades")
    rows, err = _fetch(f"/api/bot/trades/closed?limit={DEFAULT_LIMIT}")
    if err:
        st.warning(err)
        return
    if not rows:
        st.caption("No closed trades.")
        return
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)


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
    pill = _format_pill(bucket)
    stage = latest.get("target_deployment_stage") or latest.get("stage") or "—"
    family = latest.get("model_family") or latest.get("family") or "—"
    linked = latest.get("linked_strategies") or []

    with st.container(border=True):
        # Header — pill + model_id + linked strategy + registry stage
        head_l, head_r = st.columns([3, 1])
        with head_l:
            st.markdown(f"### {pill} · `{model_id}`")
            if linked:
                st.caption(f"**Used by:** {', '.join(linked)}")
            else:
                st.caption("**Used by:** — (no strategy references this model)")
        with head_r:
            st.metric("Registry stage", stage)

        # About — type / class / dataset / decision logic hints
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

        # Latest run — metrics + run_id + timestamp.
        # Prefer the enriched `latest_run` field (PR #1391). Falls back
        # to the per-run endpoint /api/bot/ml/runs/{model_id}/{run_id}
        # for backward compat.
        latest_run = latest.get("latest_run")
        if isinstance(latest_run, dict) and latest_run:
            with st.expander("📊 Latest run metrics", expanded=True):
                rc1, rc2 = st.columns(2)
                rc1.caption(f"Run: `{latest_run.get('run_id', '—')}`")
                rc2.caption(f"At: {latest_run.get('at', '—')}")
                metrics = latest_run.get("metrics") or {}
                if metrics:
                    st.json(metrics)
                else:
                    st.caption("No metrics recorded for this run.")
        else:
            # Backward-compat: try the per-run endpoint.
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
                        with st.expander("📊 Latest run metrics", expanded=True):
                            st.json(metrics)

        # Training history — every recorded run with its metrics.
        runs = latest.get("runs") or []
        if isinstance(runs, list) and len(runs) > 1:
            with st.expander(f"📈 Training history ({len(runs)} runs)"):
                history_rows = []
                for r in runs:
                    history_rows.append({
                        "run_id": r.get("run_id"),
                        "at": r.get("at"),
                        **(r.get("metrics") or {}),
                    })
                st.dataframe(
                    pd.DataFrame(history_rows),
                    hide_index=True, use_container_width=True,
                )

        cfg = latest.get("trainer_config") or {}
        if cfg:
            with st.expander("⚙️ Trainer config"):
                st.json(cfg)

        # Stage-transition history (registry mutations over time).
        if len(rows) > 1:
            with st.expander(f"📜 Stage history ({len(rows)} rows)"):
                st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)


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
    st.header("🚦 Promotion Readiness")
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
    m3.metric("Avg profit factor", f"{df['profitFactor'].mean():.2f}" if "profitFactor" in df else "—")
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
            d4.metric("Profit Factor", f"{row.get('profitFactor', 0):.2f}")
            d5, d6, d7, d8 = st.columns(4)
            d5.metric("Winning",    row.get("winningTrades", "—"))
            d6.metric("Losing",     row.get("losingTrades",  "—"))
            d7.metric("Expectancy", fmt_usd(row.get("expectancy")))
            d8.metric("Max DD %",   fmt_pct(row.get("maxDrawdownPct")))


# ── Strategies ───────────────────────────────────────────────────────────────────

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
    # not just what the YAML enables.
    tick_age = runtime.get("tick_age_seconds")
    if runtime.get("bot_running"):
        loaded = ", ".join(runtime.get("loaded_strategies") or []) or "—"
        st.success(f"\U0001f7e2 Pipeline running · last tick {_fmt_age(tick_age)} ago · loaded: {loaded}")
    else:
        last = runtime.get("last_tick_utc") or "unknown"
        st.warning(
            f"\U0001f7e1 Pipeline not confirmed running · last tick {last}"
            f"{f' ({_fmt_age(tick_age)} ago)' if tick_age is not None else ''}. "
            "Per-strategy status below reflects config; the bot may be between restarts."
        )

    for strat in strategies:
        name      = strat.get("name", "")
        enabled   = strat.get("enabled", True)
        loaded    = strat.get("loaded", False)
        running   = strat.get("running", False)
        accounts  = strat.get("accounts") or []
        risk_pct  = strat.get("risk_pct")
        timeframe = strat.get("timeframe", "—")
        symbols   = ", ".join(strat.get("symbols") or []) or "—"
        stats     = strat.get("stats") or {}
        desc      = strat.get("description") or {}
        changelog = strat.get("changelog") or []

        if not enabled:
            badge = "\U0001f534 Disabled"
        elif running:
            badge = "\U0001f7e2 Running"
        elif loaded:
            badge = "\U0001f7e1 Loaded · tick stale"
        else:
            badge = "⚪ Configured · not loaded"

        st.subheader(f"{name}  ·  {badge}")
        st.caption(desc.get("short", ""))

        # Account routing — which accounts run this strategy + live/dry.
        if accounts:
            chips = []
            for a in accounts:
                dot = "\U0001f7e2" if a.get("live") else "⚫"
                chips.append(f"{dot} {a.get('id')}")
            st.caption("Routes to: " + " · ".join(chips))
        else:
            st.caption("Routes to: — (no account routes this strategy)")

        m1, m2, m3, m4, m5, m6 = st.columns(6)
        m1.metric("Timeframe",    timeframe)
        m2.metric("Risk/trade",   f"{risk_pct}%" if risk_pct is not None else "—")
        m3.metric("Symbols",      symbols)
        m4.metric("Total trades", stats.get("total_trades", 0))
        m5.metric("Win rate",     fmt_pct(stats.get("win_rate_pct")))
        m6.metric("Total PnL",   fmt_usd(stats.get("total_pnl")))

        exit_reasons = stats.get("exit_reasons") or {}
        if exit_reasons:
            total = stats.get("total_trades") or 1
            reason_cols = st.columns(len(exit_reasons))
            for col, (reason, count) in zip(reason_cols, sorted(exit_reasons.items())):
                col.metric(reason, count, f"{count / total * 100:.0f}%")

        if (desc or {}).get("how_it_works"):
            with st.expander("How it works"):
                st.write(desc["how_it_works"])
        if strat.get("config"):
            with st.expander("Config parameters"):
                st.json(strat["config"])
        if changelog:
            with st.expander(f"Update log ({len(changelog)} entries)"):
                st.dataframe(pd.DataFrame(changelog), hide_index=True, use_container_width=True)
        st.divider()


# ── Data Explorer ─────────────────────────────────────────────────────────────

def page_data_explorer() -> None:
    st.header("Data Explorer")
    st.caption(
        "Read-only browse of the bot's `trade_journal.db`. Pick a table, "
        "filter by a column, and page through rows. Nothing here can write."
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
    st.caption(
        f"{len(tables)} tables in `{meta.get('db', 'trade_journal.db')}` · "
        "expand a table to see its exact columns. ⚠️ marks empty tables."
    )
    for t in tables:
        rows = t.get("rows")
        tcols = t.get("columns") or []
        flag = "  ⚠️ empty" if rows == 0 else ""
        with st.expander(
            f"{t['name']} — {rows if rows is not None else '?'} rows · {len(tcols)} cols{flag}"
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


# ── Demo Account ──────────────────────────────────────────────────────────────

_DEMO_ACCOUNT_ID = "bybit_1"


def page_demo() -> None:
    st.header("🧪 Demo Trader (bybit_1)")
    st.caption(
        "Paper-money account on Bybit demo endpoint (api-demo.bybit.com). "
        "Runs all three strategies at live settings. "
        "Trades are logged separately and excluded from live PnL totals."
    )

    # ── PnL snapshot from /api/pnl ─────────────────────────────────────────
    pnl_all, pnl_err = _fetch("/api/pnl")
    if pnl_err:
        st.warning(f"PnL endpoint error: {pnl_err}")
    else:
        acct = ((pnl_all or {}).get("accounts") or {}).get(_DEMO_ACCOUNT_ID) or {}
        c1, c2, c3 = st.columns(3)
        c1.metric("Realised PnL",  fmt_usd(acct.get("realized_usd")))
        c2.metric("Unrealised PnL", fmt_usd(acct.get("unrealized_usd")))
        c3.metric("Trades today",  acct.get("trades_today", 0))

    # ── PnL history chart ──────────────────────────────────────────────────
    st.subheader("Realised PnL — last 30 days")
    hist, hist_err = _fetch(f"/api/pnl/history?days=30&account_id={_DEMO_ACCOUNT_ID}")
    if hist_err:
        st.info(f"PnL history unavailable: {hist_err}")
    elif not hist:
        st.caption("No closed demo trades yet.")
    else:
        df_hist = pd.DataFrame(hist)
        if "date" in df_hist.columns and "pnl" in df_hist.columns:
            df_hist["cumulative"] = df_hist["pnl"].cumsum()
            fig = go.Figure()
            fig.add_bar(x=df_hist["date"], y=df_hist["pnl"], name="Daily PnL",
                        marker_color=[_TV_GREEN if v >= 0 else _TV_RED for v in df_hist["pnl"]])
            fig.add_scatter(x=df_hist["date"], y=df_hist["cumulative"],
                            name="Cumulative", line={"color": _TV_EMA20, "width": 2})
            fig.update_layout(
                paper_bgcolor=_TV_BG, plot_bgcolor=_TV_GRID,
                font={"color": _TV_TEXT}, height=260,
                legend={"orientation": "h", "y": 1.1},
                margin={"l": 40, "r": 10, "t": 10, "b": 40},
            )
            st.plotly_chart(fig, use_container_width=True, config=_CHART_CONFIG)

    # ── Open positions ─────────────────────────────────────────────────────
    st.subheader("Open Positions")
    pos_all, pos_err = _fetch("/api/bot/positions")
    if pos_err:
        st.warning(pos_err)
    else:
        demo_pos = [p for p in (pos_all or []) if p.get("account") == _DEMO_ACCOUNT_ID]
        if not demo_pos:
            st.caption("No open demo positions.")
        else:
            st.dataframe(pd.DataFrame(demo_pos), hide_index=True, use_container_width=True)

    # ── Closed trades ──────────────────────────────────────────────────────
    st.subheader(f"Closed Trades (last {DEFAULT_LIMIT})")
    trades, trades_err = _fetch(
        f"/api/bot/trades/closed?limit={DEFAULT_LIMIT}&account_id={_DEMO_ACCOUNT_ID}"
    )
    if trades_err:
        st.warning(trades_err)
    elif not trades:
        st.caption("No closed demo trades.")
    else:
        df_t = pd.DataFrame(trades)
        cols = [c for c in ["openedAt", "closedAt", "symbol", "side", "pattern",
                             "qty", "entryPrice", "exitPrice",
                             "realizedPnl", "realizedPnlPct", "closeReason"] if c in df_t.columns]
        st.dataframe(df_t[cols] if cols else df_t, hide_index=True, use_container_width=True)

        # Per-strategy summary
        if "pattern" in df_t.columns and "realizedPnl" in df_t.columns:
            st.subheader("Strategy Breakdown")
            grp = (
                df_t.groupby("pattern", dropna=False)
                .agg(trades=("realizedPnl", "count"),
                     total_pnl=("realizedPnl", "sum"),
                     win_rate=("realizedPnl", lambda x: round((x > 0).mean() * 100, 1)))
                .reset_index()
                .sort_values("total_pnl", ascending=False)
            )
            grp.columns = ["Strategy", "Trades", "Total PnL ($)", "Win Rate (%)"]
            st.dataframe(grp, hide_index=True, use_container_width=True)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    page = render_sidebar()
    stats, stats_err = _fetch("/api/bot/stats")

    dispatch = {
        "Overview":      lambda: page_overview(stats, stats_err),
        "Performance":   page_performance,
        "Accounts":      page_accounts,
        "Positions":     page_positions,
        "Signals":       page_signals,
        "Closed Trades": page_trades,
        "Models":        page_models,
        "Promotion":     page_promotion,
        "Backtesting":   page_backtesting,
        "Strategies":    page_strategies,
        "Data Explorer": page_data_explorer,
        "Health":        page_health,
        "Logs":          page_logs,
        "Demo":          page_demo,
    }
    dispatch.get(page, page_overview)()

    time.sleep(POLL_INTERVAL_S)
    st.rerun()


if __name__ == "__main__":
    main()
