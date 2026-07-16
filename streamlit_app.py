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
import uuid
from typing import Any, Optional
from urllib.parse import quote, urlencode

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
import streamlit.components.v1 as components
# NOTE: yfinance is imported LAZILY inside `_fetch_candles_yf` — it pulls in a
# heavy dependency tree (curl_cffi, lxml, websockets, …) that adds ~50–100 MB to
# the process baseline, and it's only ever needed when the bot's /candles feed
# is unavailable (the fallback path). Not importing it at module load keeps the
# Streamlit Community Cloud memory footprint down (the "over resource limits"
# guard). See BL-20260710-DASH-MEMORY.

try:
    from streamlit_autorefresh import st_autorefresh
    _AUTOREFRESH_AVAILABLE = True
except ImportError:
    _AUTOREFRESH_AVAILABLE = False

BOT_API = os.environ.get("BOT_API_URL", "http://141.145.193.91:8001")
TIMEOUT_S = 10.0
# Live cadence AND the fetch-cache TTL (they are deliberately the SAME value —
# see below). A click on any control (segment toggle, time window, chart symbol,
# interval) reruns the surrounding fragment; that rerun must feel INSTANT, so it
# has to hit the fetch cache instead of re-paying ~30 blocking HTTP round-trips.
# Keeping the cache TTL == the auto-refresh cadence guarantees the cache stays
# warm for the whole window BETWEEN scheduled refreshes — so interaction reruns
# in that window are pure cache hits (instant), while the timer itself is the
# only thing that pays for a fresh fetch. A gentler 30s cadence (was 10s) also
# stops the timer from firing mid-tap and swallowing the interaction, which on
# mobile was the "I click, nothing happens until I hit Refresh" bug. Switching
# to a not-yet-fetched chart symbol still pays ONE cold candle fetch (a couple
# of seconds) — expected — but no longer re-pays the whole page's fetch storm.
POLL_INTERVAL_S = 30
DEFAULT_LIMIT = 50

# Fragment-based refresh (2026-07-05). Live regions re-render IN PLACE via
# `st.fragment(run_every=…)` partial reruns — the rest of the page (scroll
# position, whatever you're reading) stays put. The old model — a global
# streamlit-autorefresh full-script rerun every POLL_INTERVAL_S — remounted the
# entire page (charts included) every 10s, which reset your reading position
# mid-scroll. The autorefresh component is KEPT but demoted to a slow heartbeat:
# it still provides the fresh-browser-load pulse main() uses to reset nav to
# Overview, plus a safety-net full refresh for long-idle tabs.
HEARTBEAT_S = 300           # slow full-page safety refresh + fresh-load detector
STALE_OK_S = 120            # serve last-good payload this long on transient fetch errors
_FRAGMENT_OK = hasattr(st, "fragment")  # graceful degradation on old Streamlit

# Config lookup: Streamlit Cloud surfaces Secrets via st.secrets (not
# os.environ), so read both (e.g. DASHBOARD_API_TOKEN for the prop POST).
def _cfg(key: str, default: str = "") -> str:
    try:
        if key in st.secrets:
            return str(st.secrets[key])
    except Exception:  # no secrets.toml (local dev) — fall through to env
        pass
    return os.environ.get(key, default)


# Single production app (tracks `main`) — "Live data" auto-polls by default.
_DEFAULT_LIVE = True

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
_TV_ENTRY  = "#3d7aed"
_TV_FVG    = "#9c6ade"   # fair-value-gap zone band
_TV_SWEEP  = "#e0a030"   # liquidity-sweep level

# Categorical palette for per-symbol stacked charts (P&L-by-asset-class → per
# symbol). Distinct, reasonably colour-blind-tolerant hues; cycles if exhausted.
_CATEGORICAL = [
    "#4c9be8", "#26a69a", "#f5a623", "#ef5350", "#ab47bc", "#66bb6a",
    "#ffca28", "#26c6da", "#ec407a", "#8d6e63", "#7e57c2", "#9ccc65",
]

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
  /* Segmented controls (segment / window / Organize-by) — keep the button row
     on ONE line; never wrap to a second row (scroll horizontally if truly too
     narrow). The mobile rule below also tightens padding + font so the five
     Organize-by options fit a phone width without scrolling. */
  [data-testid="stSegmentedControl"] [role="radiogroup"],
  [data-testid="stSegmentedControl"] > div {
      flex-wrap: nowrap !important;
      overflow-x: auto !important;
  }
  [data-testid="stSegmentedControl"] button { white-space: nowrap !important; }
  @media (max-width: 640px) {
      [data-testid="column"] { min-width: 100% !important; }
      [data-testid="stSegmentedControl"] button {
          padding-left: 0.45rem !important; padding-right: 0.45rem !important;
          font-size: 0.78rem !important;
      }
  }
</style>
""")


# ── Data fetching ──────────────────────────────────────────────────────────────

@st.cache_resource(show_spinner=False)
def _last_good_store() -> dict:
    """Process-wide last-good payload per path.

    Module globals don't survive Streamlit's per-rerun script re-execution, so
    the stale-fallback store lives behind cache_resource (persists across
    reruns AND sessions — fine: the upstream data is the same for every
    viewer). Values are ``(payload, fetched_at_epoch)``."""
    return {}


@st.cache_data(ttl=POLL_INTERVAL_S, show_spinner=False, max_entries=256)
def _fetch_cached(path: str) -> tuple[Any, str | None]:
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


def _fetch(path: str) -> tuple[Any, str | None]:
    """Cached GET with a short stale-data fallback.

    On a TRANSIENT upstream failure (timeout / blip mid-refresh) serve the
    last good payload for up to STALE_OK_S instead of flashing an empty
    section + warning banner for one poll cycle — that flash was most of the
    "not everything is showing up" perception. A sustained outage (> STALE_OK_S)
    still surfaces the real error banner."""
    data, err = _fetch_cached(path)
    store = _last_good_store()
    if err is None:
        store[path] = (data, time.time())
        return data, None
    stale = store.get(path)
    if stale is not None:
        payload, fetched_at = stale
        if time.time() - fetched_at <= STALE_OK_S:
            return payload, None
    return None, err


def _live_fragment(render, *, every: float | None = None) -> None:
    """Run ``render()`` inside a PARTIAL-RERUN fragment.

    ``every`` set (and the Live-data toggle on) → the fragment re-renders
    itself on that cadence WITHOUT re-running the rest of the script — the
    sidebar, the section chrome, and every other open card stay untouched, so
    scroll position and reading flow survive a data refresh. ``every=None`` →
    no auto-refresh, but interactions INSIDE the region (selectboxes, window
    pickers, …) still rerun only this fragment, which makes heavy pages feel
    snappier. Falls back to a plain call on Streamlit < 1.37 (no fragments).

    NOTE: ``st.rerun()`` inside a fragment defaults to app scope, so `_goto`
    navigation jumps from within a fragment still work unchanged."""
    if not _FRAGMENT_OK:
        render()
        return
    live = bool(st.session_state.get("live_data", _DEFAULT_LIVE))
    run_every = every if (every and live) else None

    @st.fragment(run_every=run_every)
    def _region(_render=render):
        _render()

    _region()


# Per-page auto-refresh cadence (seconds) for the detail pages.
#
# EVENT-DRIVEN model (2026-07-10, BL-20260710-DASH-MEMORY): the per-page timer
# auto-refresh is DISABLED. The old ``run_every`` fragments re-ran the whole
# view (~30 blocking fetches + every chart rebuilt) on a wall-clock timer for
# every open session, forever — which (a) pushed the Streamlit Community Cloud
# app over its ~1 GB memory cap ("your app has gone over its resource limits")
# and (b) raced user taps (the timer-triggered rerun fought the interaction, so
# a control change needed a manual Refresh to stick). Now EVERY page (incl.
# Overview) updates on interaction / navigation / the sidebar ↻ Refresh button /
# the slow HEARTBEAT_S (300 s) safety rerun only — no per-page timer. Interaction
# reruns are still fragment-scoped (see ``_live_fragment(every=None)``), so a tap
# reruns only its region and the page around it stays put. Leave this map empty;
# add a page back ONLY if a genuine live-ticking need outweighs the memory cost.
_PAGE_REFRESH_S: dict[str, float] = {}


def _post(path: str, json_data: dict) -> tuple[Any, str | None]:
    """POST JSON to a bot API endpoint (NOT cached — it mutates).

    Sends the ``DASHBOARD_API_TOKEN`` bearer when one is configured (the bot
    gates the prop ingest on it). Returns ``(json_or_None, error_or_None)``.
    """
    url = f"{BOT_API}{path}"
    headers = {}
    token = _cfg("DASHBOARD_API_TOKEN").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        r = requests.post(url, json=json_data, headers=headers, timeout=TIMEOUT_S)
        r.raise_for_status()
        return r.json(), None
    except requests.HTTPError as e:
        detail = ""
        try:
            detail = f" — {e.response.json().get('detail', '')}"
        except Exception:  # noqa: BLE001
            pass
        return None, f"HTTP {e.response.status_code} on {path}{detail}"
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
        bot_df.attrs["candle_source"] = "bot"
        return bot_df, None
    # Bot feed unavailable → Yahoo Finance backup. Tag the frame so the chart
    # can surface a visible "backup data" badge instead of masking the degraded
    # pipeline silently. `.copy()` so we tag the returned frame, not the
    # st.cache_data-held object.
    yf_df, yf_err = _fetch_candles_yf(symbol, interval, limit)
    if yf_df is not None and not yf_df.empty:
        yf_df = yf_df.copy()
        yf_df.attrs["candle_source"] = "yfinance"
    return yf_df, yf_err


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


@st.cache_data(ttl=30, show_spinner=False, max_entries=16)
def _fetch_candles_yf(
    symbol: str, interval: str, limit: int = 200
) -> tuple[pd.DataFrame | None, str | None]:
    try:
        import yfinance as yf  # lazy — heavy dep tree, only the fallback needs it
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

# ── Information architecture: 6 sections, each a landing of summary cards that
# drill into the existing detail page (2026-06-22 redesign). Principle:
# overview first, details one click away. Overview is special — its landing IS
# the exec summary + live monitor (no card grid). Every other section renders a
# card per sub-page; clicking a card opens that page's existing render fn.
SECTIONS: dict[str, list[str]] = {
    "Overview": [],  # special-cased: renders page_overview directly
    "Performance": ["Performance", "Insights", "Reports"],
    "Strategies & Models": ["Strategies", "Models", "GPU Spend", "Exit Ladder", "Backtesting", "Promotion", "News"],
    "Accounts": ["Accounts", "Prop"],
    "Activity": ["Positions", "Trades", "Order Packages", "Signals"],
    "Roadmap": [],  # special-cased: renders page_roadmap directly (like Overview)
    "Learning": [],  # special-cased: renders page_learning directly (like Roadmap)
    "Admin": ["Data Explorer", "Logs", "Health"],
}
SECTION_NAMES = list(SECTIONS.keys())

# One-line "what's in here" blurb per sub-page, shown on the section-landing card.
PAGE_DESC: dict[str, str] = {
    "Performance": "Analytics deep-dive: equity curve, win-rate, expectancy, per-strategy + per-symbol.",
    "Insights": "AI-analyst narrative + grade for the book and each strategy.",
    "Reports": "Consolidated /system-report executive reports (health + trading + ML).",
    "Strategies": "Live-runtime per-strategy status, routing, P&L curve, review packet.",
    "Models": "ML fleet — per-model stage, training metric, drift.",
    "GPU Spend": "M19 Tier-1 spot-GPU training cost — per-session + monthly total vs the $10 cap.",
    "Exit Ladder": "ExitPlan laddered-vs-single-target soak (observe-only).",
    "Backtesting": "Trainer-VM sweeps + on-demand /test runs.",
    "Promotion": "Shadow-model promotion-readiness tracker.",
    "News": "M9 news-layer decisions (veto / boost / reduce) per actionable signal.",
    "Accounts": "Per-account balance, realised/unrealised P&L, trade log.",
    "Prop": "Breakout rule-distance cushion, report-back, journal.",
    "Positions": "Open positions — full detail cards (entry/SL/TP/uPnL + decision).",
    "Trades": "Closed-trade history (real / paper / all).",
    "Order Packages": "Decision-level table with model scores + Claude grade.",
    "Signals": "Recent ICT detections.",
    "Data Explorer": "Read-only browse of the federated canonical store.",
    "Logs": "Merged pipeline + outcome log feed.",
    "Health": "VM / service health + last-tick + snapshot checks.",
}


def _section_for(page: str) -> str:
    """Return the section that owns a sub-page (default Overview)."""
    for sec, subs in SECTIONS.items():
        if page in subs:
            return sec
    return "Overview"



# ── Cross-page navigation + queued widget presets ─────────────────────────────
#
# Streamlit forbids mutating a widget's session_state value AFTER the widget has
# been instantiated on the current run ("cannot modify a widget's value after it
# is instantiated"). To let one page programmatically jump to another AND preset
# the target page's segment/window control, we QUEUE the desired value and apply
# it on the NEXT run, BEFORE the target widget is created. `_apply_pending_widget`
# is called at the very start of each widget's render path; `_queue_widget`
# stages a value; `_goto` queues the nav page (plus any presets) and reruns.

def _queue_widget(key: str, value) -> None:
    """Stage `value` for widget `key`, applied on the next run before the widget
    is instantiated (see `_apply_pending_widget`)."""
    st.session_state.setdefault("_pending_widgets", {})[key] = value


def _apply_pending_widget(key: str) -> None:
    """If a value was queued for `key`, write it into session_state now. Must be
    called BEFORE the widget with that key is created, or Streamlit raises."""
    pend = st.session_state.get("_pending_widgets")
    if pend and key in pend:
        st.session_state[key] = pend.pop(key)


def _nav_key() -> str:
    """Per-SESSION key for the section-nav radio.

    A brand-new key each browser session means Streamlit has no browser-cached
    widget value to RESTORE onto a fresh load — so a refresh always falls back
    to the Overview default instead of reopening the last-viewed section (the
    behaviour merely setting ``session_state`` before the widget could NOT fix,
    because the restored value won that reconciliation). Stable within a session
    (the nonce is stored in ``session_state``), so in-session navigation — incl.
    ``_goto`` jumps and the ``?report=`` deeplink — still persists across reruns.
    """
    nonce = st.session_state.get("_nav_nonce")
    if not nonce:
        nonce = uuid.uuid4().hex[:8]
        st.session_state["_nav_nonce"] = nonce
    return f"nav_section_{nonce}"


def _goto(page: str, **preset) -> None:
    """Jump to `page`'s section and EXPAND its card in place.

    Resolves the owning section, queues it onto the section radio, adds the page
    to the expanded set (the section landing renders open cards inline — stacked
    expand/collapse, not a separate page), applies any target-page widget
    presets, then reruns. `preset` maps {widget_key: value} (segment/window
    controls store their DISPLAY label)."""
    for k, v in preset.items():
        _queue_widget(k, v)
    _queue_widget(_nav_key(), _section_for(page))
    st.session_state.setdefault("expanded_pages", set()).add(page)
    st.rerun()


def _consume_report_deeplink() -> None:
    """Open a specific report when the URL carries ``?report=<id>``.

    The Telegram system-report ping links to
    ``<dashboard>/?report=RPT-…`` so tapping it lands directly on the
    Reports card with that report rendered (the user can then Download
    the HTML from there). Runs ONCE per session per id (guarded by
    ``_deeplink_consumed``) so it deep-links on first load but never
    fights the user's later navigation. The query param is then STRIPPED
    from the URL (a plain refresh right after the tap still shows the
    report — Streamlit resumes the same session, and `_deeplink_consumed`
    already short-circuits a re-navigation within it) so a later, separate
    reload of the page (new session) lands on Overview per the normal
    fresh-load default instead of reopening this report forever (the param
    otherwise never goes away on its own — this was BL-20260702-REPORT-STICKY)."""
    try:
        rid = st.query_params.get("report")
    except Exception:
        return
    if not rid:
        return
    if st.session_state.get("_deeplink_consumed") == rid:
        return
    st.session_state["_deeplink_consumed"] = rid
    st.session_state["_deep_report_id"] = rid
    # Navigate to the Reports card (its owning section), opened in place,
    # with the window unfiltered so the target id is present in the list.
    _queue_widget(_nav_key(), _section_for("Reports"))
    _queue_widget("reports_window", "All")
    st.session_state.setdefault("expanded_pages", set()).add("Reports")
    try:
        del st.query_params["report"]
    except Exception:
        pass


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


# ── Redesign: shared header-band + progress widgets ───────────────────────────
# The whole app follows one page grammar: a header band of headline KPIs at the
# top (real-money PRIMARY as big metrics, paper SECONDARY as a labeled caption —
# never blended, per the canonical P4 contract), then live-now content, then a
# progress-vs-standard lens where relevant, then drill-down. These two helpers
# implement the first and third of those so every page reads consistently and a
# page never renders as "dead" when only paper is active.

def _render_header_band(
    real: list[tuple],
    paper: list[tuple] | None = None,
    *,
    status: tuple[str, str] | None = None,
) -> None:
    """One consistent headline band for any page.

    `real` / `paper` are lists of ``(label, value_str)`` or
    ``(label, value_str, delta)``. Real-money KPIs render big (``st.metric``);
    paper rides directly below as a single 🧪-tagged caption so it's always
    visible but visually secondary. `status` is an optional ``(text, color)``
    status dot rendered above the metrics."""
    if status:
        text, color = status
        st.markdown(_status_dot(color) + f"**{text}**", unsafe_allow_html=True)
    if real:
        cols = st.columns(len(real))
        for col, item in zip(cols, real):
            label, value = item[0], item[1]
            delta = item[2] if len(item) > 2 else None
            col.metric(label, value, delta=delta)
    if paper:
        bits = " · ".join(f"{it[0]} {it[1]}" for it in paper)
        st.caption("🧪 Paper · " + bits)


def _progress_dot(ratio: float) -> str:
    """🟢/🟡/🔴 for a 0..1 progress-toward-standard ratio."""
    if ratio >= 1.0:
        return "🟢"
    if ratio >= 0.5:
        return "🟡"
    return "🔴"


def _standard_progress(
    label: str,
    current: float | None,
    threshold: float | None,
    *,
    fmt=None,
) -> None:
    """Render a 'progress toward the system standard' bar.

    `current` vs the codified-gate `threshold` (e.g. 9 of 14 soak-days, 142 of
    200 trades). Renders a labeled `st.progress` bar with a 🟢/🟡/🔴 dot. Null
    current/threshold renders an em-dash caption rather than a fake 0."""
    f = fmt or (lambda v: f"{v:g}")
    if current is None or not threshold:
        st.caption(f"{label}: —")
        return
    ratio = max(0.0, min(1.0, current / threshold))
    st.progress(ratio, text=f"{_progress_dot(ratio)} {label}: {f(current)} / {f(threshold)}")


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

        def _status_block() -> None:
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

        # Own fragment so the status dot + clock stay live without the page
        # around them re-rendering (calling a fragment inside the sidebar
        # context renders it there).
        _live_fragment(_status_block, every=30)
        st.divider()

        # Keyed section nav so other pages can jump programmatically via `_goto`
        # (which queues the nav value + expands the target card + reruns). The
        # key is PER-SESSION (`_nav_key`) so a browser refresh can't restore the
        # last-viewed section — a fresh load gets a fresh key with no cached
        # value and falls back to the Overview default. Apply any queued section
        # BEFORE the radio is instantiated; seed the default so the choice
        # persists across in-session reruns. Don't pass `index=` once keyed.
        nav_key = _nav_key()
        _apply_pending_widget(nav_key)
        st.session_state.setdefault(nav_key, SECTION_NAMES[0])
        section = st.radio(
            "nav", SECTION_NAMES,
            label_visibility="collapsed",
            key=nav_key,
        )
        st.divider()
        # Data updates on interaction / navigation / ↻ Refresh. "Live data" ON
        # additionally keeps a slow background safety refresh (every 5 min) so a
        # long-idle tab can't drift stale; OFF stops even that. There is no
        # fast wall-clock auto-poll any more — it was pushing the app over its
        # memory cap and racing taps (BL-20260710-DASH-MEMORY).
        live = st.toggle(
            "Background refresh", value=_DEFAULT_LIVE, key="live_data",
            help="On: a slow safety refresh every 5 min keeps an idle tab from "
                 "drifting stale. Data always updates the instant you tap a "
                 "control, navigate, or hit ↻ Refresh — regardless of this toggle.",
        )
        if live:
            st.caption("\U0001f7e2 Updates on tap · slow 5-min safety refresh")
        else:
            st.caption("⏸ Updates on tap / navigation / ↻ Refresh only")
        if st.button("↻ Refresh now", use_container_width=True, key="refresh_now"):
            _fetch_cached.clear()
        # Deploy marker — bump on each release so a stale Streamlit Cloud
        # instance is obvious at a glance. If this date is old, the app
        # needs a reboot/redeploy.
        st.caption("build 2026-07-10b · event-driven refresh (lower memory)")

    return section  # type: ignore[return-value]


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


def _lc_position_markers(
    positions: list[dict] | None,
    symbol:    str,
) -> list[dict]:
    """Time-anchored ENTRY markers for OPEN positions on *symbol*.

    `_lc_price_lines` already draws the open position's entry as a *horizontal*
    price line, but that says nothing about WHEN the trade was entered. This
    adds a marker on the time axis at ``openedAt`` (price = ``entryPrice``) so a
    live trade's entry point is visible on the chart — green up for a long, red
    down for a short. Skipped silently when openedAt/entry is missing.
    """
    markers: list[dict] = []
    for p in positions or []:
        if p.get("symbol") and p.get("symbol") != symbol:
            continue
        # A working (placed, unfilled) order has no entry fill — skip its ENTRY
        # marker; it renders only as a dashed LIMIT price line (see _lc_price_lines).
        if p.get("_working"):
            continue
        ts = pd.to_datetime(p.get("openedAt"), errors="coerce", utc=True)
        if pd.isna(ts):
            continue
        is_long = str(p.get("side", "")).lower() in ("buy", "long")
        markers.append({
            "time":     int(ts.timestamp()),
            "position": "belowBar" if is_long else "aboveBar",
            "color":    _TV_ENTRY,
            "shape":    "arrowUp" if is_long else "arrowDown",
            "text":     "ENTRY",
        })
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
        if p.get("_working"):
            # Working (placed, unfilled) order — a dashed AMBER limit line + its
            # would-be SL/TP, visually distinct from a live position (there's no
            # position yet). Labelled "limit" so it never reads as an entry.
            _wc = "#f5a623"
            if entry is not None:
                lines.append({
                    "price": float(entry), "color": _wc, "lineWidth": 1,
                    "lineStyle": 2, "axisLabelVisible": True,
                    "title": f"{side or 'LIMIT'} limit (working)",
                })
            if sl is not None:
                lines.append({
                    "price": float(sl), "color": _wc, "lineWidth": 1,
                    "lineStyle": 3, "axisLabelVisible": True, "title": "SL (working)",
                })
            if tp is not None:
                lines.append({
                    "price": float(tp), "color": _wc, "lineWidth": 1,
                    "lineStyle": 3, "axisLabelVisible": True, "title": "TP (working)",
                })
            continue
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
    // Live-position ENTRY markers ride the 'Live' toggle (with the entry/SL/TP
    // price-lines) so a live trade's entry point on the time axis shows by
    // default alongside its horizontal entry line.
    if (pref('live', true)) m = m.concat(D.positionMarkers || []);
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
    storage_key: str | None = None,
) -> None:
    """Render the live chart via the custom lightweight-charts v4 embed.

    All series + overlays are sent to the component; the on-canvas checkboxes
    (Live / Signals / Closed / Zones / EMA / Volume) toggle them client-side
    (persisted in localStorage), and the ⤢ button requests fullscreen.

    `storage_key` overrides the per-symbol localStorage namespace. Pass a
    unique value when embedding several charts for the SAME symbol on one page
    (e.g. one inside each open-trade detail card) so their scroll position and
    overlay toggles don't clobber each other or the top-of-page symbol chart."""
    candle_data = _lc_candle_data(df)
    if not candle_data:
        st.caption("No candle data.")
        return
    # Backup-data indicator: when the bot's candle feed was unavailable and the
    # chart is drawn from the Yahoo Finance fallback, say so loudly instead of
    # passing off delayed/approximate backup data as the live bot feed.
    if df is not None and getattr(df, "attrs", {}).get("candle_source") == "yfinance":
        st.warning(
            "⚠️ Backup feed — Yahoo Finance. The bot's candle pipeline was "
            "unavailable, so these prices are delayed/approximate."
        )
    payload = {
        "candles": candle_data,
        "volume": _lc_volume_data(df),
        "ema": _lc_ema_data(df, ema_period),
        "signalMarkers": _lc_markers(signals, None, symbol),
        "tradeMarkers": _lc_markers(None, trades, symbol),
        "positionMarkers": _lc_position_markers(positions, symbol),
        "priceLines": _lc_price_lines(positions, df, symbol),
        "zoneLines": _lc_zone_lines(signals, symbol),
        # Namespace the chart's localStorage (scroll range + overlay toggles)
        # per symbol so the Overview's stacked per-symbol charts persist
        # independently instead of sharing one global key.
        "storageKey": storage_key or ("tvc_" + re.sub(r"[^A-Za-z0-9]", "", symbol)),
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


def _position_upnl(p: dict) -> float:
    """Unrealised PnL for a position — straight from the bot API.

    `/api/bot/positions` returns a **multiplier-aware** `unrealizedPnl`:
    broker-truth when the integration provides it
    (`unrealizedPnlSource="broker"`), else a server-side mark-to-market
    fallback computed with `contract_value_usd`
    (`unrealizedPnlSource="markprice_local"`) — see the ict-trading-bot
    PnL-resolution contract (2026-06-16, #3761). Both are correct, so the
    dashboard simply trusts the value.

    The old client-side `(last_price - entry) * qty` recompute was dropped
    (BL-20260616-DASH-UPNL-MULTIPLIER): it was **multiplier-blind**, so a
    futures move (MES/MGC/MHG `contract_value_usd` ≠ 1) rounded to ≈ $0 —
    wrong, and now redundant since the API returns the correct figure.

    Returns `0.0` when the API value is absent (`unavailable` — e.g. an
    IBKR-paper symbol while the gateway is offline); use :func:`_open_upnl`
    where the known/unknown distinction matters (em-dash vs a real $0.00).
    """
    raw = p.get("unrealizedPnl")
    if raw is not None:
        try:
            return float(raw)
        except (TypeError, ValueError):
            pass
    return 0.0


def _open_upnl(p: dict) -> tuple[float, bool]:
    """Like :func:`_position_upnl` but also returns whether the value is
    actually KNOWN, so the detail card can show "—" instead of a misleading
    $0.00 when the API value is "unavailable" (e.g. an IBKR-paper symbol while
    the gateway is offline — broker read failed AND no mark price).

    A leg is treated as UNKNOWN when ``unrealizedPnl`` is null OR the bot
    flags ``unrealizedPnlSource == "unavailable"`` (broker read failed and no
    mark price) — those legs must NOT be summed as $0 into an exposure total.
    """
    raw = p.get("unrealizedPnl")
    src = str(p.get("unrealizedPnlSource") or "").lower()
    if raw is not None and src != "unavailable":
        try:
            return float(raw), True
        except (TypeError, ValueError):
            pass
    return 0.0, False


def _sum_upnl(positions) -> tuple[float, int]:
    """Sum the KNOWN unrealised PnL across positions and count the UNKNOWN legs.

    Returns ``(total_of_known, n_unknown)``. Unknown legs (null uPnL or
    ``unrealizedPnlSource == "unavailable"``) are **excluded** from the sum
    rather than counted as $0 — summing unknowns as zero silently understates
    exposure and is the canonical "missing ≠ 0" trust bug.
    """
    total = 0.0
    n_unknown = 0
    for p in positions or []:
        val, known = _open_upnl(p)
        if known:
            total += val
        else:
            n_unknown += 1
    return total, n_unknown


def _upnl_metric(total: float, n_known: int, n_unknown: int) -> str:
    """Format an aggregate uPnL metric value: "—" when nothing is known, else
    the known sum. Caller appends an "+N unmeasured" caption when n_unknown>0."""
    if n_known == 0:
        return "—"
    return fmt_usd(total)


def _upnl_caption(n_unknown: int) -> str | None:
    """A "+N positions with unmeasured uPnL" caption, or None when all known."""
    if n_unknown <= 0:
        return None
    return (f"+{n_unknown} position{'s' if n_unknown != 1 else ''} with "
            "unmeasured uPnL (excluded from the sum)")


# ── Live prop trades (manual-bridge, no broker feed) ────────────────────────────
#
# A prop account (e.g. Breakout) has no broker API — the bot only *emits* a
# ticket and learns the fill/close from an operator report-back (see the Prop
# tab). So a LIVE prop trade is an OUTBOUND ticket whose lifecycle status reads
# ``filled`` (``emitted → filled → closed``). We shape those tickets into
# position-like rows (``accountClass="prop"``) so the SAME live-trades monitor
# machinery — per-symbol charts with entry/SL/TP lines, the detail card, the
# organize/focus layer — renders them next to real/paper legs. Prop is a THIRD
# funding class and is **never** blended into a real-money or paper P&L sum: the
# monitor keeps a separate "Prop PnL" metric for it (mirroring the exec-summary
# and header-band split that already exist elsewhere in this file).
#
# Because there is no broker feed, prop uPnL can't be broker-truth — it's a
# dashboard **mark-price estimate** (last candle close vs the ticket entry ×
# qty × side), tagged with its own ``unrealizedPnlSource`` so the card labels it
# honestly. The estimate assumes a 1:1 contract value (correct for the crypto/FX
# symbols the prop account trades; a futures multiplier ≠ 1 would need the bot's
# ``contract_value_usd``, which the dashboard doesn't have — noted in the UI).
_PROP_UPNL_SOURCE = "prop_estimate"


def _prop_accounts() -> list[str]:
    """Prop-firm account ids from ``/api/bot/config`` (``account_class == 'prop'``).

    Falls back to the canonical ``breakout_1`` when config is unavailable so the
    monitor still finds the live prop account on a bot that predates the field."""
    cfg, _ = _fetch("/api/bot/config")
    ids: list[str] = []
    if isinstance(cfg, dict):
        for a in cfg.get("accounts") or []:
            if (isinstance(a, dict)
                    and str(a.get("account_class") or "").lower() == "prop"
                    and a.get("id")):
                ids.append(str(a["id"]))
    return ids or ["breakout_1"]


def _prop_ticket_to_position(t: dict, account_id: str) -> dict:
    """Shape one live prop ticket into a ``/api/bot/positions``-style row.

    Entry / SL / TP / qty are the LAST values the bot recorded on the ticket —
    static unless the monitor updates them, which the report-back loop reflects
    (the ticket is re-emitted / advanced), so this is always the current setup.
    ``_prop_ticket`` is kept so the card can surface the exact ticket message
    (the assistant's decision output) as the trade's reasoning."""
    direction = str(t.get("direction") or "").lower()
    side = ("buy" if direction in ("long", "buy")
            else "sell" if direction in ("short", "sell") else direction)
    return {
        "id": t.get("ticket_id") or t.get("order_package_id"),
        "account": account_id,
        "accountClass": "prop",
        "isDemo": False,
        "symbol": str(t.get("symbol") or "").upper(),
        "side": side,
        "qty": t.get("qty"),
        "entryPrice": t.get("entry"),
        "stopLoss": t.get("sl"),
        "takeProfit": t.get("tp"),
        "pattern": t.get("strategy"),
        "openedAt": t.get("signal_time") or t.get("created_at"),
        # uPnL is filled in from the mark price below (no broker feed).
        "unrealizedPnl": None,
        "unrealizedPnlSource": None,
        "_prop_ticket": t,
    }


def _apply_prop_upnl(p: dict, mark: float | None) -> None:
    """Fill a prop row's mark-price uPnL estimate in place.

    ``(mark − entry) × qty × side``. Marked ``unavailable`` (→ card shows "—",
    excluded from every sum) when the mark/entry/qty isn't known — never a fake
    $0. Source ``prop_estimate`` distinguishes it from broker/markprice_local."""
    entry, qty = p.get("entryPrice"), p.get("qty")
    if mark is None or entry is None or qty is None:
        p["unrealizedPnl"] = None
        p["unrealizedPnlSource"] = "unavailable"
        return
    try:
        sign = 1.0 if str(p.get("side") or "").lower() in ("buy", "long") else -1.0
        p["unrealizedPnl"] = (float(mark) - float(entry)) * float(qty) * sign
        p["unrealizedPnlSource"] = _PROP_UPNL_SOURCE
    except (TypeError, ValueError):
        p["unrealizedPnl"] = None
        p["unrealizedPnlSource"] = "unavailable"


def _prop_mark(symbol: str) -> float | None:
    """Last candle close for *symbol* — the mark for the prop uPnL estimate.

    Uses a fixed 15m interval (independent of the chart's interval selector) so
    it doesn't re-fetch when the operator changes the chart timeframe; the last
    close is ~identical across intervals anyway."""
    df, _ = _fetch_candles(symbol, "15m", limit=2)
    if df is None or df.empty:
        return None
    try:
        return float(df["close"].iloc[-1])
    except (KeyError, IndexError, ValueError, TypeError):
        return None


def _prop_rows_by_status(status: str) -> list[dict]:
    """Prop tickets at lifecycle ``status`` shaped into position-like rows.

    Returns ``[]`` on any error (prop endpoints not deployed yet, or none at
    that status) so callers degrade to exactly their prior behaviour."""
    rows: list[dict] = []
    for acct in _prop_accounts():
        payload, err = _fetch(
            f"/api/bot/prop/tickets?account_id={acct}&status={status}&limit=200")
        if err or not isinstance(payload, dict):
            continue
        for t in payload.get("tickets") or []:
            if str(t.get("status")) != status or not t.get("symbol"):
                continue
            rows.append(_prop_ticket_to_position(t, acct))
    return rows


def _prop_open_positions() -> list[dict]:
    """Live (FILLED) prop trades as position-like rows, with a mark-price uPnL
    estimate. A live prop trade = a ticket at lifecycle status ``filled`` (the
    limit tripped / market filled — a real open position)."""
    positions = _prop_rows_by_status("filled")
    # One mark per distinct symbol, applied to every leg on it.
    marks: dict[str, float | None] = {}
    for p in positions:
        sym = p.get("symbol")
        if sym not in marks:
            marks[sym] = _prop_mark(sym)
        _apply_prop_upnl(p, marks[sym])
    return positions


def _prop_working_orders() -> list[dict]:
    """WORKING (PLACED) prop orders — a limit/pending order placed on the terminal
    but NOT yet filled. These hold **no position and no P&L**, so they're kept
    apart from the live-trades P&L entirely: each row is tagged ``_working`` and
    carries no uPnL. Rendered as a separate "Working orders (awaiting fill)"
    section + a dashed LIMIT/SL/TP overlay on the symbol's chart."""
    rows = _prop_rows_by_status("placed")
    for r in rows:
        r["_working"] = True
        r["unrealizedPnl"] = None
        r["unrealizedPnlSource"] = None
    return rows


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
    """Parse a trade timestamp into a tz-naive UTC datetime.

    Handles BOTH an ISO-8601 string AND a bare **epoch number** — the
    reconciler-filled close path writes ``closed_at`` as a raw epoch-ms string
    that ``fromisoformat`` can't read, which silently dropped every
    reconciler-closed trade from the analytics frame (empty calendar / counts).
    A 10-digit value is epoch-seconds, longer is epoch-millis.
    """
    if not value:
        return None
    s = str(value).strip()
    # Bare epoch number (all digits) → epoch seconds/millis.
    if s.isdigit():
        try:
            n = int(s)
            ms = n if n >= 100_000_000_000 else n * 1000  # < 1e11 ⇒ seconds
            return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).replace(tzinfo=None)
        except (ValueError, OverflowError, OSError):
            return None
    try:
        d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if d.tzinfo is not None:
        d = d.astimezone(dt.timezone.utc).replace(tzinfo=None)
    return d


def _fmt_duration(start: Any, end: Any = None) -> str | None:
    """Human-readable elapsed time between two trade timestamps.

    For an OPEN trade pass only ``start`` (``openedAt``) — ``end`` defaults to
    "now" (tz-naive UTC, matching :func:`_parse_trade_ts`), so the result reads
    as "how long it has been live". For a CLOSED trade pass both ``openedAt``
    and ``closedAt`` to get the trade's lifetime. Returns ``None`` when the
    start can't be parsed or the span is negative (clock skew / bad data), so
    callers render an em-dash rather than a fabricated "0s".
    """
    s = _parse_trade_ts(start)
    if s is None:
        return None
    e = _parse_trade_ts(end) if end else dt.datetime.utcnow()
    if e is None:
        e = dt.datetime.utcnow()
    secs = int((e - s).total_seconds())
    if secs < 0:
        return None
    days, rem = divmod(secs, 86400)
    hours, rem = divmod(rem, 3600)
    mins, _ = divmod(rem, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {mins}m"
    if mins:
        return f"{mins}m"
    return f"{secs}s"


def _row_account_class(d: dict) -> str:
    """Normalize a row's funding category — ``real_money`` | ``paper`` | ``prop``.

    The bot dual-emits the new ``accountClass`` field alongside the legacy
    ``isDemo`` boolean. Prefer ``accountClass`` (which can be ``paper`` /
    ``prop`` / ``real_money``); fall back to ``isDemo`` (paper when truthy,
    else real_money) for rows from an older API that hasn't grown the field.

    NOTE: ``prop`` (prop-firm accounts) is its OWN category and is **never**
    real money — the bot keeps real / paper / prop strictly separate and so
    must the dashboard. Use :func:`_is_real_money` for the "counts toward the
    real-money headline" test rather than ``== "real_money"`` open-coded.
    """
    return str(d.get("accountClass") or ("paper" if d.get("isDemo") else "real_money")).lower()


# Funding categories that are NOT real money. ``prop`` (prop-firm accounts)
# rides alongside ``paper`` here: per the bot's canonical contract real /
# paper / prop are never blended into one number, so prop must be excluded
# from every real-money aggregate, header, and segment filter.
_NON_REAL_CLASSES = frozenset({"paper", "prop"})


def _is_real_money(d: dict) -> bool:
    """True only for genuine real-money rows — paper AND prop excluded."""
    return _row_account_class(d) not in _NON_REAL_CLASSES


def _portfolio_paper_ids() -> frozenset[str]:
    """Account ids of the live-portfolio-mirror PAPER books (``paper_role:
    portfolio``) read from ``/api/bot/config`` (S-PAPER-PORTFOLIO, 2026-07-16).

    These are the paper accounts that mirror the *actual* live-traded portfolio
    (``bybit_portfolio`` mirrors ``bybit_2``; ``alpaca_portfolio`` mirrors
    ``alpaca_live``) — the ones the "Paper" funding view scopes to, so the
    data-only SOAK books (which trade the full instrument roster for ML data)
    stay OFF every tab except the Accounts page.

    Data-driven off the bot's ``paper_role`` field — **never a hardcoded id
    list** — so a roster change needs no dashboard edit. Returns an **empty
    set** when the field is absent (a bot that predates it) OR the config read
    fails; callers treat empty as "fall back to ALL paper", so the paper view
    is never stranded pre-deploy — it just shows every paper account until the
    portfolio books are declared.
    """
    cfg, _err = _fetch("/api/bot/config")
    if not isinstance(cfg, dict):
        return frozenset()
    ids: set[str] = set()
    for a in cfg.get("accounts") or []:
        if not isinstance(a, dict):
            continue
        if (str(a.get("account_class") or "").lower() == "paper"
                and str(a.get("paper_role") or "").lower() == "portfolio"):
            aid = a.get("id") or a.get("account_id")
            if aid:
                ids.add(str(aid))
    return frozenset(ids)


def _row_is_portfolio_paper(d: dict) -> bool:
    """True for a paper row that belongs to a live-portfolio-mirror book.

    A row qualifies when it is paper-class AND (its account is in the declared
    portfolio set, OR no portfolio accounts are declared yet — the graceful
    all-paper fallback). Non-paper rows never qualify. Used to scope the
    "Paper" funding view to the portfolio, keeping soak books out of it.
    """
    if _row_account_class(d) != "paper":
        return False
    ids = _portfolio_paper_ids()
    if not ids:
        return True  # fallback: no portfolio books declared → treat all paper as portfolio
    acct = str(d.get("account") or d.get("account_id") or "")
    if not acct:
        # The row carries no per-account attribution (e.g. `/order-packages`
        # rows have no `account` field). We can't tell soak from portfolio, so
        # include it rather than blank the view — over-include beats dropping.
        return True
    return acct in ids


def _closed_trades_frame(trades: list[dict]) -> pd.DataFrame:
    """One row per closed trade — strategy, pnl, ts (UTC), outcome, accountClass, isDemo.

    ``realizedPnl`` is nullable on the wire (bot emits ``null`` for the
    reconciler-incomplete close shape, see ict-trading-bot #2759). Keep
    null as ``NaN`` so pandas aggregations skip those rows by default
    (``sum``/``mean`` with ``skipna=True``), and mark ``outcome='unknown'``
    so the wins/losses/breakeven counts don't fold null rows into
    "breakeven". 2026-06-04 reporting-cleanup follow-up.
    """
    import math

    cols = ["strategy", "pnl", "pnl_pct", "ts", "outcome", "accountClass", "isDemo", "account"]
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
        # Summed per-trade return % (realizedPnlPct) — powers the calendar's
        # per-day / monthly "%" figure (0.0 when the bot didn't record it).
        try:
            pnl_pct = float(t.get("realizedPnlPct") or 0.0)
        except (TypeError, ValueError):
            pnl_pct = 0.0
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
            "pnl_pct": pnl_pct,
            "ts": ts,
            "outcome": outcome,
            "accountClass": _row_account_class(t),
            "isDemo": bool(t.get("isDemo", False)),
            "account": str(t.get("account") or t.get("account_id") or ""),
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


# 2026-06-04 reporting-cleanup — paper/real-money segment helpers.
#
# Every reporting surface that mixes paper + real-money accounts now
# offers a "Real money / Paper / All" picker. The category axis is
# orthogonal to the technical live/dry EXECUTION mode. The bot dual-emits
# a per-row ``accountClass`` ("paper" | "real_money") alongside the legacy
# ``isDemo`` boolean (see ict-trading-bot PR #2759), so we fetch with
# ``?include_paper=true`` and filter client-side on ``accountClass`` (with
# an ``isDemo`` fallback). Default segment is **Real money** — operators
# see real-money activity by default and opt into paper explicitly.

_SEGMENT_CHOICES: list[str] = ["Real money", "Paper", "All"]
_SEGMENT_SLUG: dict[str, str] = {"Real money": "real", "Paper": "paper", "All": "all"}


def _segment_picker(key: str) -> str:
    """Render a Real money / Paper / All radio at the top of a reporting page.

    Returns ``"real"`` / ``"paper"`` / ``"all"`` so callers can pass it
    through to ``_segment_filter`` and to API ``include_paper`` params.
    """
    # Honor a queued cross-page preset before the radio is instantiated.
    _apply_pending_widget(key)
    label = st.radio(
        "Segment",
        _SEGMENT_CHOICES,
        index=0,  # Real money by default
        horizontal=True,
        key=key,
        help=(
            "Real money = genuine real-money accounts only (paper AND "
            "prop-firm accounts excluded — never blended into the real "
            "headline); Paper = paper-trading accounts "
            "(``account_class: paper``). All merges real + paper + prop."
        ),
    )
    return _SEGMENT_SLUG[label]


def _segment_filter_rows(rows: list[dict], segment: str) -> list[dict]:
    """Filter a list of row-dicts by segment using each row's category.

    Classifies via :func:`_row_account_class` — the new ``accountClass``
    field with an ``isDemo`` fallback. ``real`` keeps only genuine
    real-money rows (:func:`_is_real_money` — **prop excluded**, never
    blended into real); ``paper`` keeps paper-class rows; ``all`` keeps
    everything (real + paper + prop).
    """
    if segment == "all":
        return rows
    if segment == "paper":
        # "Paper" scopes to the live-portfolio-mirror books (`paper_role:
        # portfolio`); the data-only soak books stay off this view (they're
        # visible on the Accounts page only). Falls back to all-paper when no
        # portfolio books are declared. S-PAPER-PORTFOLIO 2026-07-16.
        return [r for r in (rows or []) if _row_is_portfolio_paper(r)]
    if segment == "prop":
        return [r for r in (rows or []) if _row_account_class(r) == "prop"]
    # real money: prop and paper both excluded
    return [r for r in (rows or []) if _is_real_money(r)]


def _segment_filter_frame(df: pd.DataFrame, segment: str) -> pd.DataFrame:
    """Same as :func:`_segment_filter_rows` for a pandas DataFrame with
    an ``accountClass`` column. ``real`` excludes both paper AND prop."""
    if segment == "all" or "accountClass" not in df.columns:
        return df
    classes = df["accountClass"].astype(str).str.lower()
    if segment == "paper":
        paper = df[classes == "paper"]
        # Scope "Paper" to the live-portfolio-mirror books; soak books drop out
        # (visible on the Accounts page only). Fall back to ALL paper when no
        # portfolio books are declared OR the frame lacks an `account` column.
        ids = _portfolio_paper_ids()
        if ids and "account" in paper.columns:
            accts = paper["account"].astype(str)
            paper = paper[accts.isin(ids)]
        return paper.reset_index(drop=True)
    if segment == "prop":
        return df[classes == "prop"].reset_index(drop=True)
    return df[~classes.isin(_NON_REAL_CLASSES)].reset_index(drop=True)


# ── Mobile-friendly control bar — segment + time-window pickers ─────────────────
#
# A compact, tap-friendly control bar that sits at the top of every reporting
# page. It pairs the existing Real/Paper/All segment axis with a time-window
# axis (24h / 7d / 30d / All) that maps to the bot's ``/performance?window=``
# values. Both prefer ``st.segmented_control`` (newer Streamlit, large tap
# targets) and gracefully fall back to ``st.radio(horizontal=True)`` on older
# builds — matching how the rest of the file feature-detects Streamlit APIs
# (see ``_df_row_selection_supported``).

# label → /performance window slug. "All" reaches the uncapped all-history
# aggregate. Order is the operator's natural escalation: recent → wider.
_WINDOW_CHOICES: list[str] = ["24h", "7d", "30d", "All"]
_WINDOW_SLUG: dict[str, str] = {"24h": "24h", "7d": "7d", "30d": "30d", "All": "all"}
# window slug → days, for the client-side closed-trade `since=` math. "All" uses
# a 10-year lookback (3650 days) rather than a special sentinel — the since-calc
# (utcnow() - timedelta(days=days)) handles it directly, reaching every trade
# this bot will ever produce without any branch in the date math.
_WINDOW_DAYS: dict[str, int] = {"24h": 1, "7d": 7, "30d": 30, "all": 3650}


def _segmented_or_radio(
    label: str, choices: list[str], *, index: int, key: str, help: str | None = None,
) -> str:
    """Render a single-select control as ``st.segmented_control`` when available
    (bigger tap targets, nicer on phones), else fall back to a horizontal radio.

    ``st.segmented_control`` (Streamlit ≥1.40) can transiently return ``None`` on
    a rerun — inside an auto-refreshing ``run_every`` fragment this snapped a
    window/segment pick back to the hardcoded default until a full page refresh
    committed it (the "change the timeframe, then hit refresh" bug). Two fixes:
    (a) a ``None`` return falls back to the COMMITTED value in ``session_state``
    (the user's actual pick), not ``choices[index]``; and (b) ``default=`` is
    only seeded on FIRST render (when the key isn't in ``session_state`` yet) —
    re-passing it every run alongside ``key`` can itself reset the selection.
    Streamlit Community Cloud may briefly run an older build than the pin during
    a rollout, so the radio fallback keeps the page importable."""
    # Honor any value queued by a cross-page jump (_goto / _queue_widget) BEFORE
    # the widget is created — the queued value is the DISPLAY label, not a slug.
    _apply_pending_widget(key)
    seg = getattr(st, "segmented_control", None)
    if callable(seg):
        try:
            kwargs: dict[str, Any] = {
                "key": key, "help": help, "selection_mode": "single"}
            # Seed the default ONLY on the first render; afterwards let
            # session_state[key] drive so a fragment rerun can't snap it back.
            if key not in st.session_state:
                kwargs["default"] = choices[index]
            picked = seg(label, choices, **kwargs)
            if picked is not None:
                return picked
            # Transient None → the last committed selection, never the default.
            committed = st.session_state.get(key)
            return committed if committed in choices else choices[index]
        except (TypeError, ValueError):
            pass  # older signature / build → radio fallback below
    return st.radio(label, choices, index=index, horizontal=True, key=key, help=help)


def _segment_control(key: str) -> str:
    """Mobile-friendly Real money / Paper / All picker → ``real``/``paper``/``all``.

    Same semantics + default (Real money) as :func:`_segment_picker`; this
    variant uses ``st.segmented_control`` for larger tap targets on phones."""
    label = _segmented_or_radio(
        "Segment", _SEGMENT_CHOICES, index=0, key=key,
        help=(
            "Real money = genuine real-money accounts only (paper AND prop-firm "
            "accounts excluded — never blended into the real headline); Paper = "
            "paper-trading accounts; All explicitly merges real + paper "
            "(profit factor / max drawdown can't be combined, shown as —)."
        ),
    )
    return _SEGMENT_SLUG[label]


def _window_control(key: str, *, index: int = 0) -> tuple[str, str]:
    """Mobile-friendly 24h / 7d / 30d / All time-window picker.

    Returns ``(label, slug)`` where ``slug`` ∈ {24h, 7d, 30d, all} drives the
    bot's ``/performance?window=`` param and the client-side ``since=`` math.
    Defaults to 24h (``index=0``)."""
    label = _segmented_or_radio(
        "Window", _WINDOW_CHOICES, index=index, key=key,
        help="Time window for the figures below — last 24 hours, 7 days, 30 "
             "days, or all-time.",
    )
    return label, _WINDOW_SLUG[label]


def _control_bar(seg_key: str, win_key: str, *, win_index: int = 0) -> tuple[str, str, str]:
    """Render the standard two-control mobile control bar (segment + window)
    side-by-side and return ``(segment, window_label, window_slug)``."""
    c1, c2 = st.columns(2)
    with c1:
        segment = _segment_control(seg_key)
    with c2:
        win_label, win_slug = _window_control(win_key, index=win_index)
    return segment, win_label, win_slug


# ── Funding-class control — Real money / Paper / Prop ───────────────────────────
#
# The Overview's ONE top-of-page toggle (operator ask 2026-07-10): the whole
# page reflects the single selected funding class. This is the three-way
# real/paper/prop axis (the bot keeps the three strictly separate and never
# blends them), REPLACING the old Real/Paper/All segment on the Overview — "All"
# is dropped in favour of the three concrete funding classes. Prop rides its own
# data paths (prop tickets/fills, mark-price estimate) since prop is not in the
# `/trades/closed` / `/performance` money DB.
_FUNDING_CHOICES: list[str] = ["Real money", "Paper", "Prop"]
_FUNDING_SLUG: dict[str, str] = {"Real money": "real", "Paper": "paper", "Prop": "prop"}
_FUNDING_SEG_WORD: dict[str, str] = {"real": "real", "paper": "paper", "prop": "prop"}
_FUNDING_SEG_NAME: dict[str, str] = {
    "real": "real money", "paper": "paper", "prop": "prop"}


def _funding_control(key: str) -> str:
    """Real money / Paper / Prop picker → ``real`` / ``paper`` / ``prop``."""
    # Coerce any stale / invalid stored value BEFORE the widget renders — else
    # Streamlit raises when session_state holds a label not in the option set.
    # Two real sources of that: (a) a returning user whose browser cached this
    # key as "All" back when it was a Real/Paper/All control, and (b) the shared
    # `_empty_segment_hint`, which can queue an "All" label. Apply any queued
    # value first, then drop it if it isn't one of the three funding choices.
    _apply_pending_widget(key)
    if st.session_state.get(key) not in _FUNDING_CHOICES:
        st.session_state.pop(key, None)
    label = _segmented_or_radio(
        "Funding", _FUNDING_CHOICES, index=0, key=key,
        help=("The one toggle that drives this whole tab. Real money = genuine "
              "real-money accounts; Paper = paper-trading accounts; Prop = "
              "prop-firm accounts (a mark-price estimate, no broker feed). The "
              "three are never blended into one number."),
    )
    return _FUNDING_SLUG.get(label, "real")


def _funding_bar(seg_key: str, win_key: str, *, win_index: int = 0) -> tuple[str, str, str]:
    """The Overview control bar: one Real/Paper/Prop funding toggle + the
    time window, side by side. Returns ``(segment, window_label, window_slug)``."""
    c1, c2 = st.columns(2)
    with c1:
        segment = _funding_control(seg_key)
    with c2:
        win_label, win_slug = _window_control(win_key, index=win_index)
    return segment, win_label, win_slug


# Slug → display label for the segment control (the segment widgets store the
# DISPLAY label, so a queued preset must be the label). Inverse of _SEGMENT_SLUG.
_SLUG_SEGMENT: dict[str, str] = {v: k for k, v in _SEGMENT_SLUG.items()}


def _empty_segment_hint(
    unfiltered_rows: list[dict],
    segment: str,
    *,
    seg_widget_key: str,
    window_widget_key: str | None = None,
    noun: str = "trades",
    window_label: str | None = None,
) -> None:
    """Smart empty state for a segment+window selection that yielded no rows.

    When the chosen segment is empty but data EXISTS in another segment (computed
    from the UNFILTERED rows the caller already has in hand), render an honest,
    helpful caption that names the available data and offers one-tap jumps to a
    segment that actually has rows — instead of a bare "No … trades".

    The jumps are EXPLICIT, user-initiated and labeled (never a silent real/paper
    blend): a "Show Paper (N) →" button queues the segment widget's DISPLAY label
    and reruns the SAME page. ``window_widget_key`` (optional) enables a
    "Widen to All-time →" jump when the window — not the segment — is the
    constraint. Only segments/windows that actually have rows get a button.

    Args are the row list BEFORE the segment filter, the current ``segment``
    slug, and the widget keys to drive. Reuses ``_segment_filter_rows``.
    """
    rows = unfiltered_rows or []
    real_n = len(_segment_filter_rows(rows, "real"))
    paper_n = len(_segment_filter_rows(rows, "paper"))
    all_n = len(rows)

    win_word = f" · {window_label} window" if window_label else ""
    seg_word = {"real": "real-money", "paper": "paper", "all": ""}.get(segment, segment)
    base = f"No {seg_word} {noun}".replace("  ", " ").strip()
    st.caption(f"{base}{win_word}.")

    # Offer a jump only to a segment that genuinely has rows in this window.
    buttons: list[tuple[str, str]] = []  # (label, target segment slug)
    if segment != "paper" and paper_n > 0:
        buttons.append((f"Show Paper ({paper_n}) →", "paper"))
    if segment != "real" and real_n > 0:
        buttons.append((f"Show Real money ({real_n}) →", "real"))
    if segment != "all" and all_n > 0 and all_n not in (real_n, paper_n):
        # "All" is only useful when it surfaces MORE than the single other
        # segment already offers (i.e. both classes have rows).
        buttons.append((f"Show All ({all_n}) →", "all"))

    # Widen-window jump: the segment has zero rows in THIS window but the caller
    # asked us to offer a wider window (it can't know without a second fetch, so
    # we only surface this when a window key is provided AND this window is
    # narrower than All — honest, since All-time is a strict superset).
    widen = (
        window_widget_key is not None
        and window_label not in (None, "All")
    )

    if not buttons and not widen:
        return

    cols = st.columns(len(buttons) + (1 if widen else 0))
    i = 0
    for label, target_slug in buttons:
        with cols[i]:
            if st.button(
                label, key=f"{seg_widget_key}__jump_{target_slug}",
                use_container_width=True,
            ):
                _queue_widget(seg_widget_key, _SLUG_SEGMENT[target_slug])
                st.rerun()
        i += 1
    if widen:
        with cols[i]:
            if st.button(
                "Widen to All-time →", key=f"{window_widget_key}__widen_all",
                use_container_width=True,
            ):
                # _WINDOW_CHOICES stores the display label; "All" is the slug
                # "all". Queue the label the window widget expects.
                _queue_widget(window_widget_key, "All")
                st.rerun()


# ── /performance segment + "All" client-combine ────────────────────────────────
#
# /performance returns a real-money block at the top level PLUS a `paper`
# sub-block of the same shape. For the explicit user-selected "All" view we
# combine the two for the metrics that ARE combinable (sums + recomputed rates);
# profitFactor / maxDrawdown are NOT recoverable from the sub-blocks, so they
# render "—" under All. This is an EXPLICIT, user-picked, All-labeled view —
# the never-blend rule only forbids SILENTLY folding paper into a "Real" label.

# Metrics that cannot be reconstructed by combining the real + paper sub-blocks.
_NON_COMBINABLE = ("profitFactor", "maxDrawdown")


def _merge_per_asset_class(real: list | None, paper: list | None) -> list[dict]:
    """Merge two perAssetClass lists by assetClass, summing trades/wins/totalPnl
    and recomputing winRate (wins/trades×100) + expectancy (totalPnl/trades)."""
    acc: dict[str, dict] = {}
    for src in (real or []), (paper or []):
        for row in src:
            cls = str(row.get("assetClass") or "—").lower()
            a = acc.setdefault(cls, {"assetClass": cls, "trades": 0, "wins": 0,
                                     "totalPnl": 0.0})
            a["trades"] += int(row.get("trades") or 0)
            a["wins"] += int(row.get("wins") or 0)
            try:
                a["totalPnl"] += float(row.get("totalPnl") or 0.0)
            except (TypeError, ValueError):
                pass
    out = []
    for a in acc.values():
        t = a["trades"]
        a["winRate"] = round(a["wins"] / t * 100, 1) if t else None
        a["expectancy"] = round(a["totalPnl"] / t, 2) if t else None
        out.append(a)
    return out


def _combine_perf_blocks(real: dict, paper: dict) -> dict:
    """Client-combine the real + paper /performance blocks for the All view.

    Combinable: totalPnl, totalTrades, wins/losses (→ winRate), expectancy,
    perAssetClass (merged), equity (summed if both present). Non-combinable
    (profitFactor / maxDrawdown) are left as ``None`` → the renderer shows "—"
    with a "not available for combined view" caption."""
    def _f(d: dict, k: str) -> float:
        try:
            return float(d.get(k) or 0.0)
        except (TypeError, ValueError):
            return 0.0
    trades = int(real.get("totalTrades") or 0) + int(paper.get("totalTrades") or 0)
    wins = int(real.get("wins") or 0) + int(paper.get("wins") or 0)
    losses = int(real.get("losses") or 0) + int(paper.get("losses") or 0)
    total_pnl = _f(real, "totalPnl") + _f(paper, "totalPnl")
    out = {
        "totalTrades": trades,
        "wins": wins,
        "losses": losses,
        "totalPnl": total_pnl,
        "winRate": round(wins / trades * 100, 1) if trades else None,
        "expectancy": round(total_pnl / trades, 2) if trades else None,
        "perAssetClass": _merge_per_asset_class(
            real.get("perAssetClass"), paper.get("perAssetClass")),
        # Not client-combinable — surfaced as "—" by the renderers.
        "profitFactor": None,
        "maxDrawdown": None,
        "_combined": True,  # marks the non-combinable caption
    }
    # Equity: sum the two curves by index position when both present, else take
    # whichever exists (best-effort — the curves share the window's cadence).
    re_eq, pe_eq = real.get("equity") or [], paper.get("equity") or []
    if re_eq and pe_eq and len(re_eq) == len(pe_eq):
        out["equity"] = [
            {"t": r.get("t"), "cum": _f(r, "cum") + _f(p, "cum")}
            for r, p in zip(re_eq, pe_eq)
        ]
    else:
        out["equity"] = re_eq or pe_eq
    # perStrategy: pass real-money through (paper strategies are a separate axis;
    # best/worst fleet readout stays real-anchored). Combine only when one side
    # is empty so the caller still gets a list.
    out["perStrategy"] = real.get("perStrategy") or paper.get("perStrategy") or []
    return out


def _perf_for_segment(window: str, segment: str) -> tuple[dict, bool]:
    """Resolve one ``/performance?window=`` payload for the chosen segment.

    Returns ``(block, combined)`` where ``block`` is the metrics dict for the
    segment and ``combined`` flags the explicit All view (so the renderer can
    show the profitFactor / maxDrawdown "not available for combined" caption).
    ``{}`` on a real DB error / missing payload (renderers show em-dashes)."""
    if segment == "prop":
        # Prop is not in the money DB (no /performance) — build the same-shaped
        # block from the prop-fills closed frame.
        return _prop_perf_block(window), False
    d, err = _fetch(f"/api/bot/performance?window={window}")
    d = d if isinstance(d, dict) else {}
    if err or d.get("error") or "winRate" not in d:
        return {}, False
    paper = d.get("paper") or {}
    if segment == "paper":
        # Prefer the portfolio-scoped sub-block (`paper_role: portfolio` books
        # only); the bot already falls it back to the all-paper `paper` block
        # server-side when no portfolio accounts are declared, and we fall it
        # back client-side too for a bot that predates the field. So the "Paper"
        # analytics view shows the live-portfolio mirror, not the soak roster.
        # S-PAPER-PORTFOLIO 2026-07-16.
        return (d.get("paperPortfolio") or paper), False
    if segment == "all":
        return _combine_perf_blocks(d, paper), True
    # real: the top-level block IS real-money only (paper sub-block excluded).
    return d, False


def _prop_perf_block(window: str) -> dict:
    """A ``/performance``-shaped block for PROP, computed client-side from the
    prop-fills closed frame windowed by close (report) time. Prop lives in its
    own journal — never the money DB — so this is the prop analogue of the
    real/paper blocks ``_perf_for_segment`` returns. ``perAssetClass`` is built
    separately (``_prop_per_asset_class``) since the closed frame drops symbol.
    Empty/null figures render as em-dashes, never fabricated zeros."""
    empty = {"totalTrades": 0, "wins": 0, "losses": 0, "totalPnl": None,
             "winRate": None, "expectancy": None, "profitFactor": None,
             "maxDrawdown": None, "perAssetClass": []}
    df = _prop_closed_frame()
    if df is None or df.empty:
        return empty
    if window != "all":
        cutoff = dt.datetime.utcnow() - dt.timedelta(days=_WINDOW_DAYS.get(window, 1))
        df = df[df["ts"] >= cutoff]
    if df.empty:
        return empty
    pnl = df["pnl"]
    n = int(len(df))
    wins = int((pnl > 0).sum())
    losses = int((pnl < 0).sum())
    total = float(pnl.sum())
    gross_win = float(pnl[pnl > 0].sum())
    gross_loss = float(-pnl[pnl < 0].sum())
    return {
        "totalTrades": n,
        "wins": wins,
        "losses": losses,
        "totalPnl": total,
        "winRate": round(wins / n * 100, 1) if n else None,
        "expectancy": round(total / n, 2) if n else None,
        "profitFactor": round(gross_win / gross_loss, 2) if gross_loss else None,
        "maxDrawdown": None,
        "perAssetClass": [],
    }


def _prop_per_asset_class(window: str) -> list[dict]:
    """PROP P&L bucketed by asset class (from the prop-fills, which carry the
    symbol) — the prop analogue of ``/performance``'s ``perAssetClass`` list, so
    the Overview asset breakdown renders for the Prop toggle too."""
    data, err = _fetch("/api/bot/prop/fills?limit=400")
    fills = (data or {}).get("fills") or [] if not err else []
    cutoff = (dt.datetime.utcnow() - dt.timedelta(days=_WINDOW_DAYS.get(window, 1))
              if window != "all" else None)
    acc: dict[str, dict] = {}
    for f in fills:
        if str(f.get("status") or "").lower() != "closed":
            continue
        raw = f.get("pnl")
        if raw is None:
            continue
        try:
            v = float(raw)
        except (TypeError, ValueError):
            continue
        ts = _parse_trade_ts(f.get("reported_at"))
        if cutoff is not None and (ts is None or ts < cutoff):
            continue
        cls = _symbol_asset_class(str(f.get("symbol") or ""))
        a = acc.setdefault(cls, {"assetClass": cls, "trades": 0, "wins": 0,
                                 "totalPnl": 0.0})
        a["trades"] += 1
        a["wins"] += 1 if v > 0 else 0
        a["totalPnl"] += v
    out = []
    for a in acc.values():
        t = a["trades"]
        a["winRate"] = round(a["wins"] / t * 100, 1) if t else None
        a["expectancy"] = round(a["totalPnl"] / t, 2) if t else None
        out.append(a)
    return out


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


def _month_pnl_pct(df: pd.DataFrame, year: int, month: int) -> dict[int, float]:
    """Summed per-trade return % per calendar day (0 when unrecorded)."""
    if df.empty or "pnl_pct" not in df.columns:
        return {}
    m = df[(df["ts"].dt.year == year) & (df["ts"].dt.month == month)]
    if m.empty:
        return {}
    daily = m.groupby(m["ts"].dt.day)["pnl_pct"].sum()
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
    pct = _month_pnl_pct(df, year, month)         # summed return % per day
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
                pc = pct.get(day)
                cell = f"<b>{day}</b><br>{p:+,.0f}"
                if pc is not None:
                    cell += f"<br>{pc:+.1f}%"
                tr.append(cell)
                hr.append(f"{year}-{month:02d}-{day:02d} · P&L {p:+,.2f}"
                          + (f" · {pc:+.1f}%" if pc is not None else ""))
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


@st.cache_data(ttl=POLL_INTERVAL_S, show_spinner=False, max_entries=8)
def _analytics_frame(include_paper: bool = False) -> tuple[pd.DataFrame, int, str | None]:
    """One closed-trade fetch (capped) → tidy frame, for the analytics widgets.

    ``include_paper=True`` opts into the real+paper response so the page
    can offer a Real money / Paper / All segment picker over a single fetch.
    """
    since = (dt.datetime.utcnow()
             - dt.timedelta(days=ANALYTICS_LOOKBACK_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    params: dict[str, str] = {"limit": str(ANALYTICS_MAX_ROWS), "since": since}
    if include_paper:
        params["include_paper"] = "true"
    trades, err = _fetch("/api/bot/trades/closed?" + urlencode(params))
    if err:
        return pd.DataFrame(columns=["strategy", "pnl", "ts", "outcome", "accountClass", "isDemo"]), 0, err
    trades = trades or []
    return _closed_trades_frame(trades), len(trades), None


@st.cache_data(ttl=POLL_INTERVAL_S, show_spinner=False, max_entries=4)
def _prop_closed_frame() -> pd.DataFrame:
    """Closed prop-journal fills → the same frame shape as `_closed_trades_frame`
    (strategy/pnl/pnl_pct/ts/outcome/accountClass/isDemo), for the PROP funding
    class on the P&L calendar. Prop lives in a separate store (`/api/bot/prop/fills`),
    never `/trades/closed`; keyed by `reported_at`."""
    cols = ["strategy", "pnl", "pnl_pct", "ts", "outcome", "accountClass", "isDemo", "account"]
    data, err = _fetch("/api/bot/prop/fills?limit=400")
    fills = (data or {}).get("fills") or [] if not err else []
    records = []
    for f in fills:
        if str(f.get("status") or "").lower() != "closed":
            continue
        raw = f.get("pnl")
        if raw is None:
            continue
        try:
            pnl = float(raw)
        except (TypeError, ValueError):
            continue
        ts = _parse_trade_ts(f.get("reported_at"))
        if ts is None:
            continue
        try:
            pct = float(f.get("pnl_percent") or 0.0)
        except (TypeError, ValueError):
            pct = 0.0
        records.append({
            "strategy": "prop", "pnl": pnl, "pnl_pct": pct, "ts": ts,
            "outcome": "win" if pnl > 0 else "loss" if pnl < 0 else "breakeven",
            "accountClass": "prop", "isDemo": False,
            "account": str(f.get("account_id") or ""),
        })
    return pd.DataFrame.from_records(records)[cols] if records else pd.DataFrame(columns=cols)


def _prop_closed_rows(window: str) -> list[dict]:
    """Closed PROP fills shaped into the ``/trades/closed`` row schema so the
    Trades page's table + detail card render them like any closed trade. Prop
    lives in its own journal (`/api/bot/prop/fills`), never `/trades/closed`.
    Windowed by close (report) time; ``all`` keeps everything."""
    data, err = _fetch("/api/bot/prop/fills?limit=400")
    fills = (data or {}).get("fills") or [] if not err else []
    cutoff = (dt.datetime.utcnow() - dt.timedelta(days=_WINDOW_DAYS.get(window, 1))
              if window != "all" else None)
    rows: list[dict] = []
    for f in fills:
        if str(f.get("status") or "").lower() != "closed":
            continue
        ts = _parse_trade_ts(f.get("closed_at") or f.get("reported_at"))
        if cutoff is not None and (ts is None or ts < cutoff):
            continue
        rows.append({
            "closedAt": f.get("closed_at") or f.get("reported_at"),
            "openedAt": f.get("opened_at"),
            "account": f.get("account_id"),
            "symbol": f.get("symbol"),
            "side": f.get("direction"),
            "pattern": "prop",
            "qty": f.get("qty"),
            "entryPrice": f.get("entry_price"),
            "exitPrice": f.get("exit_price"),
            "realizedPnl": f.get("pnl"),
            "realizedPnlPct": f.get("pnl_percent"),
            "closeReason": f.get("reason"),
            "accountClass": "prop",
            "isDemo": False,
        })
    return rows


def _render_overview_calendar(segment: str) -> None:
    """The P&L calendar on the Overview — mirrors the Android Overview widget:
    a month picker + day $+% cells + a monthly total. Driven by the page's ONE
    top funding toggle (its own separate toggle was removed 2026-07-10). Full
    history, NOT scoped to the page window. Reuses `build_pnl_calendar`; prop
    days come from the prop-fills frame."""
    seg_word = _FUNDING_SEG_NAME.get(segment, segment)
    st.markdown(f"**📅 P&L calendar · {seg_word}**")
    if segment == "prop":
        cal_df = _prop_closed_frame()
    else:
        frame, _, ferr = _analytics_frame(include_paper=True)
        cal_df = frame if ferr else _segment_filter_frame(frame, segment)
    c1, c2 = st.columns([2, 3])
    with c1:
        months = _recent_months(6)
        ym = st.selectbox(
            "Month", months, key="ov_cal_month",
            format_func=lambda v: f"{calendar.month_name[v[1]]} {v[0]}",
        )
    with c2:
        mp = _month_pnl(cal_df, ym[0], ym[1])
        mpc = _month_pnl_pct(cal_df, ym[0], ym[1])
        if mp:
            st.markdown(
                f"**{calendar.month_name[ym[1]]} {ym[0]} total**  \n"
                f"{fmt_usd(sum(mp.values()))} · {sum(mpc.values()):+.1f}%"
            )
        else:
            st.caption(f"No closed {seg_word} trades this month.")
    st.plotly_chart(
        build_pnl_calendar(cal_df, ym[0], ym[1]),
        use_container_width=True, config={"displayModeBar": False},
    )
    st.caption("Daily realised P&L ($ + summed return %) · green profit / red "
               "loss · full history, pick the month above.")


def render_trade_analytics(segment: str) -> None:
    """The performance deep-dive: filter + headline metrics + equity curve +
    calendar + win/loss bar + strategy pie + per-strategy breakdown.

    ``segment`` (real/paper/prop) comes from the page's ONE top funding toggle —
    the deep-dive no longer renders its own segment picker (operator ask
    2026-07-10: one toggle drives the whole tab). It renders only the time-window
    axis; the window drives the headline metrics, equity curve, calendar and
    win/loss bar via the shared ``df``.
    """
    dd_wlabel, dd_wslug = _window_control("perf_dd_window", index=3)
    if segment == "prop":
        # Prop closed trades live in the prop journal, not /trades/closed.
        df = _prop_closed_frame()
        raw_count = len(df)
    else:
        df, raw_count, err = _analytics_frame(include_paper=True)
        if err:
            st.info(f"Trade analytics unavailable: {err}")
            return
        df = _segment_filter_frame(df, segment)
    if not df.empty:
        _dd_cutoff = dt.datetime.utcnow() - dt.timedelta(days=_WINDOW_DAYS[dd_wslug])
        df = df[df["ts"] >= _dd_cutoff].reset_index(drop=True)
    if df.empty:
        if segment == "real":
            st.caption("No closed real-money trades yet — analytics will populate as trades close.")
        elif segment == "paper":
            st.caption("No closed paper trades in the lookback window.")
        elif segment == "prop":
            st.caption("No closed prop trades in the lookback window.")
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
    m[0].metric(f"Trades · {dd_wlabel}", n)
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
        st.markdown(f"**Per-strategy breakdown · {dd_wlabel}**")
        st.dataframe(_strategy_breakdown(df), hide_index=True,
                     use_container_width=True)


# ── Overview ──────────────────────────────────────────────────────────────────

# Asset-class display order + icons for the exec-summary breakdown. The bot's
# /performance perAssetClass list drives the rows; this just gives a stable
# order + a glyph. An unknown class falls through to a bullet.
_ASSET_CLASS_ICON = {
    "crypto": "₿ crypto", "index": "📈 index", "commodity": "🛢️ commodity",
    "equity": "🏛️ equity", "fx": "💱 fx", "futures": "📊 futures",
}


def _asset_class_order(c: str) -> int:
    """Stable display order for a perAssetClass row (known classes first)."""
    keys = list(_ASSET_CLASS_ICON.keys())
    k = str(c).lower()
    return keys.index(k) if k in keys else len(keys)


# ── Organize-by / focus: group live trades + history by strategy / account /
#    asset class / symbol, isolate one group, and show per-group performance ────
#
# Operator ask (2026-06-29): organize the Overview live-trades monitor + the
# Positions/Trades views by strategy, account, or asset GROUP (crypto / metals /
# equities / …), and isolate a single group to see just its trades + its
# performance. Asset class prefers the bot's authoritative ``assetClass`` field
# (added 2026-06-29, resolved from config/instruments.yaml); a client-side
# classifier is the fallback so the dashboard still buckets sensibly against a
# bot that predates the field (graceful degradation — render, never crash).

# Display labels + canonical order for the asset-class grouping dimension.
# Superset of _ASSET_CLASS_ICON (adds bond + unknown), used only by the grouping
# UI so the exec-summary breakdown that reads the /performance perAssetClass list
# is untouched.
_ASSET_CLASS_LABEL = {
    "crypto": "₿ Crypto", "index": "📈 Index", "commodity": "🛢️ Commodity / Metals",
    "bond": "🏦 Bonds", "equity": "🏛️ Equities", "fx": "💱 FX",
    "futures": "📊 Futures", "unknown": "• Other",
}

# Client-side fallback roots — mirror src/web/api/_asset_class.py::_infer so a
# row from a pre-field bot still classifies the same way the server would.
_CRYPTO_SUFFIX = ("USDT", "USDC", "USDP")
_FALLBACK_INDEX_ROOTS = {"ES", "NQ", "YM", "RTY", "MES", "MNQ", "MYM", "M2K"}
_FALLBACK_COMMODITY_ROOTS = {
    "GC", "SI", "HG", "PL", "PA", "CL", "NG", "MGC", "MHG",
    "XAU", "XAG", "GLD", "SLV", "USO",
}
_FALLBACK_BOND_ROOTS = {
    "TLT", "IEF", "AGG", "BND", "LQD", "HYG", "SHY", "TLH", "IEI", "SHV",
    "BNDX", "TIP",
}
_FALLBACK_EQUITY_ROOTS = {"SPY", "QQQ", "IWM", "DIA", "VOO", "VTI"}


def _symbol_asset_class(symbol: Any) -> str:
    """Best-effort asset class from a bare symbol (fallback only)."""
    s = str(symbol or "").strip().upper()
    if not s:
        return "unknown"
    if s in _FALLBACK_COMMODITY_ROOTS:
        return "commodity"
    if s in _FALLBACK_BOND_ROOTS:
        return "bond"
    if s in _FALLBACK_INDEX_ROOTS:
        return "index"
    if s in _FALLBACK_EQUITY_ROOTS:
        return "equity"
    if s.endswith(_CRYPTO_SUFFIX):
        return "crypto"
    # 6-letter all-alpha pair convention (EURUSD, GBPJPY) — best-effort FX.
    if len(s) == 6 and s.isalpha():
        return "fx"
    return "unknown"


def _row_asset_class(d: dict) -> str:
    """Asset class for a position/trade/order-package row.

    Prefers the bot's authoritative ``assetClass`` field; falls back to the
    client-side classifier (so a bot that predates the field still groups)."""
    ac = str((d or {}).get("assetClass") or "").strip().lower()
    if ac and ac != "unknown":
        return ac
    return _symbol_asset_class((d or {}).get("symbol"))


# Organize-by dimension: display label → slug. "Recent" = no grouping, one flat
# list sorted by the relevant time (open time for live trades, close time for
# closed trades) newest-first — the default.
_GROUP_CHOICES: list[str] = ["Recent", "Strategy", "Account", "Asset", "Symbol"]
_GROUP_DIM: dict[str, str] = {
    "Recent": "none", "Strategy": "strategy", "Account": "account",
    "Asset": "asset", "Symbol": "symbol",
}
# dim slug → the column header used for that dimension in a per-group table.
_GROUP_DIM_COL: dict[str, str] = {
    "strategy": "Strategy", "account": "Account", "asset": "Asset class",
    "symbol": "Symbol",
}


def _group_dim_col(dim: str) -> str:
    return _GROUP_DIM_COL.get(dim, "Group")


def _row_group_key(row: dict, dim: str) -> str:
    """The group a row belongs to for ``dim``. ``pattern``/``strategy`` both
    resolve the strategy (positions use ``pattern``, order-packages ``strategy``)."""
    if dim == "strategy":
        return str(row.get("pattern") or row.get("strategy") or "—")
    if dim == "account":
        return str(row.get("account") or "—")
    if dim == "asset":
        return _row_asset_class(row)
    if dim == "symbol":
        return str(row.get("symbol") or "—")
    return "All"


def _group_label(key: str, dim: str) -> str:
    """Human label for a group key (asset class gets an icon label)."""
    if dim == "asset":
        return _ASSET_CLASS_LABEL.get(key, _ASSET_CLASS_LABEL["unknown"])
    return key


def _group_rows(rows: list[dict], dim: str) -> list[tuple[str, list[dict]]]:
    """Partition ``rows`` into ``[(group_key, rows), …]``.

    Asset-class groups follow the canonical class order; every other dimension
    is ordered biggest-group-first then alphabetically."""
    groups: dict[str, list[dict]] = {}
    for r in rows or []:
        groups.setdefault(_row_group_key(r, dim), []).append(r)
    if dim == "asset":
        order = list(_ASSET_CLASS_LABEL.keys())

        def _key(kv: tuple[str, list[dict]]) -> tuple[int, str]:
            return (order.index(kv[0]) if kv[0] in order else len(order), kv[0])
    else:
        def _key(kv: tuple[str, list[dict]]) -> tuple[int, str]:
            return (-len(kv[1]), str(kv[0]))

    return sorted(groups.items(), key=_key)


def _organize_controls(
    key_prefix: str, rows: list[dict], *, account_dim: bool = True,
) -> tuple[str, str | None]:
    """Render the 'Organize by' + 'Focus on' control pair.

    Returns ``(dim, focus)`` — ``dim`` ∈ {none,strategy,account,asset,symbol};
    ``focus`` is ``None`` (show every group) or a single group key to isolate.
    ``rows`` (already segment-filtered) populate the focus choices. Pass
    ``account_dim=False`` where rows carry no account (e.g. signals)."""
    choices = [c for c in _GROUP_CHOICES if account_dim or c != "Account"]
    # Compact two-up bar: a single-line "Organize by" dropdown (was a 5-button
    # segmented control that wrapped to two rows on mobile) beside a "Focus on"
    # dropdown that only appears once a real dimension is picked — so the default
    # "Recent" view is a single control (one row on a phone).
    c1, c2 = st.columns(2)
    with c1:
        dim_label = _segmented_or_radio(
            "Organize by", choices, index=0, key=f"{key_prefix}_groupby",
            help="Default 'Recent' = one list newest-first (by open time for "
                 "live trades, close time for closed trades). Pick a dimension "
                 "to split into per-group sections + isolate one group.",
        )
        dim = _GROUP_DIM.get(dim_label, "none")
    focus: str | None = None
    if dim != "none":
        with c2:
            keys = [k for k, _ in _group_rows(rows, dim)]
            _apply_pending_widget(f"{key_prefix}_focus")
            picked = st.selectbox(
                f"Focus on {dim_label.lower()}", ["All", *keys],
                key=f"{key_prefix}_focus",
                format_func=lambda k: "All" if k == "All" else _group_label(k, dim),
                help="Isolate a single group — its trades and its performance "
                     "only. 'All' keeps every section.",
            )
            focus = None if picked == "All" else picked
    return dim, focus


def _apply_focus(rows: list[dict], dim: str, focus: str | None) -> list[dict]:
    """Narrow ``rows`` to the focused group (no-op when focus is None)."""
    if dim == "none" or focus is None:
        return rows
    return [r for r in rows if _row_group_key(r, dim) == focus]


def _row_time_value(row: dict, kind: str) -> dt.datetime:
    """The timestamp a row sorts on. ``open`` → opened time, ``closed`` →
    closed time (opened fallback), anything else → a generic detection time.
    Unparseable / missing sorts oldest (``datetime.min``)."""
    if kind == "closed":
        d = _parse_trade_ts(row.get("closedAt") or row.get("openedAt"))
    elif kind == "open":
        d = _parse_trade_ts(row.get("openedAt"))
    else:
        d = _parse_trade_ts(
            row.get("ts") or row.get("timestamp") or row.get("time"))
    return d or dt.datetime.min


def _sort_recent(rows: list[dict], kind: str) -> list[dict]:
    """Newest-first by the row's relevant time (open/close), for the default
    'Recent' view + ordering within each group."""
    return sorted(rows, key=lambda r: _row_time_value(r, kind), reverse=True)


def _focus_symbols(
    all_symbols: list[str], focus_positions: list[dict], dim: str, focus: str | None,
) -> list[str]:
    """The Overview chart symbols relevant to the focused group.

    No focus → every active symbol (unchanged). With a focus, restrict to the
    symbols carrying a matching open position (so the operator sees exactly the
    isolated trades), plus — for the symbol/asset dimensions — any active
    no-position symbol that still belongs to the group. Original order kept."""
    if dim == "none" or focus is None:
        return all_symbols
    syms: list[str] = []
    for p in focus_positions:
        s = str(p.get("symbol") or "").strip().upper()
        if s and s not in syms:
            syms.append(s)
    if dim == "symbol" and focus not in syms:
        syms.append(focus)
    elif dim == "asset":
        for s in all_symbols:
            if _symbol_asset_class(s) == focus and s not in syms:
                syms.append(s)
    ordered = [s for s in all_symbols if s in syms]
    extra = [s for s in syms if s not in all_symbols]
    return ordered + extra


def _open_group_caption(rows: list[dict]) -> str:
    """One-line open-exposure summary for a group of open positions."""
    total, unk = _sum_upnl(rows)
    known = len(rows) - unk
    noun = "position" if len(rows) == 1 else "positions"
    return f"{len(rows)} open {noun} · uPnL " + _upnl_metric(total, known, unk)


def _closed_group_stats(rows: list[dict]) -> dict:
    """Client-side win/loss/PnL aggregate over a group of closed-trade rows.

    Null ``realizedPnl`` rows are counted in ``trades`` but excluded from the
    win/loss/PnL math (never folded in as $0) — matching the API's nullability
    contract."""
    n = len(rows)
    wins = losses = known = 0
    pnl = 0.0
    for r in rows:
        v = r.get("realizedPnl")
        if v is None:
            continue
        try:
            v = float(v)
        except (TypeError, ValueError):
            continue
        known += 1
        pnl += v
        if v > 0:
            wins += 1
        elif v < 0:
            losses += 1
    return {
        "trades": n, "wins": wins, "losses": losses, "known": known,
        "winRate": (wins / known * 100) if known else None,
        "pnl": pnl if known else None,
    }


def _closed_group_caption(rows: list[dict]) -> str:
    """One-line realised-performance summary for a group of closed trades."""
    s = _closed_group_stats(rows)
    return (f"{s['trades']} trades · {s['wins']}W/{s['losses']}L · "
            f"win {fmt_pct(s['winRate'])} · P&L {fmt_usd(s['pnl'])}")


def build_asset_class_bar(per_class: list | None, height: int = 220) -> go.Figure | None:
    """Horizontal P&L-by-asset-class bar (green profit / red loss) from a
    /performance ``perAssetClass`` list. Returns None when there's nothing to
    show, so the caller can fall back to a caption."""
    rows = [r for r in (per_class or []) if r.get("totalPnl") is not None]
    if not rows:
        return None
    rows = sorted(rows, key=lambda r: _asset_class_order(r.get("assetClass")))
    labels, vals = [], []
    for r in rows:
        cls = str(r.get("assetClass") or "—").lower()
        labels.append(_ASSET_CLASS_ICON.get(cls, f"• {cls}"))
        try:
            vals.append(float(r.get("totalPnl") or 0.0))
        except (TypeError, ValueError):
            vals.append(0.0)
    fig = go.Figure(go.Bar(
        x=vals, y=labels, orientation="h",
        marker_color=[_TV_GREEN if v >= 0 else _TV_RED for v in vals],
        hovertemplate="%{y}: $%{x:,.2f}<extra></extra>",
    ))
    fig.update_xaxes(showgrid=True, gridcolor=_LC_GRID_H, fixedrange=True,
                     zeroline=True, zerolinecolor="#2a3a5a")
    fig.update_yaxes(showgrid=False, fixedrange=True)
    return _style_plotly(fig, height)


def _asset_symbol_pnl(rows: list[dict]) -> dict[str, dict[str, float]]:
    """Aggregate realized P&L per (asset class → symbol) from closed-trade rows.

    Null ``realizedPnl`` rows are skipped (never summed as 0) — matching the
    API nullability contract."""
    agg: dict[str, dict[str, float]] = {}
    for r in rows or []:
        v = r.get("realizedPnl")
        if v is None:
            continue
        try:
            v = float(v)
        except (TypeError, ValueError):
            continue
        cls = _row_asset_class(r)
        sym = str(r.get("symbol") or "—").upper()
        agg.setdefault(cls, {}).setdefault(sym, 0.0)
        agg[cls][sym] += v
    return agg


def build_asset_class_symbol_bar(rows: list[dict], height: int = 220) -> go.Figure | None:
    """Horizontal P&L-by-asset-class bar **stacked by symbol** (operator ask):
    each asset-class bar is subdivided into its constituent symbols, one coloured
    portion each, so you can see WHICH instrument drove the class's P&L.
    ``barmode='relative'`` so a losing symbol extends left of zero and a winning
    one right — the net bar length still reads as the class total. Returns None
    when no per-symbol closed-trade P&L resolves, so the caller can fall back to
    the authoritative per-class bar. Legend = the symbols."""
    agg = _asset_symbol_pnl(rows)
    if not agg:
        return None
    classes = sorted(agg.keys(), key=_asset_class_order)
    class_labels = [_ASSET_CLASS_ICON.get(c, f"• {c}") for c in classes]
    # Symbols ordered by total |P&L| so the biggest movers get the stable
    # leading palette colours.
    sym_abs: dict[str, float] = {}
    for d in agg.values():
        for s, v in d.items():
            sym_abs[s] = sym_abs.get(s, 0.0) + abs(v)
    symbols = sorted(sym_abs, key=lambda s: sym_abs[s], reverse=True)
    fig = go.Figure()
    for i, sym in enumerate(symbols):
        xs = [agg.get(c, {}).get(sym, 0.0) for c in classes]
        if not any(xs):
            continue
        fig.add_bar(
            y=class_labels, x=xs, orientation="h", name=sym,
            marker_color=_CATEGORICAL[i % len(_CATEGORICAL)],
            hovertemplate=f"{sym} · %{{y}}: $%{{x:,.2f}}<extra></extra>",
        )
    fig.update_layout(barmode="relative",
                      legend=dict(orientation="h", yanchor="top", y=-0.2,
                                  xanchor="left", x=0))
    fig.update_xaxes(showgrid=True, gridcolor=_LC_GRID_H, fixedrange=True,
                     zeroline=True, zerolinecolor="#2a3a5a")
    fig.update_yaxes(showgrid=False, fixedrange=True)
    return _style_plotly(fig, height)


def _closed_rows_for_window(segment: str, window: str) -> list[dict]:
    """Closed-trade rows (with ``symbol`` + ``realizedPnl``) for the segment +
    window, feeding the per-symbol asset-class breakdown. real/paper come from
    ``/trades/closed`` (windowed by CLOSE time client-side, matching the exec
    basis — deliberately no ``since=`` since that filters on OPEN time and drops
    a trade held across the window boundary); prop comes from the prop journal.
    ``realizedPnl``-null rows are kept in the list (the aggregator skips them)."""
    if segment == "prop":
        return _prop_closed_rows(window)
    include_paper = "true" if segment in ("paper", "all") else "false"
    rows, _ = _fetch("/api/bot/trades/closed?"
                     + urlencode({"limit": 500, "include_paper": include_paper}))
    rows = _segment_filter_rows(rows or [], segment)
    if window != "all":
        cutoff = dt.datetime.utcnow() - dt.timedelta(days=_WINDOW_DAYS.get(window, 1))
        rows = [
            r for r in rows
            if (_parse_trade_ts(r.get("closedAt") or r.get("openedAt")) or dt.datetime.min) >= cutoff
        ]
    return rows


def _closed_rows_all(segment: str) -> list[dict]:
    """All recent closed rows (NO window filter) — the per-symbol composition
    fallback for when the windowed close-time filter drops rows. ``/trades/closed``
    can return a recently-closed trade whose ``closedAt`` is null while its
    ``openedAt`` predates the window, so the client-side close-time window drops
    it even though ``/performance`` (which windows on a COALESCE(closed_at,
    updated_at, timestamp) basis) still counts it — leaving the symbol split
    blank while the class total is non-zero. This un-windowed set recovers the
    symbol composition; the class TOTAL still comes from the authoritative
    ``/performance`` figure, so the split is representative, not authoritative."""
    if segment == "prop":
        return _prop_closed_rows("all")
    include_paper = "true" if segment in ("paper", "all") else "false"
    rows, _ = _fetch("/api/bot/trades/closed?"
                     + urlencode({"limit": 500, "include_paper": include_paper}))
    return _segment_filter_rows(rows or [], segment)


def _bar_from_symbol_agg(
    agg: dict[str, dict[str, float]], height: int = 220
) -> go.Figure | None:
    """Stacked-by-symbol horizontal P&L bar from a ``{class: {symbol: pnl}}``
    map (``barmode='relative'`` so a losing symbol extends left of zero). Returns
    None when the map is empty. Shared by :func:`build_asset_class_symbol_bar`
    and the anchored breakdown below."""
    agg = {c: s for c, s in agg.items() if s}
    if not agg:
        return None
    classes = sorted(agg.keys(), key=_asset_class_order)
    class_labels = [_ASSET_CLASS_ICON.get(c, f"• {c}") for c in classes]
    sym_abs: dict[str, float] = {}
    for d in agg.values():
        for s, v in d.items():
            sym_abs[s] = sym_abs.get(s, 0.0) + abs(v)
    symbols = sorted(sym_abs, key=lambda s: sym_abs[s], reverse=True)
    fig = go.Figure()
    for i, sym in enumerate(symbols):
        xs = [agg.get(c, {}).get(sym, 0.0) for c in classes]
        if not any(xs):
            continue
        fig.add_bar(
            y=class_labels, x=xs, orientation="h", name=sym,
            marker_color=_CATEGORICAL[i % len(_CATEGORICAL)],
            hovertemplate=f"{sym} · %{{y}}: $%{{x:,.2f}}<extra></extra>",
        )
    fig.update_layout(barmode="relative",
                      legend=dict(orientation="h", yanchor="top", y=-0.2,
                                  xanchor="left", x=0))
    fig.update_xaxes(showgrid=True, gridcolor=_LC_GRID_H, fixedrange=True,
                     zeroline=True, zerolinecolor="#2a3a5a")
    fig.update_yaxes(showgrid=False, fixedrange=True)
    return _style_plotly(fig, height)


def _render_asset_class_symbol_breakdown(
    segment: str, win_label: str, window: str, *, seg_note: str,
) -> None:
    """P&L-by-asset-class bar **stacked by symbol** + a compact per-class caption.
    Shared by the Overview and the Performance page.

    Classes + totals AND the per-symbol split both come from the AUTHORITATIVE
    ``/performance`` aggregate: ``perAssetClass`` for the class totals (the same
    source as the exec "Realized P&L" card) and ``perSymbol`` for the split —
    both computed by the SAME windowed SQL query, so a class that reports a total
    can NEVER render an empty per-symbol split. This replaced the client-side
    ``/trades/closed`` re-aggregation, which came back empty (leaving a flat
    per-class bar) because that endpoint drops a recently-closed trade whose
    ``closedAt`` is null while ``/performance`` still counts it. A client-side
    fallback remains for a bot that predates ``perSymbol``; Prop (not in the
    money DB) comes from the prop journal, symbol-stacked as well."""
    st.markdown(f"**P&L by asset class · by symbol · {win_label} ({seg_note})**")

    agg: dict[str, dict[str, float]] = {}
    approx = False
    if segment == "prop":
        # Prop isn't in /performance — per-symbol from the prop journal.
        per_class = [r for r in _prop_per_asset_class(window)
                     if r.get("totalPnl") is not None]
        agg = _asset_symbol_pnl(_prop_closed_rows(window))
        if not any(agg.values()):
            agg = _asset_symbol_pnl(_prop_closed_rows("all"))
            approx = bool(agg)
    else:
        block, _combined = _perf_for_segment(window, segment)
        per_class = [r for r in ((block or {}).get("perAssetClass") or [])
                     if r.get("totalPnl") is not None]
        # AUTHORITATIVE per-symbol split from /performance `perSymbol` — computed
        # by the SAME windowed query as the class totals, so a class that reports
        # a total can never render an empty per-symbol split (the /trades/closed
        # close-time drift that kept this bar flat). Grouped by asset class.
        for row in (block or {}).get("perSymbol") or []:
            p = row.get("totalPnl")
            if p is None:
                continue
            cls = str(row.get("assetClass") or "unknown").lower()
            sym = str(row.get("symbol") or "—").upper()
            try:
                agg.setdefault(cls, {})[sym] = float(p)
            except (TypeError, ValueError):
                pass
        # Graceful fallback for a bot that predates the `perSymbol` field: fill
        # each class from the client-side closed rows (windowed → recent).
        if not agg:
            win_agg = _asset_symbol_pnl(_closed_rows_for_window(segment, window))
            all_agg: dict[str, dict[str, float]] | None = None
            for r in per_class:
                cls = str(r.get("assetClass") or "unknown").lower()
                if win_agg.get(cls):
                    agg[cls] = win_agg[cls]
                    continue
                if all_agg is None:
                    all_agg = _asset_symbol_pnl(_closed_rows_all(segment))
                if all_agg.get(cls):
                    agg[cls] = all_agg[cls]
                    approx = True
            if not per_class and win_agg:
                agg = win_agg

    fig = _bar_from_symbol_agg(agg, height=220)
    if fig is None:
        # Last resort: the flat authoritative per-class bar (no per-symbol data
        # anywhere — e.g. brand-new account with only unresolved-PnL trades).
        class_fig = build_asset_class_bar(per_class, height=220)
        if class_fig is None:
            st.caption("P&L by asset class: — (no closed-trade P&L for this "
                       "class / window yet).")
            return
        st.plotly_chart(class_fig, use_container_width=True,
                        config={"displayModeBar": False})
        st.caption("Per-class totals shown; per-symbol split unavailable.")
        _render_per_class_caption(per_class)
        return

    st.plotly_chart(fig, use_container_width=True,
                    config={"displayModeBar": False})
    if approx:
        st.caption("Some classes' per-symbol split uses recent closed trades "
                   "(the window's close-time data was incomplete); the per-class "
                   "totals below follow the window.")
    _render_per_class_caption(per_class)


def _render_per_class_caption(per_class: list[dict]) -> None:
    """2-up per-class 'N trades · win X%' caption from the authoritative
    ``/performance`` ``perAssetClass`` list."""
    ordered = sorted(
        [r for r in per_class if r.get("totalPnl") is not None],
        key=lambda r: _asset_class_order(r.get("assetClass")))
    for i in range(0, len(ordered[:6]), 2):
        cols_ac = st.columns(2)
        for j, r in enumerate(ordered[i:i + 2]):
            cls = str(r.get("assetClass") or "—").lower()
            lbl = _ASSET_CLASS_ICON.get(cls, f"• {cls}")
            cols_ac[j].caption(
                f"{lbl}: {int(r.get('trades') or 0)} trades · "
                f"win {fmt_pct(r.get('winRate'))}")


def _exec_perf_window(window: str) -> dict:
    """One /performance window as a dict ({} on error/missing), error-aware."""
    d, err = _fetch(f"/api/bot/performance?window={window}")
    d = d if isinstance(d, dict) else {}
    if err or d.get("error"):
        return {}
    return d


def _readiness_counts(strategies: list) -> dict:
    """Promotion-readiness roll-up for the exec summary + the Promotion page.

    Two fleets, mirroring the Android Readiness screen so the apps agree:
      - **Models** — shadow-stage soak from ``/api/bot/shadow/stats``, graded by
        the shared ``_promotion_verdict``: ``ok`` → *ready to evaluate*,
        ``warn`` → *soaking* (maturing toward the ≥7d & ≥200-pred standard).
      - **Strategies** — the M7 review verdict per strategy
        (``/api/bot/strategies/{name}/review`` → ``proposed_action``), bucketed
        into promote / tune / hold / demote_shadow / kill. Only strategies WITH
        a packet are counted. Best-effort — a failed fetch just contributes 0.
    """
    stats_env, serr = _fetch("/api/bot/shadow/stats")
    rows = (stats_env or {}).get("records") or [] if not serr else []
    ready = soaking = 0
    for r in rows:
        _, sev, _facts = _promotion_verdict(r)
        if sev == "ok":
            ready += 1
        elif sev == "warn":
            soaking += 1

    buckets = {"promote": 0, "tune": 0, "hold": 0, "demote_shadow": 0, "kill": 0}
    reviewed = 0
    for strat in strategies or []:
        name = strat.get("name")
        if not name:
            continue
        rev, rerr = _fetch(f"/api/bot/strategies/{quote(str(name))}/review")
        if rerr or not (rev or {}).get("present"):
            continue
        packet = (rev or {}).get("packet")
        if not packet:
            continue
        action = str(packet.get("proposed_action") or "hold").lower()
        if action == "demote":
            action = "demote_shadow"
        buckets[action] = buckets.get(action, 0) + 1
        reviewed += 1
    return {"ready": ready, "soaking": soaking, "reviewed": reviewed, **buckets}


def _render_readiness_block(strategies: list) -> None:
    """The compact promotion-readiness metric row for the exec summary."""
    st.markdown("**Promotion readiness**")
    rc = _readiness_counts(strategies)
    if rc["ready"] + rc["soaking"] + rc["reviewed"] == 0:
        st.caption("No soaking models or strategy-review packets yet.")
        return
    rr = st.columns(4)
    rr[0].metric("Models soaking", rc["soaking"])
    rr[1].metric("Models ready", rc["ready"])
    rr[2].metric("Strat. promote", rc["promote"])
    rr[3].metric("Needs attn.", rc["demote_shadow"] + rc["kill"])
    extra = []
    if rc["tune"]:
        extra.append(f"{rc['tune']} tune")
    if rc["hold"]:
        extra.append(f"{rc['hold']} hold")
    if extra:
        st.caption("Strategies: " + " · ".join(extra)
                   + " · full drill-down on the Promotion page")


def _segment_equity(segment: str) -> tuple[float | None, int]:
    """Sum of PRESENT tracked balances for the segment's accounts.

    ``real`` → real-money accounts; ``paper`` → paper accounts; ``all`` →
    real + paper (prop excluded — prop is never real money). Returns
    ``(equity, n_missing)``; a missing / failed balance is excluded from the
    sum (never summed as 0), and ``equity`` is None when NO in-scope account
    has a tracked balance."""
    cfg, _ = _fetch("/api/bot/config")
    cfg = cfg if isinstance(cfg, dict) else {}
    accounts = cfg.get("accounts") or []
    bal_env, _ = _fetch("/api/bot/accounts/balances")
    balances = (bal_env or {}).get("balances") or {}

    def _cls(a: dict) -> str:
        return str(a.get("account_class") or "real_money").lower()

    if segment == "paper":
        # Paper equity scopes to the live-portfolio-mirror books (soak books
        # excluded — they're on the Accounts page only); fall back to all paper
        # when no portfolio books are declared. S-PAPER-PORTFOLIO 2026-07-16.
        portfolio = _portfolio_paper_ids()
        ids = {a.get("id") for a in accounts if _cls(a) == "paper"
               and (not portfolio or str(a.get("id")) in portfolio)}
    elif segment == "prop":
        ids = {a.get("id") for a in accounts if _cls(a) == "prop"}
    elif segment == "all":
        ids = {a.get("id") for a in accounts if _cls(a) != "prop"}
    else:  # real
        ids = {a.get("id") for a in accounts if _cls(a) not in _NON_REAL_CLASSES}

    total = 0.0
    present = missing = 0
    for i in ids:
        b = (balances.get(i) or {}).get("balance")
        if b is None:
            missing += 1
            continue
        try:
            total += float(b)
            present += 1
        except (TypeError, ValueError):
            missing += 1
    return (total if present else None), missing


def _render_exec_summary(stats: dict, segment: str, win_label: str, window: str) -> None:
    """The slim executive header at the top of the Overview page — the SIX
    headline cards the operator asked for (2026-07-09):

        Total equity · Open trades · Realized P&L (# + %) ·
        Unrealized P&L (# + %) · Win rate · Profit factor

    Everything that used to live here (asset-class breakdown, strategy/ML
    fleets, promotion readiness, the analyst/report/news glance) moved BELOW the
    live-trades monitor. All figures follow the page's ``segment`` (real / paper
    / all) + ``window`` (24h/7d/30d/all). The **%** on the two P&L cards is the
    return on the SAME tracked equity shown in card 1 (a single consistent
    denominator). Any null/missing value renders as an em-dash, never a
    fabricated 0. Real / paper / prop stay strictly separate — "All" is the
    operator's EXPLICIT, All-labeled merge, never a silent blend into "real"."""
    seg_name = _FUNDING_SEG_NAME.get(
        segment, {"real": "real money", "paper": "paper",
                  "all": "all (real + paper)"}.get(segment, segment))
    st.markdown(f"### Executive summary · {seg_name} · {win_label}")

    # ── System status line ─────────────────────────────────────────────────
    status = str(stats.get("status") or "unknown")
    status_color = {"running": _TV_GREEN, "paused": "#f5a623",
                    "stopped": _TV_RED}.get(status, "#6b7488")
    strat_payload, _ = _fetch("/api/bot/strategies")
    strat_payload = strat_payload if isinstance(strat_payload, dict) else {}
    tick_age = (strat_payload.get("runtime") or {}).get("tick_age_seconds")
    st.markdown(_status_dot(status_color)
                + f"**System {status.upper()}** · last tick {_fmt_age(tick_age)} ago"
                + f" · datasource {stats.get('datasource', '?')}",
                unsafe_allow_html=True)

    # ── Equity for the segment (real / paper / all) ────────────────────────
    equity_val, eq_missing = _segment_equity(segment)
    equity_str = fmt_usd(equity_val) if equity_val is not None else "—"

    # ── Open positions for the segment ─────────────────────────────────────
    if segment == "prop":
        # Prop has no broker feed — live prop trades come from the outbound
        # `filled` tickets shaped into position-like rows (mark-price uPnL).
        seg_open = _prop_open_positions()
    else:
        pos_all, _ = _fetch("/api/bot/positions?include_paper=true")
        pos_all = pos_all or []
        if segment == "paper":
            seg_open = [p for p in pos_all if _row_is_portfolio_paper(p)]
        else:  # real
            seg_open = [p for p in pos_all if _is_real_money(p)]
    open_upnl, open_unk = _sum_upnl(seg_open)
    open_known = len(seg_open) - open_unk

    # ── Windowed realized P&L / win rate / profit factor for the segment ───
    block, combined = _perf_for_segment(window, segment)
    _pnl = block.get("totalPnl")
    if _pnl is None and window == "24h" and segment == "real":
        _pnl = stats.get("pnl24h")
    if _pnl is None and window == "all" and segment == "real":
        _pnl = stats.get("totalPnL")
    _wr = block.get("winRate")
    if _wr is None and window == "all" and segment == "real":
        _wr = stats.get("winRate")
    _pf = block.get("profitFactor")

    def _pct_of_equity(v: Any) -> float | None:
        if v is None or not equity_val:
            return None
        try:
            return float(v) / float(equity_val) * 100.0
        except (TypeError, ValueError, ZeroDivisionError):
            return None

    realized_pct = _pct_of_equity(_pnl)
    unreal_pct = _pct_of_equity(open_upnl) if open_known else None

    # ── The six cards (2-up × 3 — readable on a phone) ─────────────────────
    c1, c2 = st.columns(2)
    c1.metric("Total equity", equity_str)
    c2.metric("Open trades", len(seg_open))
    c3, c4 = st.columns(2)
    c3.metric(f"Realized P&L · {win_label}", fmt_usd(_pnl),
              delta=(f"{realized_pct:+.2f}%" if realized_pct is not None else None))
    c4.metric("Unrealized P&L",
              _upnl_metric(open_upnl, open_known, open_unk),
              delta=(f"{unreal_pct:+.2f}%" if unreal_pct is not None else None))
    c5, c6 = st.columns(2)
    c5.metric(f"Win rate · {win_label}", fmt_pct(_wr))
    c6.metric("Profit factor", fmt_num(_pf) if _pf is not None else "—")

    if eq_missing:
        st.caption(f"⚠️ {eq_missing} {seg_name} account(s) without a tracked "
                   "balance snapshot (excluded from Total equity; the P&L % is "
                   "against the equity that IS tracked).")
    elif equity_val:
        st.caption(f"P&L % = return on the tracked equity above "
                   f"({fmt_usd(equity_val)}).")
    if combined:
        st.caption("Profit factor may be — for the combined (All) view "
                   "(not reconstructable from the real + paper sub-blocks).")

    # Contextual secondary line so the OTHER funding class is never invisible.
    if segment == "real":
        _other_blk, _ = _perf_for_segment(window, "paper")
        _other_tag = "🧪 Paper"
    else:  # paper / prop view → real-money one-liner
        _other_blk, _ = _perf_for_segment(window, "real")
        _other_tag = "💰 Real"
    if _other_blk:
        st.caption(
            f"{_other_tag} · {win_label} · "
            f"P&L {fmt_usd(_other_blk.get('totalPnl'))} · "
            f"win {fmt_pct(_other_blk.get('winRate'))} · "
            f"trades {_other_blk.get('totalTrades', 0)}"
        )

    # ── Open trades list (operator ask 2026-07-10) — AT THE END of the exec
    # summary, reflecting the SAME funding toggle above. A compact table of the
    # positions open right now for the selected class; the full detail cards live
    # under each chart in the monitor below.
    _render_exec_open_trades(seg_open, segment)


def _render_exec_open_trades(seg_open: list[dict], segment: str) -> None:
    """Compact open-trades table closing out the executive summary. Rows are the
    already funding-class-filtered open positions; uPnL renders "—" (never a fake
    $0) when the broker value is unavailable. Prop rows are the mark-price
    estimate (labelled). Empty state names the class so it never reads as broken."""
    seg_word = _FUNDING_SEG_NAME.get(segment, segment)
    st.markdown(f"**Open trades · {seg_word}**")
    if not seg_open:
        st.caption(f"No open {seg_word} trades right now.")
        return
    rows = _sort_recent(list(seg_open), "open")

    def _upnl_cell(p: dict) -> str:
        v, known = _open_upnl(p)
        return fmt_usd(v) if known else "—"

    tbl = pd.DataFrame([
        {
            "Symbol": p.get("symbol") or "—",
            "Side": str(p.get("side", "")).upper() or "—",
            "Qty": p.get("qty", "—"),
            "Entry": p.get("entryPrice", "—"),
            "Strategy": p.get("pattern") or "—",
            "Account": p.get("account") or "—",
            "uPnL": _upnl_cell(p),
            "Age": _fmt_duration(p.get("openedAt")) or "—",
        }
        for p in rows
    ])
    st.dataframe(tbl, hide_index=True, use_container_width=True)
    if segment == "prop":
        st.caption("🏦 Prop uPnL is a dashboard mark-price estimate (no broker "
                   "feed) — never blended into real-money or paper totals.")


def _render_overview_fleets(stats: dict) -> None:
    """The fleet-health + promotion-readiness block — moved BELOW the live-trades
    monitor (operator ask 2026-07-09): strategy fleet + ML fleet counts +
    best/worst strategy + promotion readiness. (The per-symbol asset-class P&L
    breakdown stays ABOVE the monitor with the exec cards — operator ask, it was
    never part of the 'move below' set.)"""
    strat_payload, _ = _fetch("/api/bot/strategies")
    strat_payload = strat_payload if isinstance(strat_payload, dict) else {}
    strategies = strat_payload.get("strategies") or []

    # ── Strategy fleet + ML fleet health ───────────────────────────────────
    wall = _exec_perf_window("all")
    with st.container():
        st.markdown("**Strategy fleet**")
        n_live = sum(1 for x in strategies
                     if str(x.get("execution") or "live").lower() == "live"
                     and x.get("loaded"))
        n_shadow = sum(1 for x in strategies
                       if str(x.get("execution") or "").lower() == "shadow")
        n_stale = sum(1 for x in strategies if x.get("enabled", True)
                      and x.get("loaded") and not x.get("running"))
        n_off = sum(1 for x in strategies
                    if not x.get("enabled", True) or not x.get("loaded"))
        sc = st.columns(4)
        sc[0].metric("Live", n_live)
        sc[1].metric("Shadow", n_shadow)
        sc[2].metric("Stale", n_stale)
        sc[3].metric("Off", n_off)
        per_strat = (wall.get("perStrategy") if wall else None) or []
        graded = [r for r in per_strat if r.get("totalPnl") is not None]
        if graded:
            best = max(graded, key=lambda r: r["totalPnl"])
            worst = min(graded, key=lambda r: r["totalPnl"])
            st.caption(
                f"🥇 Best: **{best.get('name', '?')}** {fmt_usd(best.get('totalPnl'))} · "
                f"🥉 Worst: **{worst.get('name', '?')}** {fmt_usd(worst.get('totalPnl'))}"
            )
        else:
            st.caption("Best / worst strategy: — (no per-strategy P&L yet).")
    with st.container():
        st.markdown("**ML fleet**")
        reg, reg_err = _fetch("/api/bot/ml/registry")
        rows_reg = (reg or {}).get("rows", []) if not reg_err else []

        def _stage_of(r: dict) -> str:
            return str(r.get("target_deployment_stage") or r.get("stage") or "").lower()
        n_adv = sum(1 for r in rows_reg
                    if _stage_of(r) in ("advisory", "limited_live", "live_approved"))
        n_sh = sum(1 for r in rows_reg if _stage_of(r) == "shadow")
        n_cand = sum(1 for r in rows_reg
                     if _stage_of(r) in ("candidate", "research_only", "backtest_approved"))
        n_dis = sum(1 for r in rows_reg
                    if _stage_of(r) in ("", "offline", "disabled", "parked"))
        mc = st.columns(4)
        mc[0].metric("Advisory", n_adv)
        mc[1].metric("Shadow", n_sh)
        mc[2].metric("Candidate", n_cand)
        mc[3].metric("Disabled", n_dis)
        last_train = None
        sess, serr = _fetch("/api/bot/ml/sessions")
        for srow in ((sess or {}).get("sessions", []) if not serr else []):
            tsv = srow.get("ts")
            if tsv and (last_train is None or str(tsv) > str(last_train)):
                last_train = tsv
        if last_train is None:
            cyc, cerr = _fetch("/api/bot/ml/cycle?limit=50")
            for crow in ((cyc or {}).get("rows", []) if not cerr else []):
                tsv = crow.get("ts")
                if tsv and (last_train is None or str(tsv) > str(last_train)):
                    last_train = tsv
        st.caption(f"Last training: {last_train or '—'}"
                   + ("" if rows_reg else " · registry unavailable"))

    # ── Promotion readiness (models soaking/ready + strategy M7 verdicts) ──
    with st.container():
        _render_readiness_block(strategies)


def _render_strategy_snapshot(frame: pd.DataFrame, hours: int = 24,
                              win_label: str = "24h") -> None:
    """Compact per-strategy line for the Overview snapshot. The per-strategy
    trade count is over the page's chosen window (``hours``); the lifetime
    Trades / Win% / P&L come straight from the strategy's bot stats."""
    data, err = _fetch("/api/bot/strategies")
    strategies = (data or {}).get("strategies") or []
    if err or not strategies:
        st.caption("Strategy data unavailable.")
        return
    rows = []
    for strat in strategies:
        name = strat.get("name", "")
        sstats = strat.get("stats") or {}
        tW = (_summary_window(_filter_strategy(frame, name), hours)["trades"]
              if not frame.empty else 0)
        rows.append({
            "Strategy": name,
            win_label: tW,
            "Trades": sstats.get("total_trades", 0),
            "Win %": sstats.get("win_rate_pct"),
            "P&L $": sstats.get("total_pnl"),
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)


def _news_sentiment(records: list, hours: float) -> tuple[float | None, int]:
    """Mean `adjustment` (net news sentiment ∈ [-1,1], +=bullish) over records
    within the last `hours`, **counting only records that actually scored news**
    (`item_count > 0`), plus that scored count.

    Records with `item_count == 0` are no-ops ("all news items stale or
    irrelevant", or a symbol with no configured query → no feed) — including
    their `adjustment: 0.0` in the mean dilutes the real signal to ~0.00 and
    inflates the "scored signals" count (the card looked unwired). They're
    excluded here so the read reflects genuinely-scored news only. None when no
    record scored any news in the window."""
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)
    vals = []
    for r in records or []:
        ts, adj = r.get("ts"), r.get("adjustment")
        if ts is None or adj is None:
            continue
        try:
            if int(r.get("item_count") or 0) <= 0:
                continue  # no news actually scored — skip the no-op
        except (TypeError, ValueError):
            continue
        try:
            t = dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            if t.tzinfo is None:
                t = t.replace(tzinfo=dt.timezone.utc)
        except ValueError:
            continue
        if t >= cutoff:
            try:
                vals.append(float(adj))
            except (TypeError, ValueError):
                pass
    return (sum(vals) / len(vals), len(vals)) if vals else (None, 0)


def _sentiment_tag(avg: float | None) -> str:
    """Render an avg sentiment as a colored +/- tag (news is a factor, not y/n).
    Small-but-real reads get 3 decimals so a genuine ~+0.005 tilt isn't shown as
    a misleading flat ``+0.00``."""
    if avg is None:
        return "—"
    if avg > 0.10:
        return f"🟢 +{avg:.2f}"
    if avg < -0.10:
        return f"🔴 {avg:.2f}"
    if avg == 0:
        return "⚪ 0.00"
    return f"⚪ {avg:+.3f}"  # near-neutral but non-zero: show the real tilt


def _render_notification_banner(*, alerts_only: bool = False) -> None:
    """Render the system-notification banner from ``/api/bot/notifications``.

    Can't-miss conditions the operator wants surfaced at the top of the app
    (NOT routine pings): trainer_down / account_down (severity ``alert``) and a
    recently-opened-trades info line (``trade_open``). Best-effort — a missing
    endpoint (older bot) or any fetch error renders nothing (graceful
    degradation, never a page crash).

    ``alerts_only`` → render only ``severity == "alert"`` banners (used on the
    non-Overview sections so the trainer/account-down alerts stay visible
    everywhere without repeating the info-level trade-open line off Overview).
    """
    payload, err = _fetch("/api/bot/notifications")
    if err or not isinstance(payload, dict):
        return
    banners = payload.get("banners") or []
    if not isinstance(banners, list):
        return
    for b in banners:
        if not isinstance(b, dict):
            continue
        sev = b.get("severity")
        if alerts_only and sev != "alert":
            continue
        msg = b.get("message") or ""
        detail = b.get("detail")
        body = f"**{msg}**"
        if detail:
            body += f"\n\n{detail}"
        if sev == "alert":
            st.error("🔴 " + body)
        elif sev == "warning":
            st.warning("🟠 " + body)
        else:
            st.info(body)


def _render_overview_glance() -> None:
    """Cross-link nav row + the latest-system-report and news-sentiment glance
    cards — moved BELOW the live-trades monitor (operator ask 2026-07-09)."""
    # Cross-links — one compact row jumping to the detail pages.
    nav1, nav2, nav3 = st.columns(3)
    with nav1:
        if st.button("Open Trades log →", key="ov_nav_trades",
                     use_container_width=True):
            _goto("Trades")
    with nav2:
        if st.button("Open Positions →", key="ov_nav_positions",
                     use_container_width=True):
            _goto("Positions")
    with nav3:
        if st.button("View Strategies →", key="ov_nav_strategies",
                     use_container_width=True):
            _goto("Strategies")

    # Glance cards: latest system-report + news layer — summary here, full
    # detail one click away (the overview→drill-down principle).
    rc, nc = st.columns(2)
    with rc:
        with st.container(border=True):
            st.markdown("**📊 Latest system report**")
            ridx, rerr = _fetch("/api/bot/reports?limit=1")
            latest = ((ridx or {}).get("reports") or [None])[0]
            if rerr or latest is None:
                st.caption("No reports yet — run `/system-report`." if not rerr else rerr)
            else:
                dot = _REPORT_GRADE_DOT.get(str(latest.get("roll_up_grade")).lower(), "")
                st.caption(
                    f"{dot} {latest.get('roll_up_grade') or '—'} · {latest.get('window') or '—'} · "
                    f"{(latest.get('generated_at') or '—')[:16].replace('T', ' ')}"
                )
                st.caption((latest.get("headline") or "—")[:160])
            if st.button("Open full report →", key="ov_card_reports",
                         use_container_width=True):
                _goto("Reports")
    with nc:
        with st.container(border=True):
            st.markdown("**📰 News — market sentiment**")
            ndata, nerr = _fetch("/api/bot/news/recent?limit=500")
            if nerr:
                st.caption(nerr)
            elif not (ndata or {}).get("present"):
                st.caption("Not active yet (source-driven: NEWS_SOURCE=rss / newsapi+key).")
            else:
                recs = (ndata or {}).get("records") or []
                a24, _ = _news_sentiment(recs, 24)
                a7, _ = _news_sentiment(recs, 24 * 7)
                a30, scored30 = _news_sentiment(recs, 24 * 30)
                # Total signals checked in 30d (incl. the no-relevant-news no-ops)
                # for honest "X scored of Y checked" context.
                cutoff30 = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30)
                total30 = 0
                for r in recs:
                    try:
                        t = dt.datetime.fromisoformat(str(r.get("ts")).replace("Z", "+00:00"))
                        if (t.tzinfo and t or t.replace(tzinfo=dt.timezone.utc)) >= cutoff30:
                            total30 += 1
                    except (ValueError, TypeError, AttributeError):
                        pass
                st.caption(
                    f"Avg sentiment (scored news) · 24h {_sentiment_tag(a24)} · "
                    f"7d {_sentiment_tag(a7)} · 30d {_sentiment_tag(a30)}"
                )
                if scored30 == 0:
                    st.caption(
                        f"Layer active — but **0 of {total30}** signals had relevant news "
                        "in 30d (symbols without a configured query never score). "
                        "Reductive sizing factor (−1…+1), not a y/n veto."
                    )
                else:
                    bias = ("bullish" if (a7 or 0) > 0.10 else
                            "bearish" if (a7 or 0) < -0.10 else "neutral")
                    st.caption(
                        f"Market read: **{bias}** over 7d · **{scored30} scored** of "
                        f"{total30} signals/30d. Reductive sizing factor (−1…+1), "
                        "not a y/n veto."
                    )
                # Clickable ticker of the top source articles the layer read
                # (top_items; highest-|score| first, dedup'd). Skips silently on
                # a bot predating the field.
                _hl: dict[str, dict] = {}
                for r in recs:
                    for it in (r.get("top_items") or []):
                        h = str(it.get("headline") or "").strip()
                        if not h:
                            continue
                        key = str(it.get("url") or "").strip() or h
                        sc = abs(float(it.get("score") or 0.0))
                        if key not in _hl or sc > _hl[key]["_abs"]:
                            _hl[key] = {"headline": h, "url": it.get("url") or "", "_abs": sc}
                if _hl:
                    for it in sorted(_hl.values(), key=lambda x: x["_abs"], reverse=True)[:4]:
                        _lbl = it["headline"][:80]
                        if it["url"]:
                            st.caption(f"🔗 [{_lbl}]({it['url']})")
                        else:
                            st.caption(f"• {_lbl}")
            if st.button("Open News →", key="ov_card_news",
                         use_container_width=True):
                _goto("News")


def page_overview(stats: dict | None, stats_err: str | None) -> None:
    st.header("Overview")
    # Can't-miss system conditions (trainer down / broker account down /
    # recently-opened trades) — full banner at the very top of Overview.
    _render_notification_banner()
    if stats_err:
        st.warning(f"Stats endpoint error: {stats_err}")
    s  = stats or {}
    vm = s.get("vmHealth") or {}

    # ── THE one toggle — Real money / Paper / Prop drives the WHOLE page ───────
    # (exec summary, open-trades list, asset breakdown, calendar, live monitor,
    # 24h scorecard, P&L curve, per-strategy line, open-positions table). This is
    # the single funding-class control the operator asked for (2026-07-10): one
    # toggle at the top, everything below reflects it. Defaults to Real money;
    # window to 24h. Mobile-friendly: segmented_control with a radio fallback.
    st.caption("One toggle for the whole tab — real money, paper, or prop — "
               "plus the time window.")
    ov_segment, ov_win_label, ov_window = _funding_bar(
        "ov_segment", "ov_window", win_index=0)
    st.divider()

    # ── Executive ("CEO") summary band — at-a-glance system health + business
    # performance for the chosen funding class + window. Real / paper / prop are
    # never blended into one number.
    _render_exec_summary(s, ov_segment, ov_win_label, ov_window)
    # Segment word reused by the snapshot section below.
    seg_word = _FUNDING_SEG_WORD.get(ov_segment, ov_segment)
    _seg_name = _FUNDING_SEG_NAME.get(ov_segment, ov_segment)
    st.divider()

    # ── P&L by asset class (item 2) — stays with the exec cards, ABOVE the
    # monitor. Authoritative /performance perAssetClass (matches the exec card).
    _render_asset_class_symbol_breakdown(ov_segment, ov_win_label, ov_window,
                                         seg_note=_seg_name)
    st.divider()

    # P&L calendar — driven by the ONE top toggle now (its own separate toggle
    # was removed 2026-07-10). Full closed-trade history (NOT windowed).
    _render_overview_calendar(ov_segment)
    st.divider()

    # ── Live charts (top of page) ──────────────────────────────────────────────
    # One chart per ACTIVE symbol (anything a strategy is paper/live-trading,
    # enumerated live via _discover_symbols()). Symbols with an OPEN POSITION are
    # floated to the top so what's at risk right now is seen first; the rest keep
    # config-declaration order. A single interval selector drives every chart.
    # include_paper=true so PAPER open trades (e.g. IBKR ib_paper MGC/MHG,
    # demo bybit_1) also render on the charts — their entry/SL/TP lines and
    # live PnL — not just real-money positions. The per-symbol summary line
    # below tags paper rows so they read clearly as non-real-money.
    _rp_positions, _ = _fetch("/api/bot/positions?include_paper=true")
    _rp_positions = _rp_positions or []
    # Live PROP trades (Breakout manual-bridge) ride the SAME monitor. Prop has
    # no broker feed, so these come from the outbound 'filled' tickets shaped
    # into position-like rows with a mark-price uPnL estimate (accountClass=
    # 'prop'). Empty (→ no change) when the prop endpoints aren't deployed or
    # there's no open prop trade.
    prop_positions = _prop_open_positions()
    # The ONE top toggle governs the monitor too: show ONLY the selected funding
    # class's live trades + charts (real / paper / prop), never a blend.
    positions = _segment_filter_rows(_rp_positions + prop_positions, ov_segment)
    # Working PROP orders — a limit/pending order PLACED on the terminal but NOT
    # filled yet. No position and no P&L: kept OUT of `positions`, rendered in
    # their own "Working orders" section + a dashed LIMIT line on the chart. Only
    # relevant to the Prop view.
    working_orders = _prop_working_orders() if ov_segment == "prop" else []
    ov_symbols = _overview_chart_symbols(positions)
    # A prop symbol the bot isn't otherwise config-trading (so _discover_symbols
    # misses it) still needs a chart — float any such open / working-order
    # symbol to the top.
    for _pp in positions + working_orders:
        _ps = str(_pp.get("symbol") or "").upper()
        if _ps and _ps not in ov_symbols:
            ov_symbols.insert(0, _ps)

    # Organize the live-trades monitor by strategy / account / asset group /
    # symbol and isolate one group. Focus narrows BOTH the charts shown (to the
    # symbols carrying the isolated trades) and the open-position rows under
    # each chart. Driven by the live open positions, so the focus choices are
    # exactly what's at risk right now.
    st.markdown("**Live trades monitor**")
    ov_dim, ov_focus = _organize_controls("ov_live_org", positions)
    focus_positions = _apply_focus(positions, ov_dim, ov_focus)
    focus_working = _apply_focus(working_orders, ov_dim, ov_focus)
    if ov_focus is not None:
        ov_symbols = _focus_symbols(ov_symbols, focus_positions, ov_dim, ov_focus)
        st.caption(f"Focused on **{_group_label(ov_focus, ov_dim)}** · "
                   + _open_group_caption(focus_positions))

    ov_interval = st.selectbox(
        "Interval", CHART_INTERVALS,
        index=CHART_INTERVALS.index("15m") if "15m" in CHART_INTERVALS else 0,
        key="ov_interval",
    )

    # Trade-context overlays are symbol-agnostic on the wire — fetch each once
    # and let render_tv_chart filter per symbol, rather than re-fetching per chart.
    sig_data, _ = _fetch("/api/bot/signals")
    # include_paper=true so PAPER closed-trade markers render on the charts too
    # (the charts already draw paper open positions) — markers are visual
    # context, not a real-money aggregate, so mixing classes here is fine.
    trade_data, _ = _fetch(
        f"/api/bot/trades/closed?limit={DEFAULT_LIMIT}&include_paper=true")

    # Order-package join for the per-symbol expandable trade rows (the live
    # trades monitor). Fetched ONCE here, not per chart — render_tv_chart and the
    # rows below reuse it. _order_package_map keys by linkedTradeId.
    _ov_op_payload, _ = _fetch(
        "/api/bot/order-packages?" + urlencode({"limit": 50, "include_paper": "true"}))
    ov_op_map_top = _order_package_map(_ov_op_payload)
    # Prop trades aren't in order_packages the same way (no linked live trade),
    # so synthesize a minimal package per prop row keyed by its id — the card's
    # "Decision & reasoning" then surfaces the exact ticket message (the
    # assistant's decision output: entry/SL/TP + logic) instead of "no package".
    for _pp in prop_positions:
        _pid = str(_pp["id"]) if _pp.get("id") is not None else None
        _tk = _pp.get("_prop_ticket") or {}
        if _pid and _pid not in ov_op_map_top:
            ov_op_map_top[_pid] = {
                "status": _tk.get("status") or "filled",
                "signalLogic": _tk.get("message"),
                "meta": {},
                "confidence": None,
            }

    def _pos_row_label(p: dict) -> str:
        # Expander-row label for one open position: a clickable one-liner that
        # carries the at-a-glance facts (side, qty@entry, strategy, account,
        # live uPnL, ⏱️ how long it's been live) and opens to the full card.
        # uPnL "—" (not a fake $0) when the broker value is unavailable; paper
        # rows tagged 🧪 so a mixed paper+real symbol reads clearly. pattern is
        # nullable per the API contract → "?" fallback.
        side = str(p.get("side", "")).upper()
        dot = ("🟢" if side in ("BUY", "LONG")
               else "🔴" if side in ("SELL", "SHORT") else "⚪")
        qty = p.get("qty", "?")
        entry = p.get("entryPrice", "?")
        strat = p.get("pattern") or "?"
        acct = p.get("account") or "?"
        _cls = _row_account_class(p)
        tag = (" · 🧪 paper" if _cls == "paper"
               else " · 🏦 prop" if _cls == "prop" else "")
        upnl, known = _open_upnl(p)
        pnl_s = fmt_usd(upnl) if known else "—"
        dur = _fmt_duration(p.get("openedAt"))
        dur_s = f" · ⏱️ {dur}" if dur else ""
        return (f"{dot} {side} {qty} @ {entry} · {strat} · {acct} · "
                f"uPnL {pnl_s}{dur_s}{tag}")

    if not ov_symbols:
        st.caption("No active symbols — the bot isn't trading any instrument.")
    else:
        # Symbol PICKER instead of st.tabs (2026-07-09): Streamlit tab PANELS
        # drop every element rendered AFTER the tabs block on narrow mobile
        # viewports — so the fleets / report / news / snapshot below the monitor
        # rendered on desktop but were BLANK on phones. A segmented-control /
        # radio picker keeps the swipe-through, one-chart-at-a-time feel WITHOUT
        # the tab-panel layout bug. Symbols with an open position / working order
        # float to the front (ov_symbols is already so ordered) + carry a 🟢/🟠
        # badge in the picker.
        _open_syms = {p.get("symbol") for p in focus_positions}
        _working_syms = {w.get("symbol") for w in focus_working}

        def _ov_tab_label(s: str) -> str:
            if s in _open_syms:
                return f"{s} 🟢"
            if s in _working_syms:
                return f"{s} 🟠"
            return s

        def _render_symbol_panel(ov_symbol: str) -> None:
            # focus_positions == positions when no group is isolated, else
            # just the isolated group's legs. Newest-open first.
            sym_positions = _sort_recent(
                [p for p in focus_positions if p.get("symbol") == ov_symbol],
                "open")
            # Working (placed) orders on this symbol — chart overlay only
            # (never a P&L leg); listed in the Working-orders section below.
            sym_working = [w for w in focus_working
                           if w.get("symbol") == ov_symbol]
            df, candles_err = _fetch_candles(ov_symbol, ov_interval, limit=1000)

            # Chart FIRST (chart on top, tickets under). Working orders ride the
            # same positions overlay (dashed LIMIT line, no ENTRY marker) but
            # are NOT in the P&L metrics below.
            if candles_err:
                st.warning(f"{ov_symbol}: candles unavailable: {candles_err}")
            elif df is None or df.empty:
                st.caption(f"{ov_symbol}: no candle data.")
            else:
                render_tv_chart(df, sig_data, trade_data, ov_symbol,
                                positions=sym_positions + sym_working)
                st.caption(
                    f"{ov_symbol} · {ov_interval} · candles from the bot's "
                    f"exchange feed (yfinance fallback) · overlay toggles + "
                    f"fullscreen on the chart · updates on tap / ↻ Refresh"
                )

            # Tickets UNDER the chart: per-class PnL metrics + the expandable
            # trade cards for this symbol's open legs. NEVER blend the three
            # funding classes — real-money is the primary "Live PnL";
            # paper/prop each ride as their own labeled metric.
            if sym_positions:
                real_legs = [p for p in sym_positions if _is_real_money(p)]
                paper_legs = [p for p in sym_positions
                              if _row_account_class(p) == "paper"]
                prop_legs = [p for p in sym_positions
                             if _row_account_class(p) == "prop"]
                _specs = [("Live PnL", real_legs)]
                if paper_legs:
                    _specs.append(("🧪 Paper PnL", paper_legs))
                if prop_legs:
                    _specs.append(("🏦 Prop PnL", prop_legs))
                _cols = st.columns([1] * len(_specs) + [max(1, 4 - len(_specs))])
                _tot_unk = 0
                for _ci, (_lbl, _legs) in enumerate(_specs):
                    _pnl, _unk = _sum_upnl(_legs)
                    _tot_unk += _unk
                    if _legs:
                        _cols[_ci].metric(
                            f"{_lbl} · {ov_symbol}",
                            _upnl_metric(_pnl, len(_legs) - _unk, _unk),
                            delta=round(_pnl, 2) if (len(_legs) - _unk) else None)
                    else:
                        _cols[_ci].metric(f"{_lbl} · {ov_symbol}", "—")
                _cols[-1].caption(
                    f"{len(sym_positions)} open "
                    f"{'leg' if len(sym_positions) == 1 else 'legs'} — "
                    "tap a trade below to expand its full card.")
                if prop_legs:
                    st.caption("🏦 Prop P&L is a dashboard mark-price estimate "
                               "(no broker feed) — tracked separately, never "
                               "blended into real-money or paper totals.")
                _unk_cap = _upnl_caption(_tot_unk)
                if _unk_cap:
                    st.caption("⚠️ " + _unk_cap)

                # Clickable rows — one expander per open position; expands in
                # place to the SAME full detail card the Positions tab renders.
                for _i, _p in enumerate(sym_positions):
                    _render_trade_card(
                        _p, is_open=True, op_map=ov_op_map_top,
                        signals=sig_data,
                        expander_label=_pos_row_label(_p),
                        key_prefix=f"ovsym_{ov_symbol}_{_i}_",
                    )
            else:
                st.caption("No open position on this symbol — chart only.")

        _labels = [_ov_tab_label(s) for s in ov_symbols]
        _picked = _segmented_or_radio(
            "Symbol", _labels, index=0, key="ov_monitor_sym",
            help="Pick a symbol to chart. (Replaces the old tab bar, which hid "
                 "everything below the monitor on mobile.)")
        _idx = _labels.index(_picked) if _picked in _labels else 0
        _render_symbol_panel(ov_symbols[_idx])

    # ── Working orders (placed — awaiting fill) ────────────────────────────────
    # Prop limit/pending orders placed on the terminal that haven't tripped yet:
    # no position, no P&L. Kept strictly apart from the live-trades P&L above —
    # they appear here (and as a dashed amber LIMIT line on the chart) so the
    # operator can see what's working without it masquerading as an open trade.
    if focus_working:
        st.markdown("**🟠 Working orders (placed — awaiting fill)**")
        st.caption(
            "Limit / pending prop orders placed on the terminal that haven't "
            "filled yet — **no position and no P&L** until the limit trips. Each "
            "shows as a dashed amber LIMIT line on its chart above; when it "
            "fills it moves up into the live-trades monitor."
        )
        for _i, _w in enumerate(_sort_recent(focus_working, "open")):
            _render_working_order_card(
                _w, expander_label=_working_row_label(_w),
                key_prefix=f"ovwo_{_i}_")

    st.divider()

    # ── Below the live-trades monitor (operator ask 2026-07-09): strategy fleet
    # + promotion readiness + the latest analyst read + the latest-system-report
    # and news glance cards. (Asset-class breakdown + calendar stay ABOVE the
    # monitor; only these five items were asked to move below.)
    _render_overview_fleets(s)
    st.divider()

    # M13 S1: the latest AI-analyst summary (silent no-op until the generator
    # has written its first cache file).
    _render_overview_insight_card()

    # Cross-links + latest-report + news-sentiment glance cards.
    _render_overview_glance()
    st.divider()

    # ââ Snapshot (below the chart) ââââââââââââââââââââââââââââââââââââââââââââââ
    # Headline KPIs now live in the header band at the TOP of the page (real
    # primary / paper secondary). This section is the supporting detail only:
    # the last-24h scorecard, system health, and the 30-day realised-P&L chart.
    # Supporting detail — all driven by the page's funding toggle + window.
    # Prop lives in its own journal (not /trades/closed), so source its closed
    # frame from the prop fills; real/paper come from the analytics frame.
    if ov_segment == "prop":
        odf = _prop_closed_frame()
    else:
        odf_all, _, _ = _analytics_frame(include_paper=True)
        odf = _segment_filter_frame(odf_all, ov_segment)
    # Window → hours for the scorecard. "All" uses the full analytics lookback.
    ov_hours = {"24h": 24, "7d": 7 * 24, "30d": 30 * 24,
                "all": ANALYTICS_LOOKBACK_DAYS * 24}[ov_window]
    sW = _summary_window(odf, ov_hours)

    left, right = st.columns(2)
    with left:
        st.markdown(f"**Scorecard · {ov_win_label} ({seg_word})**")
        a1, a2 = st.columns(2)
        a1.metric("Trades", sW["trades"])
        a2.metric("Wins", sW["wins"])
        a3, a4 = st.columns(2)
        a3.metric("Losses", sW["losses"])
        a4.metric("P&L", fmt_usd(sW["pnl"]))
        st.markdown("**System health**")
        h1, h2 = st.columns(2)
        h1.metric("CPU",    fmt_pct(vm.get("cpu")))
        h2.metric("Memory", fmt_pct(vm.get("memory")))
        st.metric("Disk",   fmt_pct(vm.get("disk")))
    with right:
        st.markdown(f"**Realised P&L curve · {ov_win_label} ({seg_word})**")
        # Cumulative realised P&L over the segment+window-filtered closed
        # trades — segment-consistent (the /api/pnl/history route is real-only,
        # so we drive this from the same frame the scorecard uses).
        win_frame = (odf[odf["ts"] >= (dt.datetime.utcnow()
                                       - dt.timedelta(hours=ov_hours))]
                     if not odf.empty else odf)
        fig30 = build_cumulative_pnl_fig(win_frame, height=230)
        if fig30 is not None:
            st.plotly_chart(fig30, use_container_width=True,
                            config={"displayModeBar": False})
        else:
            st.caption(f"No realised {seg_word} P&L in the {ov_win_label.lower()}.")

    pos_col, strat_col = st.columns(2)
    with pos_col:
        st.markdown(f"**Open positions ({seg_word})**")
        # Filtered to the chosen funding class. Prop comes from the prop tickets
        # (no /positions feed); real/paper from /positions.
        if ov_segment == "prop":
            positions_unfiltered = _prop_open_positions()
            positions_all = positions_unfiltered
        else:
            positions_all, _ = _fetch("/api/bot/positions?include_paper=true")
            positions_unfiltered = positions_all or []
            positions_all = _segment_filter_rows(positions_unfiltered, ov_segment)
        # Honour the live-trades monitor's organize/focus selection here too, so
        # isolating a group narrows this table to the same set.
        positions_all = _apply_focus(positions_all, ov_dim, ov_focus)
        if positions_all:
            # Default: newest-open first. When organized, cluster by group while
            # keeping newest-open order within each group (stable sort).
            pos_sorted = _sort_recent(positions_all, "open")
            if ov_dim != "none":
                _gorder = {k: i for i, (k, _v) in
                           enumerate(_group_rows(positions_all, ov_dim))}
                pos_sorted = sorted(
                    pos_sorted,
                    key=lambda p: _gorder.get(_row_group_key(p, ov_dim), 99),
                )
            pdf = pd.DataFrame(pos_sorted)
            # Per-row uPnL straight from the API's multiplier-aware
            # unrealizedPnl (broker-truth or markprice_local; ict-trading-bot
            # #3761). No client-side recompute — the old (price-entry)*qty was
            # multiplier-blind for futures (BL-20260616-DASH-UPNL-MULTIPLIER).
            # A leg whose value is "unavailable" renders "—", never a fake $0.
            def _upnl_cell(p: dict) -> str:
                v, known = _open_upnl(p)
                return fmt_usd(v) if known else "—"
            pdf["uPnL"] = [_upnl_cell(p) for p in pos_sorted]
            # Clear paper/real label derived from accountClass (isDemo fallback).
            pdf["Type"] = [
                "🧪 paper" if _row_account_class(p) == "paper" else "real"
                for p in pos_sorted
            ]
            cmap = {"symbol": "Symbol", "side": "Side", "qty": "Qty",
                    "entryPrice": "Entry", "uPnL": "uPnL",
                    "pattern": "Strategy", "account": "Account", "Type": "Type"}
            # Add a Group column when organized by asset class (the one grouping
            # not already a column) so the cluster is legible.
            if ov_dim == "asset":
                pdf["Group"] = [_group_label(_row_asset_class(p), "asset")
                                for p in pos_sorted]
                cmap["Group"] = "Group"
            cols = [c for c in cmap if c in pdf.columns]
            st.dataframe(pdf[cols].rename(columns=cmap), hide_index=True,
                         use_container_width=True)

            # One full detail card per open position — the SAME rich card the
            # Positions tab renders inline (_render_trade_card uses st.container
            # and nests an st.expander for the raw package, so it can't be
            # wrapped in another expander — render the cards directly, exactly
            # like the Positions tab does). pos_sorted puts real-money legs
            # first, paper after; the card header labels each.
            _ov_op_path = "/api/bot/order-packages?" + urlencode(
                {"limit": 50, "include_paper": "true"})
            _ov_sig_path = "/api/bot/signals"
            _ov_joins = _fetch_parallel([_ov_op_path, _ov_sig_path], timeout=6.0)
            ov_op_map = _order_package_map(
                _ov_joins.get(_ov_op_path, (None, None))[0])
            ov_signals = _ov_joins.get(_ov_sig_path, (None, None))[0] or []
            # Full detail cards are heavy on a phone — collapse behind a toggle
            # (the card itself uses containers/expanders, so it can't be wrapped
            # in an st.expander; a checkbox is the nesting-safe gate).
            if st.checkbox("Show full open-trade detail cards",
                           key="ov_open_detail"):
                for p in pos_sorted:
                    _render_trade_card(
                        p, is_open=True, op_map=ov_op_map, signals=ov_signals,
                        key_prefix="ovsnap_",
                    )
        else:
            # Smart empty state — if another segment has open positions, name it
            # + offer a one-tap jump (drives the Overview page's own segment).
            _empty_segment_hint(
                positions_unfiltered, ov_segment, seg_widget_key="ov_segment",
                noun="open positions",
            )
    with strat_col:
        st.markdown(f"**Strategies · {ov_win_label} ({seg_word})**")
        _render_strategy_snapshot(odf, ov_hours, ov_win_label)


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
    # include_paper=true so a paper open trade on this symbol (e.g. IBKR
    # ib_paper MGC/MHG) draws its entry/SL/TP lines on the chart too.
    rows, err = _fetch("/api/bot/positions?include_paper=true")
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
    # uPnL straight from the API's multiplier-aware unrealizedPnl
    # (broker-truth or markprice_local; ict-trading-bot #3761). Legs whose
    # value is "unavailable" are excluded from the sum (not summed as $0).
    net_pnl, net_unk = _sum_upnl(positions)
    net_known = len(positions) - net_unk
    p = positions[0]  # primary leg for the detail metrics
    side = str(p.get("side", "")).upper() or "—"
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Open legs", len(positions))
    c2.metric(
        "Live PnL", _upnl_metric(net_pnl, net_known, net_unk),
        delta=round(net_pnl, 2) if (net_known and net_pnl) else None,
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
    # include_paper=true so a paper closed trade on this symbol still draws its
    # entry/exit markers (visual context, not a real-money aggregate).
    trades, tr_err = _fetch(
        f"/api/bot/trades/closed?limit={DEFAULT_LIMIT}&include_paper=true")
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
        f"updates on tap / ↻ Refresh"
    )


def page_performance() -> None:
    st.header("Performance")
    st.caption(
        "Detailed system + per-strategy performance, plus per-symbol trade "
        "context. One toggle — real money, paper, or prop — plus a window drive "
        "the whole page; the strategy filter for the deep-dive is below."
    )
    # ── The ONE top toggle: funding class + window drive the WHOLE page ────────
    pf_segment, pf_label, pf_window = _funding_bar(
        "perf_hdr_segment", "perf_hdr_window", win_index=3)  # All default
    _pf_block, _ = _perf_for_segment(pf_window, pf_segment)
    _seg_name = _FUNDING_SEG_NAME.get(pf_segment, pf_segment)
    if _pf_block and "winRate" in _pf_block:
        _render_header_band(
            real=[
                ("Trades", _pf_block.get("totalTrades", 0)),
                ("Win rate", fmt_pct(_pf_block.get("winRate"))),
                ("Total PnL", fmt_usd(_pf_block.get("totalPnl"))),
                ("Expectancy", fmt_usd(_pf_block.get("expectancy"))),
            ],
        )
        st.caption(f"{_seg_name} · {pf_label} window, uncapped.")
        # Asset-class P&L bar for the chosen class + window — from the
        # authoritative /performance perAssetClass (matches the headline P&L).
        _render_asset_class_symbol_breakdown(
            pf_segment, pf_label, pf_window, seg_note=_seg_name)
        st.divider()
    render_trade_analytics(pf_segment)

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
        "Every configured account — the paper/real-money category, live/dry "
        "execution status, balance, PnL, and a recent-trades log. All values "
        "are read live from the bot; nothing here is hardcoded."
    )

    # Time-window picker — drives each account's realised-PnL figure, the daily
    # P&L chart, and the recent-trades log (same 24h/7d/30d/All axis as the rest
    # of the app; default 30d). Balance + open positions are point-in-time.
    acc_wlabel, acc_wslug = _window_control("acc_window", index=2)
    acc_win_days = _WINDOW_DAYS[acc_wslug]

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

    # Include paper rows so a paper account (e.g. IBKR ib_paper) shows its
    # true open-position count + unrealized PnL, not 0. Each card filters to
    # its own account id below, so real-money cards are unaffected.
    positions, _ = _fetch("/api/bot/positions?include_paper=true")
    positions = positions or []

    # Broker-truth realized ledger (bot-side committed ledger). Authoritative
    # lifetime realized for accounts whose per-row journal pnl can't be trusted
    # (netting + spot/perp + a sub-account switch ⇒ the journal under-records;
    # e.g. bybit_2). We render it next to the window's journal realized so the
    # operator sees the true figure. Best-effort: absent → the line just doesn't
    # show. Keyed by account_id.
    _bt_env, _ = _fetch("/api/bot/pnl/broker-truth")
    _broker_truth = {}
    for _r in ((_bt_env or {}).get("accounts") or []):
        if isinstance(_r, dict) and _r.get("account_id"):
            _broker_truth[_r["account_id"]] = _r

    # Surface config load errors as a banner rather than silently rendering
    # an empty/partial account roster.
    _cfg_errs = cfg.get("config_load_errors") or []
    if _cfg_errs:
        if isinstance(_cfg_errs, (list, tuple)):
            st.warning("⚠️ Config load errors:\n" + "\n".join(
                f"- {e}" for e in _cfg_errs))
        else:
            st.warning(f"⚠️ Config load errors: {_cfg_errs}")

    # ── Header band: portfolio balance + open exposure ─────────────────────
    # Real-money accounts PRIMARY (tracked balance + open count + uPnL), paper
    # SECONDARY — never blended. Prop-firm accounts are NOT real money and are
    # excluded from the real headline (they ride the "prop" sub-block).
    # Balances are the bot's tracked snapshots.
    def _acct_class(a: dict) -> str:
        return str(a.get("account_class") or "real_money").lower()
    _real_ids = {a.get("id") for a in accounts
                 if _acct_class(a) not in _NON_REAL_CLASSES}
    _paper_ids = {a.get("id") for a in accounts if _acct_class(a) == "paper"}
    _prop_ids = {a.get("id") for a in accounts if _acct_class(a) == "prop"}

    def _bal_sum(ids: set) -> tuple[float, int, int]:
        """(sum of PRESENT balances, n_present, n_missing) — a missing balance
        is excluded from the sum, never summed as 0."""
        total = 0.0
        present = missing = 0
        for i in ids:
            b = (balances.get(i) or {}).get("balance")
            if b is None:
                missing += 1
                continue
            try:
                total += float(b)
                present += 1
            except (TypeError, ValueError):
                missing += 1
        return total, present, missing

    def _bal_metric(ids: set) -> str:
        total, present, _ = _bal_sum(ids)
        return fmt_usd(total) if present else "—"

    def _open_count(ids: set) -> int:
        return sum(1 for p in positions if p.get("account") in ids)

    def _upnl_metric_for(ids: set) -> str:
        legs = [p for p in positions if p.get("account") in ids]
        total, unk = _sum_upnl(legs)
        return _upnl_metric(total, len(legs) - unk, unk)

    st.markdown("**💵 Real-money accounts**")
    _render_header_band(
        real=[
            ("Real balance", _bal_metric(_real_ids)),
            ("Open · real", _open_count(_real_ids)),
            ("uPnL · real", _upnl_metric_for(_real_ids)),
        ],
    )
    # Paper accounts get the SAME big-metric summary band as real money
    # (operator ask 2026-07-09) — was a single 🧪 caption before. Still strictly
    # separate from the real-money band (never blended).
    if _paper_ids:
        st.markdown("**🧪 Paper accounts**")
        _render_header_band(
            real=[
                ("Paper balance", _bal_metric(_paper_ids)),
                ("Open · paper", _open_count(_paper_ids)),
                ("uPnL · paper", _upnl_metric_for(_paper_ids)),
            ],
        )
    # Prop-firm accounts: kept strictly separate from real money.
    if _prop_ids:
        _pt, _pp, _pm = _bal_sum(_prop_ids)
        st.caption(
            f"🏦 Prop · balance {fmt_usd(_pt) if _pp else '—'} · "
            f"open {_open_count(_prop_ids)} · uPnL {_upnl_metric_for(_prop_ids)}"
        )
    # Caption when any real-money balance is missing from the snapshot — split
    # a FAILED broker read (api_ok=False) from a genuinely never-snapshotted
    # account, so a credential/host failure reads as an error, not "no data yet".
    def _api_failed_count(ids: set) -> int:
        n = 0
        for i in ids:
            e = balances.get(i) or {}
            if e.get("balance") is None and e.get("api_ok") is False:
                n += 1
        return n

    _r_total, _r_present, _r_missing = _bal_sum(_real_ids)
    _r_failed = _api_failed_count(_real_ids)
    if _r_failed:
        st.caption(f"⚠️ {_r_failed} real-money account(s) had a FAILED broker "
                   "balance read (excluded from the Real balance sum — not $0).")
    _r_nosnap = _r_missing - _r_failed
    if _r_nosnap > 0:
        st.caption(f"⚠️ {_r_nosnap} real-money account(s) have no tracked "
                   "balance snapshot yet (excluded from the Real balance sum).")
    st.divider()

    since_win = (dt.datetime.utcnow()
                 - dt.timedelta(days=acc_win_days)).strftime("%Y-%m-%dT%H:%M:%SZ")

    for acc in accounts:
        aid       = acc.get("id", "?")
        is_live   = bool(live_map.get(aid, False))
        exchange  = acc.get("exchange", "—")
        market    = acc.get("market_type", "—")
        strategies = acc.get("strategies") or []
        # Paper/real-money CATEGORY — orthogonal to the live/dry EXECUTION
        # mode above. Read from config's per-account ``account_class``;
        # absent ⇒ real_money (back-compat with pre-field configs).
        acct_class = str(acc.get("account_class") or "real_money").lower()
        is_paper   = (acct_class == "paper")
        class_tag  = "🧪 PAPER" if is_paper else "💵 REAL"

        _bal_entry = balances.get(aid) or {}
        bal_val = _bal_entry.get("balance")
        # Broker-read health: api_ok=False ⇒ the trader's last balance read for
        # this account FAILED (balance is then null because of the failure, not
        # because none was ever recorded) — render distinctly, never as a bare
        # "—" that looks like "no snapshot yet". None ⇒ legacy/JSON-fallback
        # envelope (no api_ok) or no snapshot.
        bal_api_ok = _bal_entry.get("api_ok")
        bal_read_failed = bal_val is None and bal_api_ok is False
        acc_positions = [p for p in positions if p.get("account") == aid]
        # uPnL straight from the API's multiplier-aware unrealizedPnl
        # (broker-truth or markprice_local; ict-trading-bot #3761). A leg whose
        # value is "unavailable" is EXCLUDED from this sum (not counted as $0);
        # the metric shows "—" when no leg has a known value.
        unrealized, unrealized_unk = _sum_upnl(acc_positions)
        unrealized_known = len(acc_positions) - unrealized_unk

        # Windowed realised-PnL history via the no-session, account-filtered
        # endpoint. Rows are `{date, pnl, trades}` — `pnl`, not `realizedPnl`
        # (renamed in S-063; the old key silently summed to zero).
        realized = None
        trades_win = 0
        ph, _ = _fetch(f"/api/pnl/history?days={acc_win_days}&account_id={aid}")
        ph = ph or []
        if ph:
            try:
                realized = sum(float(r.get("pnl") or 0) for r in ph)
                trades_win = sum(int(r.get("trades") or 0) for r in ph)
            except (TypeError, ValueError):
                realized = None

        dot = _row_dot("live" if is_live else "dry")
        label = (f"{dot}  **{aid}**  ·  {class_tag}  ·  "
                 f"{'LIVE' if is_live else 'DRY'}  ·  "
                 f"{acc_wlabel} {fmt_usd(realized)}  ·  {len(acc_positions)} open")
        with st.expander(label):
            st.caption(
                f"{'Paper-trading' if is_paper else 'Real-money'} account · "
                f"execution {'LIVE' if is_live else 'DRY'} · "
                f"{exchange} · {market} · "
                f"strategies: {', '.join(strategies) if strategies else '— (none assigned)'}"
            )
            m1, m2, m3, m4, m5 = st.columns(5)
            _bal_display = (
                "API error" if bal_read_failed
                else fmt_usd(bal_val) if bal_val is not None else "—"
            )
            m1.metric("Balance",        _bal_display)
            m2.metric(f"Realized · {acc_wlabel}", fmt_usd(realized))
            m3.metric("Unrealized",     _upnl_metric(unrealized, unrealized_known, unrealized_unk))
            m4.metric("Open trades",    len(acc_positions))
            m5.metric(f"Trades · {acc_wlabel}", trades_win)
            if bal_read_failed:
                st.caption("⚠️ Broker balance read failed — last snapshot "
                           "unavailable for this account (not $0).")
            _acc_unk_cap = _upnl_caption(unrealized_unk)
            if _acc_unk_cap:
                st.caption("⚠️ " + _acc_unk_cap)

            # Broker-truth realized (authoritative account lifetime figure) when
            # this account has a reconciliation ledger record — surfaced next to
            # the journal window figure because the live per-row pnl under-records
            # for this account (spot/perp + sub-account switch). Renders null→"—".
            _bt = _broker_truth.get(aid)
            if _bt is not None:
                _bt_real = _bt.get("realized_usd")
                _bt_fees = _bt.get("fees_usd")
                st.markdown(
                    f"**🏦 Broker-truth realized (lifetime): "
                    f"{fmt_usd(_bt_real)}**"
                    + (f"  ·  fees {fmt_usd(_bt_fees)}" if _bt_fees is not None else "")
                )
                _subs = _bt.get("sub_accounts")
                _src = _bt.get("source") or "broker export"
                _win = ""
                if _bt.get("window_start") and _bt.get("window_end"):
                    _win = f" · {_bt['window_start']}..{_bt['window_end']}"
                st.caption(
                    "Authoritative broker wallet-truth (stitched across "
                    + (f"{len(_subs)} sub-accounts" if isinstance(_subs, list) and _subs else _src)
                    + f"{_win}). The windowed **Realized** metric above is the live "
                    "journal's per-row figure, which under-records for this account; "
                    "this line is the true lifetime realized. "
                    + (_bt.get("note") or "")
                )

            fig = build_daily_pnl_fig(ph, height=220)
            if fig is not None:
                st.plotly_chart(fig, use_container_width=True,
                                config={"displayModeBar": False})
            else:
                st.caption(f"No realised P&L in the {acc_wlabel.lower()}.")

            st.markdown(f"**Recent trades · {acc_wlabel}**")
            trades, terr = _fetch(
                f"/api/bot/trades/closed?limit=100&account_id={aid}&since={since_win}"
            )
            if terr:
                st.warning(terr)
            elif not trades:
                st.caption(f"No closed trades in the {acc_wlabel.lower()}.")
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

def _trade_card_join_data() -> tuple[dict[str, dict], list[dict]]:
    """Fetch the order-package + signal join data the detail cards overlay.

    All fast journal/DB pulls now that the per-model ML scores are persisted ON
    the order package (``modelScores``) — no slow shadow-log recompile.
    order-packages carries the reasoning AND the model scores; signals adds the
    triggering-signal correlation. Fetched concurrently, time-boxed.
    """
    _op_path = "/api/bot/order-packages?" + urlencode({"limit": 50, "include_paper": "true"})
    _sig_path = "/api/bot/signals"
    _joins = _fetch_parallel([_op_path, _sig_path], timeout=6.0)
    op_map = _order_package_map(_joins.get(_op_path, (None, None))[0])
    signals = _joins.get(_sig_path, (None, None))[0] or []
    return op_map, signals


def page_positions() -> None:
    """OPEN positions only — full detail cards. Closed-trade history is the
    separate **Trades** page (split out 2026-06-20 to mirror the Android app,
    where Positions and Trades are distinct views)."""
    st.header("Positions")
    st.caption("Live OPEN positions — full detail cards. Closed-trade history "
               "lives on the separate **Trades** page. One toggle — real money, "
               "paper, or prop. (Open positions have no time window — see "
               "**Trades** for windowed history.)")

    segment = _funding_control("pos_segment")

    # ── Header band: open exposure (real PRIMARY, paper SECONDARY) ──────────
    # Computed over ALL open positions (every class), independent of the
    # segment picker, so the headline never reads as dead when only paper is on.
    _open_all, _ = _fetch("/api/bot/positions?include_paper=true")
    _open_all = _open_all or []
    # Prop is NOT real money — exclude it from the real headline (it rides the
    # prop caption below). paper / prop both kept separate from real.
    _real_open = [p for p in _open_all if _is_real_money(p)]
    # "Paper" here means the live-portfolio mirror (soak books show on the
    # Accounts page only), per the operator UI directive. S-PAPER-PORTFOLIO.
    _paper_open = [p for p in _open_all if _row_is_portfolio_paper(p)]
    _prop_open = [p for p in _open_all if _row_account_class(p) == "prop"]
    _real_upnl, _real_unk = _sum_upnl(_real_open)
    _paper_upnl, _paper_unk = _sum_upnl(_paper_open)
    _render_header_band(
        real=[
            ("Open · real", len(_real_open)),
            ("Unrealized PnL · real",
             _upnl_metric(_real_upnl, len(_real_open) - _real_unk, _real_unk)),
        ],
        paper=[
            ("open", len(_paper_open)),
            ("uPnL", _upnl_metric(_paper_upnl, len(_paper_open) - _paper_unk, _paper_unk)),
        ],
    )
    if _prop_open:
        _prop_upnl, _prop_unk = _sum_upnl(_prop_open)
        st.caption(
            f"🏦 Prop · open {len(_prop_open)} · uPnL "
            + _upnl_metric(_prop_upnl, len(_prop_open) - _prop_unk, _prop_unk)
        )
    _pos_unk_cap = _upnl_caption(_real_unk + _paper_unk)
    if _pos_unk_cap:
        st.caption("⚠️ " + _pos_unk_cap)
    st.divider()

    op_map, signals = _trade_card_join_data()

    st.subheader("Open")
    # Prop lives in its own journal (filled tickets, mark-price uPnL) — not
    # /positions. Real/paper come from /positions.
    if segment == "prop":
        rows, err = _prop_open_positions(), None
        unfiltered = rows
    else:
        rows, err = _fetch("/api/bot/positions?include_paper=true")
        unfiltered = rows or []
        rows = _segment_filter_rows(unfiltered, segment)
    if err:
        st.warning(err)
    else:
        if not rows:
            if segment == "prop":
                st.caption("No open prop trades right now.")
            else:
                # Smart empty state — if THIS segment has no open positions but
                # another does, name it + offer a one-tap jump (open positions
                # have no time window, so no widen-window jump here).
                _empty_segment_hint(
                    unfiltered, segment, seg_widget_key="pos_segment",
                    noun="open positions",
                )
        else:
            # Organize by strategy / account / asset group / symbol + isolate a
            # single group, each section captioned with its own open exposure.
            # uPnL comes straight from the API's multiplier-aware unrealizedPnl
            # (broker-truth or markprice_local) — no client-side recompute
            # (BL-20260616-DASH-UPNL-MULTIPLIER).
            dim, focus = _organize_controls("pos_org", rows)
            rows = _apply_focus(rows, dim, focus)
            if dim == "none":
                rows = _sort_recent(rows, "open")  # newest open first
                st.caption(_open_group_caption(rows))
                for p in rows:
                    _render_trade_card(
                        p, is_open=True, op_map=op_map, signals=signals,
                        key_prefix="postab_",
                    )
            else:
                for gkey, grows in _group_rows(rows, dim):
                    st.markdown(f"### {_group_label(gkey, dim)}")
                    st.caption(_open_group_caption(grows))
                    for p in _sort_recent(grows, "open"):
                        _render_trade_card(
                            p, is_open=True, op_map=op_map, signals=signals,
                            key_prefix="postab_",
                        )


def _closed_trade_picker(closed: list[dict], key: str, label: str) -> int | None:
    """Selectbox fallback/companion for opening a closed trade's full card —
    a guaranteed-discoverable alternative to the dataframe's tiny per-row
    selection checkbox (BL-20260701-TRADECARD-CLICK)."""
    return st.selectbox(
        label, [None, *range(len(closed))],
        format_func=lambda i: "—" if i is None else (
            f"{closed[i].get('symbol')} "
            f"{str(closed[i].get('side', '')).upper()} · "
            f"{closed[i].get('closedAt') or ''}"
        ),
        key=key,
    )


def page_trades() -> None:
    """Closed-trade HISTORY — the window selector + clickable rows → detail
    card. Split from Positions (open) 2026-06-20 to mirror the Android app."""
    st.header("Trades")
    st.caption("Closed-trade history. One toggle — real money, paper, or prop — "
               "plus a window; click a row for the full trade card. Open "
               "positions live on **Positions**.")

    # Mobile-friendly control bar — ONE funding toggle + window side-by-side. The
    # window uses the same 24h/7d/30d/All axis as the rest of the app (default 7d).
    segment, wlabel, wslug = _funding_bar(
        "trades_segment", "trades_window", win_index=1)
    op_map, signals = _trade_card_join_data()

    days = _WINDOW_DAYS[wslug]
    if segment == "prop":
        # Prop closed trades live in the prop journal, not /trades/closed.
        closed_unfiltered = _prop_closed_rows(wslug)
        closed = closed_unfiltered
        cerr = None
    else:
        since = (dt.datetime.utcnow() - dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        closed_raw, cerr = _fetch(
            "/api/bot/trades/closed?" + urlencode({
                "limit": ANALYTICS_MAX_ROWS, "since": since, "include_paper": "true",
            })
        )
        # Keep the UNFILTERED list (all classes, this window) so the empty-state
        # hint can count per-segment availability without a second fetch.
        closed_unfiltered = closed_raw or []
        closed = _segment_filter_rows(closed_unfiltered, segment)
    if cerr:
        st.warning(cerr)
    elif not closed:
        # Smart empty state — names what data DOES exist (other segment / wider
        # window) and offers honest one-tap jumps, instead of a bare caption.
        _empty_segment_hint(
            closed_unfiltered, segment, seg_widget_key="trades_segment",
            window_widget_key="trades_window", noun="trades closed",
            window_label=wlabel,
        )
    else:
        # Organize by strategy / account / asset group / symbol + isolate a
        # single group. The single clickable dataframe is kept (so click-a-row →
        # full card still works) — grouping clusters the rows + adds a per-group
        # performance summary table above; focus narrows to one group.
        dim, focus = _organize_controls("trades_org", closed)
        closed = _apply_focus(closed, dim, focus)
        if not closed:
            st.caption(f"No trades in the focused group for the {wlabel} window.")
            return
        if dim == "none":
            closed = _sort_recent(closed, "closed")  # newest close first
        else:
            grouped = _group_rows(closed, dim)
            # Per-group realised-performance summary (this is the "show me the
            # performance for QQQ / metals / this account" ask).
            summ = pd.DataFrame([
                {
                    _group_dim_col(dim): _group_label(gkey, dim),
                    "Trades": s["trades"], "W": s["wins"], "L": s["losses"],
                    "Win rate": fmt_pct(s["winRate"]), "P&L": fmt_usd(s["pnl"]),
                }
                for gkey, grows in grouped
                for s in (_closed_group_stats(grows),)
            ])
            st.markdown(f"**Performance by {dim if dim != 'asset' else 'asset class'}"
                        f" · {wlabel}**")
            st.dataframe(summ, hide_index=True, use_container_width=True)
            # Re-order `closed` so rows cluster by group (keeps the 1:1 index
            # mapping between the dataframe and `closed` for click-to-card);
            # newest close first within each group.
            closed = [r for _gkey, grows in grouped
                      for r in _sort_recent(grows, "closed")]
        # _format_closed_trades_df preserves row order, so the dataframe's
        # selection index maps 1:1 back to `closed` → click a row for its card.
        cdf = _format_closed_trades_df(pd.DataFrame(closed))
        if dim != "none":
            cdf["__group"] = [_group_label(_row_group_key(r, dim), dim) for r in closed]
        col_map = {
            "__group": "Group",
            "closedAt": "Closed", "openedAt": "Opened", "account": "Account",
            "symbol": "Symbol", "side": "Side", "pattern": "Strategy",
            "qty": "Qty", "entryPrice": "Entry", "exitPrice": "Exit",
            "realizedPnl": "PnL", "realizedPnlPct": "PnL %", "closeReason": "Close",
        }
        cols = [c for c in col_map if c in cdf.columns]
        disp = cdf[cols].rename(columns=col_map) if cols else cdf
        sel_idx: int | None = None
        if _df_row_selection_supported():
            # Clicking a data cell in an `st.dataframe` only gives that cell
            # keyboard focus — it does NOT select the row. Only the tiny
            # auto-added checkbox in the leftmost column fires `on_select`,
            # which is easy to miss (especially on mobile), so the caption
            # calls it out explicitly and a selectbox is always offered too
            # as a foolproof alternative (BL-20260701-TRADECARD-CLICK).
            st.caption(f"{len(closed)} closed trade(s) · {wlabel} window"
                       + (f" · capped at {ANALYTICS_MAX_ROWS}" if len(closed) >= ANALYTICS_MAX_ROWS else "")
                       + " · check the box next to a row (or pick below) for "
                         "the full trade card")
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
                sel_idx = _closed_trade_picker(closed, "pos_closed_pick", "…or open full card for")
        else:
            # Older Streamlit without dataframe row-selection — render the
            # table plus a selectbox so the full card is still reachable.
            st.caption(f"{len(closed)} closed trade(s) · {wlabel} window"
                       + (f" · capped at {ANALYTICS_MAX_ROWS}" if len(closed) >= ANALYTICS_MAX_ROWS else "")
                       + " · pick a trade below for the full card")
            st.dataframe(disp, hide_index=True, use_container_width=True)
            sel_idx = _closed_trade_picker(closed, "pos_closed_pick", "Open full card for…")
        if sel_idx is not None and 0 <= sel_idx < len(closed):
            st.markdown("#### Selected trade")
            _render_trade_card(
                closed[sel_idx], is_open=False, op_map=op_map, signals=signals,
                key_prefix="trtab_",
            )


# ── Signals ────────────────────────────────────────────────────────────────────

def page_signals() -> None:
    st.header("Signals")
    st.caption("Recent ICT detections. Organize by strategy, asset group, or "
               "symbol and isolate one group.")
    rows, err = _fetch("/api/bot/signals")
    if err:
        st.warning(err)
        return
    if not rows:
        st.caption("No recent signals.")
        return
    # Signals are pre-account (no account dimension); organize by strategy /
    # asset group / symbol + isolate one group.
    dim, focus = _organize_controls("sig_org", rows, account_dim=False)
    rows = _apply_focus(rows, dim, focus)
    if dim == "none":
        st.dataframe(pd.DataFrame(_sort_recent(rows, "signal")),
                     hide_index=True, use_container_width=True)
    else:
        for gkey, grows in _group_rows(rows, dim):
            st.markdown(f"**{_group_label(gkey, dim)}** · {len(grows)} signal(s)")
            st.dataframe(pd.DataFrame(_sort_recent(grows, "signal")),
                         hide_index=True, use_container_width=True)


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


def _render_card_chart(
    trade: dict, *, is_open: bool, signals: list[dict] | None,
    key_prefix: str = "",
) -> None:
    """Embed the live price chart inside a trade detail card.

    Shows the symbol's candles with THIS trade's context overlaid — entry/SL/TP
    price-lines for an open position, entry/exit markers for a closed one, plus
    the correlated signals. A single fixed interval (15m) keeps the embed light;
    candle fetches are cached per (symbol, interval) so several cards for the
    same symbol reuse one upstream call. The storageKey is namespaced per card
    so each card's scroll/toggle state is independent of the others and of the
    top-of-page Overview chart."""
    sym = trade.get("symbol")
    if not sym:
        return
    tid = trade.get("id")
    ck = f"card_chart_{key_prefix}{tid}_{sym}_{'o' if is_open else 'c'}"
    if not st.checkbox("📈 Price chart", value=True, key=ck):
        return
    df, candles_err = _fetch_candles(sym, "15m", limit=400)
    if candles_err:
        st.caption(f"chart unavailable: {candles_err}")
        return
    if df is None or df.empty:
        st.caption("no candle data for this symbol.")
        return
    render_tv_chart(
        df,
        signals,
        [trade] if not is_open else None,
        sym,
        positions=[trade] if is_open else None,
        height=320,
        storage_key=f"tvccard_{re.sub(r'[^A-Za-z0-9]', '', key_prefix + str(tid) + sym)}",
    )


def _render_options_structure(opt: dict) -> None:
    """Render the defined-risk options structure block (Slice-5 surfacing).

    ``opt`` is the bot's ``Position.options`` payload: structure + contracts +
    net_debit + max_loss/max_gain + breakeven + expiration + per-leg
    {symbol(OCC), side, strike, type}. All null→"—" per the contract. No live
    broker call — decision-time geometry only.
    """
    structure = str(opt.get("structure") or "spread").replace("_", " ").title()
    st.markdown(f"**🧩 Options structure · {structure}**")
    m = st.columns(4)
    m[0].metric("Net debit", fmt_num(opt.get("net_debit")))
    m[1].metric("Max loss", fmt_usd(opt.get("max_loss_usd")) if opt.get("max_loss_usd") is not None else "—")
    m[2].metric("Max gain", fmt_usd(opt.get("max_gain_usd")) if opt.get("max_gain_usd") is not None else "—")
    m[3].metric("Contracts", fmt_num(opt.get("contracts")))
    st.caption(
        f"expiration **{opt.get('expiration') or '—'}** · "
        f"breakeven **{fmt_num(opt.get('breakeven'))}** · "
        f"width **{fmt_num(opt.get('width'))}**"
    )
    legs = opt.get("legs")
    if isinstance(legs, list) and legs:
        rows = []
        for leg in legs:
            if not isinstance(leg, dict):
                continue
            rows.append({
                "Leg": str(leg.get("side") or "—").upper(),
                "Type": str(leg.get("type") or "—").upper(),
                "Strike": leg.get("strike"),
                "OCC symbol": leg.get("symbol") or "—",
            })
        if rows:
            st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)


def _render_trade_card(
    trade: dict,
    *,
    is_open: bool,
    op_map: dict[str, dict],
    signals: list[dict] | None,
    expander_label: str | None = None,
    key_prefix: str = "",
) -> None:
    """Render one trade as a bordered, scannable detail card (open or closed).

    Model scores come straight off the linked order package's ``modelScores``
    (persisted at decision time — a cheap read), not a per-request recompile.

    When ``expander_label`` is given the whole card renders inside a collapsed
    ``st.expander`` so callers can present a clickable, expand-in-place ROW per
    trade (the Overview live-trades monitor) instead of a wall of open cards.
    The card no longer nests its own expander (the raw order package moved to a
    checkbox-gated ``st.json``), so wrapping it in one is now legal. ``key_prefix``
    namespaces the per-card widget keys so the same trade can render in more than
    one place on a page without a duplicate-key collision.
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

    # Either a clickable expand-in-place row (Overview live-trades monitor) or a
    # bordered always-open card (Positions / Trades tabs).
    card = (st.expander(expander_label, expanded=False)
            if expander_label is not None else st.container(border=True))
    with card:
        # ── Header: symbol + side, PnL on the right ────────────────────
        _acct_cls = _row_account_class(trade)
        demo = (" · 🧪 paper" if _acct_cls == "paper"
                else " · 🏦 prop" if _acct_cls == "prop" else "")
        h1, h2 = st.columns([3, 1])
        h1.markdown(f"### {side_dot} {sym} · {side_lbl}")
        if is_open:
            upnl, upnl_known = _open_upnl(trade)
            h2.metric(
                "Unrealized PnL",
                fmt_usd(upnl) if upnl_known else "—",
                delta=round(upnl, 2) if (upnl_known and upnl) else None,
            )
            # Surface where the uPnL figure came from: broker truth vs a
            # server-side mark-price compute vs unavailable (broker read
            # failed and no mark price → the "—" above).
            _src = str(trade.get("unrealizedPnlSource") or "").lower()
            _src_lbl = {
                "broker": "🛰️ broker truth",
                "markprice_local": "📐 mark-price (local compute)",
                _PROP_UPNL_SOURCE: "📐 dashboard mark-price estimate "
                                   "(prop — no broker feed; assumes 1:1 contract value)",
                "unavailable": "⚠️ unavailable (broker read failed, no mark price)",
            }.get(_src)
            if _src_lbl:
                h2.caption(f"uPnL source: {_src_lbl}")
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
            # Live trade: how long it has been open (now − openedAt).
            live_dur = _fmt_duration(trade.get("openedAt"))
            # Prop has no broker feed — its levels are the LAST values the bot
            # recorded on the ticket (updated via the report-back loop), so word
            # the SL/TP provenance accordingly.
            _lvl_note = ("SL/TP from the latest ticket (updates on report-back)"
                         if _acct_cls == "prop"
                         else "SL/TP set at entry (not trailed or modified post-open)")
            st.caption(
                f"opened {trade.get('openedAt') or '—'} · "
                f"⏱️ live for **{live_dur or '—'}** · {_lvl_note}"
            )
        else:
            # Closed trade: how long it ran (closedAt − openedAt).
            held_dur = _fmt_duration(trade.get("openedAt"), trade.get("closedAt"))
            st.caption(
                f"opened {trade.get('openedAt') or '—'} · closed "
                f"{trade.get('closedAt') or '—'} · ⏱️ duration **{held_dur or '—'}** "
                f"· close reason: "
                f"**{trade.get('closeReason') or '—'}**"
            )

        # ── Options structure (defined-risk spread legs) ───────────────
        # Present only for an options-expression row (alpaca_options_paper);
        # `null`/absent for every equity/futures/crypto trade. Decision-time
        # geometry from the bot's notes.options (connection-free; per-leg live
        # greeks/PnL are a documented bot-side follow-up).
        _opt = trade.get("options")
        if isinstance(_opt, dict):
            _render_options_structure(_opt)

        # ── Live price chart with this trade's context overlaid ────────
        _render_card_chart(trade, is_open=is_open, signals=signals,
                           key_prefix=key_prefix)

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
        # Checkbox-gated (not an st.expander) so the whole card can itself be
        # wrapped in an expander row — nested expanders are illegal in Streamlit.
        _raw_key = f"rawpkg_{key_prefix}{tid or id(trade)}_{'o' if is_open else 'c'}"
        if st.checkbox("Raw order package", key=_raw_key):
            st.json(op or {"note": "no linked order package"})


def _working_row_label(w: dict) -> str:
    """Expander-row label for a working (placed, unfilled) prop order — a
    clickable one-liner. No uPnL (there's no position yet); the amber dot + the
    'awaiting fill' tail read clearly as a working order, not a live trade."""
    side = str(w.get("side", "")).upper()
    qty = w.get("qty", "?")
    entry = w.get("entryPrice", "?")
    strat = w.get("pattern") or "?"
    acct = w.get("account") or "?"
    dur = _fmt_duration(w.get("openedAt"))
    dur_s = f" · ⏱️ {dur}" if dur else ""
    return (f"🟠 {side} {qty} @ {entry} (limit) · {strat} · {acct} · "
            f"placed{dur_s} · awaiting fill")


def _render_working_order_card(
    w: dict, *, expander_label: str, key_prefix: str = "",
) -> None:
    """Render one WORKING (placed, unfilled) prop order as a clickable row.

    Deliberately NOT :func:`_render_trade_card` — a working order has no
    position and no P&L, so it shows the limit/SL/TP geometry + the ticket
    message, but never a uPnL metric or "live for X" framing (which would imply
    an open trade). It's the placed side of the ``emitted → placed → filled``
    lifecycle; when it fills it appears in the live-trades monitor instead."""
    sym = w.get("symbol", "?")
    side_raw = str(w.get("side", "")).lower()
    if side_raw in ("buy", "long"):
        side_lbl = "LONG"
    elif side_raw in ("sell", "short"):
        side_lbl = "SHORT"
    else:
        side_lbl = side_raw.upper() or "—"
    with st.expander(expander_label, expanded=False):
        st.markdown(f"### 🟠 {sym} · {side_lbl} · working order")
        st.caption(
            f"strategy **{w.get('pattern') or '?'}** · account "
            f"**{w.get('account') or '?'}** · 🟠 **placed** — limit/pending order "
            "on the terminal, **not filled yet** (no position, no P&L)"
        )
        lv = st.columns(4)
        lv[0].metric("Limit / entry", fmt_num(w.get("entryPrice")))
        lv[1].metric("Stop loss", fmt_num(w.get("stopLoss")))
        lv[2].metric("Take profit", fmt_num(w.get("takeProfit")))
        lv[3].metric("Qty", fmt_num(w.get("qty")))
        placed_dur = _fmt_duration(w.get("openedAt"))
        st.caption(
            f"placed {w.get('openedAt') or '—'} · ⏱️ waiting **{placed_dur or '—'}** "
            "for the limit to trip · reported live once it fills"
        )
        msg = (w.get("_prop_ticket") or {}).get("message")
        if msg and st.checkbox("Show ticket message", key=f"womsg_{key_prefix}"):
            st.code(msg)


def _render_prop_ticket_decisions(window: str, wlabel: str) -> None:
    """The PROP decision-level view for the Order Packages tab. Prop has no
    order_packages — the outbound **ticket** (what the bot told the assistant to
    place: strategy/symbol/dir/entry/SL/TP) IS its decision record. Windowed by
    emit time; the full journal (fills, reconciliation) lives on the Prop tab."""
    cutoff = (dt.datetime.utcnow() - dt.timedelta(days=_WINDOW_DAYS.get(window, 1))
              if window != "all" else None)
    tickets: list[dict] = []
    for acct in _prop_accounts():
        payload, err = _fetch(f"/api/bot/prop/tickets?account_id={acct}&limit=200")
        if err or not isinstance(payload, dict):
            continue
        for t in payload.get("tickets") or []:
            ts = _parse_trade_ts(t.get("created_at") or t.get("signal_time"))
            if cutoff is not None and (ts is None or ts < cutoff):
                continue
            tickets.append(t)
    if not tickets:
        st.caption(f"No prop decisions (tickets) in the {wlabel.lower()} window.")
        return
    tickets.sort(key=lambda t: str(t.get("created_at") or ""), reverse=True)

    def _n(status: str) -> int:
        return sum(1 for t in tickets if str(t.get("status") or "").lower() == status)
    _render_header_band(real=[
        ("Tickets", len(tickets)),
        ("Filled", _n("filled")),
        ("Placed", _n("placed")),
        ("Closed", _n("closed")),
    ])
    st.divider()
    rows = [{
        "Created": t.get("created_at"),
        "Strategy": t.get("strategy"),
        "Symbol": t.get("symbol"),
        "Dir": t.get("direction"),
        "Entry": t.get("entry"),
        "SL": t.get("sl"),
        "TP": t.get("tp"),
        "Status": t.get("status"),
        "Valid until": t.get("valid_until"),
    } for t in tickets]
    st.caption(f"{len(tickets)} prop ticket(s) · {wlabel} window · the "
               "decision-level prop record")
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
    st.caption("Prop decisions are emitted as tickets for a supervised assistant "
               "to place — see the **Prop** tab for the full journal (fills, "
               "reconciliation, rule-distance cushion).")


def page_order_packages() -> None:
    st.header("Order Packages")
    st.caption(
        "Each row is an order package — the bot's actual decision (which "
        "strategy proposed what), with the shadow-model scores and the Claude "
        "decision grade. The decision level, not the fill level."
    )

    # One funding toggle + time-window bar (same 24h/7d/30d/All axis as the rest
    # of the app; default 30d). The window scopes the decision history via `since=`.
    segment, op_wlabel, op_wslug = _funding_bar(
        "op_segment", "op_window", win_index=2)
    if segment == "prop":
        # Prop has no order_packages — its decision-level record is the outbound
        # ticket (what the bot told the assistant to place). Render those instead.
        _render_prop_ticket_decisions(op_wslug, op_wlabel)
        return
    op_since = (dt.datetime.utcnow()
                - dt.timedelta(days=_WINDOW_DAYS[op_wslug])).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload, err = _fetch(
        "/api/bot/order-packages?" + urlencode({
            "limit": ANALYTICS_MAX_ROWS, "include_paper": "true", "since": op_since,
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
        if segment == "real":
            st.caption("No real-money order packages recorded yet.")
        elif segment == "paper":
            st.caption("No paper order packages recorded yet.")
        else:
            st.caption("No order packages recorded yet.")
        return

    # Header band: decision-volume summary for the current segment.
    _op_open = sum(1 for p in packages
                   if str(p.get("status", "")).lower() in ("open", "pending"))
    _op_graded = sum(1 for p in packages
                     if (p.get("claudeScore") or {}).get("grade"))
    _render_header_band(real=[
        ("Packages", len(packages)),
        ("Open", _op_open),
        ("Closed", len(packages) - _op_open),
        ("Claude-graded", _op_graded),
    ])
    st.divider()

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
    st.caption(f"{len(packages)} package(s) · {op_wlabel} window"
               + (f" · capped at {ANALYTICS_MAX_ROWS}"
                  if len(packages) >= ANALYTICS_MAX_ROWS else ""))
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
    if not (payload or {}).get("claude_log_present"):
        st.caption(
            "Claude decision scores populate as `/health-review` runs score each "
            "package — the column shows — until then."
        )


# ── Models & Training ──────────────────────────────────────────────────────────────

# Operator's 3-bucket deployment view (2026-05-18; default-flip update
# 2026-05-19). The canonical deployment ladder is 3-stage:
# ``candidate → shadow → advisory``. ``advisory`` is the live-influence
# stage — only advisory predictions ever change an order decision. The bot
# still aliases the legacy 7-stage names for old registry rows (via
# ``ml.manifest.canonical_stage`` — e.g. ``live_approved``/``limited_live`` →
# ``advisory``, ``backtest_approved``/``research_only`` → ``candidate``), so
# ``_normalize_bucket`` below folds those aliases in too. New rows never use
# them. The 3 operator buckets answer "is this model influencing real
# money, just observing, or parked?":
#   LIVE    — predictions influence trade decisions on live accounts
#             (canonical stage: advisory; legacy aliases limited_live /
#             live_approved fold in here).
#   SHADOW  — predictions logged in real time but decisions unchanged.
#             SHADOW is the default for any freshly-trained model since
#             the 2026-05-19 default flip; the lifecycle is
#             register-into-shadow → backtest gate → promote to advisory.
#   OFFLINE — operator-parked: canonical stage candidate (legacy aliases
#             research_only / backtest_approved). Reached only by explicit
#             demotion from shadow; not a default state for new models.
#
# Source of truth: the bot's /api/bot/ml/registry endpoint returns
# ``deployment_bucket`` per row (PR #1391). The dashboard prefers that
# field but falls back to the legacy stage→bucket mapping above when the
# bot API hasn't been upgraded yet — this keeps the dashboard rendering
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

    # ── Progress toward the ML promotion standard ──────────────────────
    # Per-model distance to the shadow→advisory evaluation gate: days in
    # shadow → 7, predictions → 200. Surfaces "how far from promotion" at a
    # glance (🟢 cleared · 🟡 maturing · 🔴 just started) using the same
    # codified PROMO_* thresholds the readiness verdict applies.
    with st.expander("Promotion progress — distance to evaluation", expanded=False):
        for s, label, _sev, f in graded:
            st.markdown(f"**{s.get('model_id', '?')}** · {label}")
            _standard_progress("Days in shadow → standard", f["days"],
                               PROMO_MIN_DAYS, fmt=lambda v: f"{v:.0f}d")
            _standard_progress("Predictions → standard", f["count"],
                               PROMO_MIN_PREDS, fmt=lambda v: f"{int(v)}")

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
                # Only a real shift when BOTH means are present — coercing a
                # null mean to 0 fabricates a "shift" of the other mean's value.
                _ref_mean = d.get("reference_mean")
                _cur_mean = d.get("current_mean")
                m4.metric(
                    "Mean shift",
                    fmt_num(_cur_mean - _ref_mean)
                    if (_ref_mean is not None and _cur_mean is not None) else "—",
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


# Codified M7 strategy-gate standards (docs/strategy-review-gate.md) — surfaced
# as progress-toward-standard bars so "how far is this strategy from promotion
# or demotion" is answerable at a glance.
STRAT_PROMOTE_MIN_CLOSED = 100   # n_closed needed before a promote can be proposed
STRAT_PROMOTE_WIN_RATE = 55.0    # win-rate % promote line
STRAT_DEMOTE_WIN_RATE = 40.0     # win-rate % below which demote_shadow zones open
STRAT_PROMOTE_MIN_SOAK_DAYS = 14  # override #4 — promote needs ≥14 days soak


def _render_strategy_review(name: str, *, soak_days: int | None = None) -> None:
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

    # ── Progress toward the codified gate standard ─────────────────────
    # How far this strategy is from PROMOTE-eligibility (and where the
    # DEMOTE line sits) per docs/strategy-review-gate.md. Soak days come
    # from the page (first closed trade); win_rate in the packet is a
    # fraction (0..1), so scale to % for the bar.
    n_closed = h.get("n_closed")
    if soak_days is not None:
        _standard_progress("Soak → promote-eligible (days)", soak_days,
                           STRAT_PROMOTE_MIN_SOAK_DAYS, fmt=lambda v: f"{int(v)}d")
    _standard_progress("Closed trades → promote-eligible", n_closed,
                       STRAT_PROMOTE_MIN_CLOSED, fmt=lambda v: f"{int(v)}")
    wr = h.get("win_rate")
    if isinstance(wr, (int, float)):
        wr_pct = wr * 100.0
        _standard_progress("Win rate → promote line", wr_pct,
                           STRAT_PROMOTE_WIN_RATE, fmt=lambda v: f"{v:.0f}%")
        zone = ("🔴 below demote line" if wr_pct < STRAT_DEMOTE_WIN_RATE
                else "🟢 clears promote line" if wr_pct >= STRAT_PROMOTE_WIN_RATE
                else "🟡 between demote and promote")
        st.caption(
            f"Standard: promote ≥ {STRAT_PROMOTE_WIN_RATE:.0f}% · "
            f"demote < {STRAT_DEMOTE_WIN_RATE:.0f}% — {zone}"
        )

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

    # ── Portfolio header band — the whole roster at a glance ───────────────
    n_running = sum(1 for x in strategies
                    if x.get("enabled", True) and x.get("running"))
    n_loaded = sum(1 for x in strategies if x.get("enabled", True)
                   and x.get("loaded") and not x.get("running"))
    n_disabled = sum(1 for x in strategies if not x.get("enabled", True))
    _render_header_band(real=[
        ("Strategies", len(strategies)),
        ("Running", n_running),
        ("Loaded · stale", n_loaded),
        ("Disabled", n_disabled),
    ])
    st.divider()

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

        # Soak proxy: days since this strategy's earliest closed trade in the
        # 92-day analytics window — feeds the M7 "≥14 days soak" progress bar.
        # A floor (under-counts a strategy older than the window) but fine for
        # the "has it cleared 14 days?" check.
        soak_days = None
        if not sdf.empty and "ts" in sdf.columns:
            earliest = sdf["ts"].min()
            if pd.notna(earliest):
                # ts is tz-naive UTC (see _parse_trade_ts) — keep the subtraction
                # tz-naive to avoid a tz-aware/naive mismatch.
                soak_days = max(
                    0, (pd.Timestamp(dt.datetime.utcnow()) - earliest).days)

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
            _render_strategy_review(name, soak_days=soak_days)

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

    # Per-strategy view. Discover strategy names from /api/bot/strategies so the
    # picker stays in sync with whatever is configured on the bot; if that's
    # unreachable, fall back to the /api/bot/config strategies block (a second
    # live source), then an empty-state — never a hardcoded list (which drifted
    # stale at 6 names vs ~36 configured; BL-20260611-SYM-1).
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
        # Second LIVE source before any hardcode: the /api/bot/config strategies
        # block (keyed by name). The old 6-name literal drifted stale vs the ~36
        # configured strategies (BL-20260611-SYM-1) and let the user pick a
        # strategy that no longer exists — derive from config instead so the
        # fallback can never go stale.
        cfg_payload, _cfg_err = _fetch("/api/bot/config")
        if isinstance(cfg_payload, dict) and isinstance(cfg_payload.get("strategies"), dict):
            strategy_names = sorted(
                n for n in cfg_payload["strategies"]
                if isinstance(n, str) and n.replace("_", "").isalnum() and n.islower()
            )
    if not strategy_names:
        st.info(
            "Strategy list unavailable — /api/bot/strategies and /api/bot/config "
            "both returned nothing. Per-strategy insights populate when the API "
            "is reachable."
        )
        selected = None
    else:
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
        # "Scored" = decisions that actually evaluated >=1 news item; the rest
        # are no-ops ("all news items stale or irrelevant" / no configured query)
        # and shouldn't be read as real neutral sentiment.
        scored = (
            int((pd.to_numeric(decisions["item_count"], errors="coerce").fillna(0) > 0).sum())
            if "item_count" in decisions else None
        )
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Decisions", len(decisions))
        c2.metric("Scored (had news)", "—" if scored is None else scored)
        c3.metric("Vetoes", vetoes)
        c4.metric("Boost / Reduce", f"{counts.get('boost', 0)} / {counts.get('reduce', 0)}")
        if scored is not None and scored < len(decisions):
            st.caption(
                f"⚪ {len(decisions) - scored} of {len(decisions)} decisions had **no "
                "relevant news** (no configured query / stale items) — those are no-ops, "
                "not real neutral reads. Avg sentiment is taken over the **scored** rows only."
            )

    # Clickable ticker of the actual source articles the layer read (top_items,
    # added bot-side 2026-07-06). Dedup by url, highest |score| first, linked to
    # the story. Absent on a bot predating the field → this block just skips.
    _headlines: dict[str, dict] = {}
    for r in records:
        for it in (r.get("top_items") or []):
            h = str(it.get("headline") or "").strip()
            if not h:
                continue
            key = str(it.get("url") or "").strip() or h
            # Keep the highest-|score| instance of each article.
            prev = _headlines.get(key)
            sc = abs(float(it.get("score") or 0.0))
            if prev is None or sc > prev["_abs"]:
                _headlines[key] = {"headline": h, "url": it.get("url") or "",
                                   "score": it.get("score"), "_abs": sc}
    if _headlines:
        top = sorted(_headlines.values(), key=lambda x: x["_abs"], reverse=True)[:15]
        with st.expander(f"📰 Headlines read ({len(_headlines)})", expanded=True):
            for it in top:
                url = it["url"]
                label = it["headline"]
                if url:
                    st.markdown(f"🔗 [{label}]({url})")
                else:
                    st.markdown(f"• {label}")

    # Friendly column order when present; tolerate missing keys across row kinds.
    # `top_items` is a list column (rendered as the clickable block above), so
    # keep it out of the flat table.
    preferred = ["ts", "symbol", "side", "strategy", "decision", "adjustment",
                 "veto", "event_risk", "factor", "action", "query", "reason"]
    cols = [c for c in preferred if c in df.columns]
    cols += [c for c in df.columns if c not in cols and c != "top_items"]
    st.dataframe(df[cols], hide_index=True, use_container_width=True, height=560)


def page_exit_ladder() -> None:
    """ExitPlan exit-ladder shadow-soak (dynamic-take-profit consistency P3).

    Reads `/api/bot/exit-ladder/soak`. One row per executed order: the laddered
    exit that WOULD be used (the materialized ExitPlan sized to the order's real
    qty) vs the single SL/TP target actually placed. **Observe-only** — nothing
    reads it back to drive an exit (graduating the ladder to the real exit is the
    backtest-gated P4). Empty until the first live opening order writes a row.
    """
    st.header("Exit Ladder")
    st.caption(
        "Observe-only soak: per executed order, the laddered exit (partial-TP "
        "rungs + final + stop) that WOULD be used vs the single SL/TP target "
        "actually placed. Nothing here changes a live exit — it's the evidence "
        "we watch before graduating the ladder (the backtest-gated P4)."
    )

    venue = st.radio("Venue", ["All", "api", "prop"], horizontal=True, index=0)
    q = "/api/bot/exit-ladder/soak?limit=300"
    if venue != "All":
        q += f"&venue={venue}"
    payload, err = _fetch(q)
    if err:
        st.warning(err)
        return
    if not isinstance(payload, dict) or not payload.get("present"):
        st.info(
            "No exit-ladder records yet — the soak begins recording on the next "
            "live opening order once the bot has deployed the P3 writer. "
            "(API accounts trade live, so this fills first; prop is dormant until "
            "the prop account goes live.)"
        )
        return

    summary = payload.get("summary") or {}
    by_venue = summary.get("by_venue") or {}
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Orders soaked", summary.get("total_scanned", 0))
    c2.metric("API / Prop", f"{by_venue.get('api', 0)} / {by_venue.get('prop', 0)}")
    c3.metric("Ladder differs", summary.get("differing", 0))
    c4.metric("Differs %", f"{summary.get('differing_pct', 0.0)}%")
    st.caption(
        "“Ladder differs” counts orders where the materialized ladder is more "
        "than the single target placed (a partial-TP rung and/or a trailing "
        "final) — i.e. where graduating to the ladder would actually change the "
        "exit."
    )

    records = payload.get("records") or []
    if not records:
        st.caption("No records for this filter.")
        return

    # Flatten the nested single_target / ladder blocks into a scan-friendly table.
    rows = []
    for r in records:
        st_blk = r.get("single_target") or {}
        ld = r.get("ladder") or {}
        targets = ld.get("targets") or []
        rungs = [f"{t.get('price')}×{round(float(t.get('qty', 0) or 0), 4)}" for t in targets]
        rows.append({
            "ts": r.get("ts"),
            "venue": r.get("venue"),
            "account": r.get("account_id") or "—",
            "strategy": r.get("strategy"),
            "symbol": r.get("symbol"),
            "dir": r.get("direction"),
            "qty": st_blk.get("qty"),
            "single TP": st_blk.get("tp"),
            "SL": st_blk.get("sl"),
            "ladder targets": "  →  ".join(rungs) if rungs else "—",
            "rungs": ld.get("n_rungs", 0),
            "differs": "✅" if r.get("differs_from_single_target") else "—",
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True, height=560)


def _money(v: Any) -> str:
    """Format a USD figure, em-dash for null."""
    if v is None:
        return "—"
    try:
        return f"${float(v):,.2f}"
    except (TypeError, ValueError):
        return "—"


def _prop_err(err: str | None) -> None:
    """Render a prop-endpoint error: quiet 'not deployed yet' for 404, warn otherwise.

    A 404 means the bot hasn't deployed the prop endpoints yet — expected during
    the rollout window, so it shouldn't look like a failure.
    """
    if not err:
        return
    if "404" in err:
        st.caption("⏳ Not available on the bot yet — populates once the prop "
                   "endpoints deploy.")
    else:
        st.warning(err)


def page_prop() -> None:
    """Breakout prop manual-bridge — the inbound report-back loop (P2/P3).

    The prop account has no broker API, so the bot only learns a prop trade's
    fill / close when the executor (or operator) posts it back. This tab shows
    the rule-distance to the account-killer limits, lets you submit a
    fill/close or account-status report, and renders the prop journal +
    un-acted tickets. Reads `/api/bot/prop/{status,fills,tickets,reconcile}`;
    posts to `/api/bot/prop/report`.
    """
    st.header("Prop")
    st.caption(
        "Breakout 1-Step manual bridge. The bot emits the ticket; you/the "
        "executor place it on the DXTrade terminal and report the fill/close "
        "back here. Prop is a third funding class — tracked separately, never "
        "blended into real-money or paper KPIs."
    )
    account_id = st.text_input("Account", value="breakout_1", key="prop_account")

    # Fetch the outbound tickets once — drives both the open-trade cards and the
    # sent-messages log below.
    tickets_payload, tickets_err = _fetch(
        f"/api/bot/prop/tickets?account_id={account_id}&limit=200")
    all_tickets = (
        (tickets_payload or {}).get("tickets") or []
        if isinstance(tickets_payload, dict) else []
    )

    if tickets_err and "404" in tickets_err:
        st.info(
            "⏳ The prop API endpoints aren't live on the bot yet — they ship "
            "with the bot update currently deploying. This tab (and the form "
            "below) populates as soon as it's live; no action needed."
        )

    # ── Open prop trades — cards at the very top, each with the trade message ──
    # A live prop trade = a ticket at status ``filled`` (limit tripped / market
    # fill — a real open position). ``placed`` orders (limit on the terminal, not
    # yet filled) are a SEPARATE section below: no position, no P&L.
    open_trades = [t for t in all_tickets if str(t.get("status")) == "filled"]
    working_tickets = [t for t in all_tickets if str(t.get("status")) == "placed"]
    if open_trades:
        st.subheader(f"Open prop trades ({len(open_trades)})")
        for t in open_trades:
            sym = t.get("symbol") or "?"
            direction = str(t.get("direction") or "").upper()
            with st.container(border=True):
                st.markdown(f"### {sym} {direction}  ·  {t.get('strategy') or '—'}")
                m = st.columns(4)
                m[0].metric("Entry", t.get("entry") if t.get("entry") is not None else "—")
                m[1].metric("SL", t.get("sl") if t.get("sl") is not None else "—")
                m[2].metric("TP", t.get("tp") if t.get("tp") is not None else "—")
                m[3].metric("Qty", t.get("qty") if t.get("qty") is not None else "—")
                with st.expander("📩 Trade message sent"):
                    msg = t.get("message")
                    if msg:
                        st.code(msg)
                    else:
                        st.caption("No message text stored for this ticket "
                                   "(pre-dates message capture).")
        st.divider()

    # ── Working orders (placed — awaiting fill) — no position, no P&L ──
    if working_tickets:
        st.subheader(f"🟠 Working orders — placed, awaiting fill ({len(working_tickets)})")
        st.caption("Limit / pending orders placed on the terminal that haven't "
                   "filled yet. **No position and no P&L** until the limit trips "
                   "— report the fill (`open`/`filled`) to move it to a live trade.")
        for t in working_tickets:
            sym = t.get("symbol") or "?"
            direction = str(t.get("direction") or "").upper()
            with st.container(border=True):
                st.markdown(f"### 🟠 {sym} {direction}  ·  {t.get('strategy') or '—'}  "
                            "·  _working_")
                m = st.columns(4)
                m[0].metric("Limit / entry",
                            t.get("entry") if t.get("entry") is not None else "—")
                m[1].metric("SL", t.get("sl") if t.get("sl") is not None else "—")
                m[2].metric("TP", t.get("tp") if t.get("tp") is not None else "—")
                m[3].metric("Qty", t.get("qty") if t.get("qty") is not None else "—")
                with st.expander("📩 Trade message sent"):
                    msg = t.get("message")
                    st.code(msg) if msg else st.caption(
                        "No message text stored for this ticket.")
        st.divider()

    # ── Rule-distance panel (distance to the account-killer limits) ──
    status_payload, status_err = _fetch(f"/api/bot/prop/status?account_id={account_id}")
    if status_err:
        _prop_err(status_err)
    elif isinstance(status_payload, dict):
        rd = status_payload.get("rule_distance") or {}
        st.subheader("Rule distance")
        if not status_payload.get("present"):
            st.info(
                "No account-status snapshot yet — submit one below (balance / "
                "equity / today's P&L) to compute distance to the limits."
            )
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Equity", _money(rd.get("equity")))
        dd = rd.get("distance_to_dd_floor_usd")
        c2.metric("→ DD floor", _money(dd),
                  help=f"Static-DD floor {_money(rd.get('static_dd_floor_usd'))} "
                       "(breach permanently disables the account)")
        dl = rd.get("distance_to_daily_loss_usd")
        c3.metric("→ Daily-loss", _money(dl),
                  help=f"Daily-loss limit {_money(rd.get('daily_loss_limit_usd'))}")
        c4.metric("Day P&L", _money(rd.get("day_pnl")))
        # Loud warning as either cushion thins.
        for label, val in (("static-drawdown floor", dd), ("daily-loss limit", dl)):
            if isinstance(val, (int, float)) and val <= 0:
                st.error(f"⛔ BREACHED the {label} ({_money(val)} cushion).")
            elif isinstance(val, (int, float)) and val < 50:
                st.warning(f"⚠ Thin cushion to the {label}: {_money(val)} left.")
        if rd.get("as_of"):
            st.caption(f"As of {rd['as_of']}")

    # ── Report-back form ──
    st.subheader("Report a fill / close")
    with st.form("prop_close_form", clear_on_submit=False):
        cc = st.columns(4)
        f_symbol = cc[0].text_input("Symbol", value="SOLUSDT")
        f_dir = cc[1].selectbox("Direction", ["long", "short"], index=0)
        f_status = cc[2].selectbox("Status", ["closed", "open", "skipped"], index=0)
        f_reason = cc[3].text_input("Reason", value="tp")
        cn = st.columns(4)
        f_entry = cn[0].text_input("Entry price", value="")
        f_exit = cn[1].text_input("Exit price", value="")
        f_qty = cn[2].text_input("Qty", value="")
        f_pnl = cn[3].text_input("PnL ($)", value="")
        submitted = st.form_submit_button("Submit fill/close report")
        if submitted:
            report: dict[str, Any] = {
                "account_id": account_id, "symbol": f_symbol,
                "direction": f_dir, "status": f_status, "reason": f_reason,
            }
            for key, raw in (("entry_price", f_entry), ("exit_price", f_exit),
                             ("qty", f_qty), ("pnl", f_pnl)):
                if str(raw).strip():
                    try:
                        report[key] = float(raw)
                    except ValueError:
                        st.error(f"{key} must be a number, got {raw!r}")
                        report = {}
                        break
            if report:
                res, err = _post("/api/bot/prop/report", report)
                if err:
                    st.error(err)
                else:
                    st.success(f"Reported: {res}")
                    _fetch_cached.clear()

    with st.expander("Submit an account-status snapshot (drives rule-distance)"):
        with st.form("prop_status_form", clear_on_submit=False):
            sc = st.columns(4)
            s_bal = sc[0].text_input("Balance ($)", value="")
            s_eq = sc[1].text_input("Equity ($)", value="")
            s_real = sc[2].text_input("Realized today ($)", value="")
            s_unreal = sc[3].text_input("Unrealized ($)", value="")
            s_submit = st.form_submit_button("Submit account status")
            if s_submit:
                report = {"kind": "account_status", "account_id": account_id}
                ok = True
                for key, raw in (("balance", s_bal), ("equity", s_eq),
                                 ("realized_today", s_real), ("unrealized", s_unreal)):
                    if str(raw).strip():
                        try:
                            report[key] = float(raw)
                        except ValueError:
                            st.error(f"{key} must be a number, got {raw!r}")
                            ok = False
                            break
                if ok:
                    res, err = _post("/api/bot/prop/report", report)
                    if err:
                        st.error(err)
                    else:
                        st.success("Account status recorded.")
                        _fetch_cached.clear()

    with st.expander("Advanced — raw JSON report"):
        st.caption(
            "Posts verbatim to /api/bot/prop/report. A fill/close needs "
            "account_id + symbol + status; an account-status needs "
            'kind:"account_status" + account_id.'
        )
        raw_json = st.text_area("Report JSON", value="", height=120, key="prop_raw")
        if st.button("POST raw JSON"):
            try:
                parsed = json.loads(raw_json)
            except (ValueError, TypeError) as exc:
                st.error(f"Invalid JSON: {exc}")
            else:
                res, err = _post("/api/bot/prop/report", parsed)
                st.error(err) if err else st.success(f"Reported: {res}")
                if not err:
                    _fetch_cached.clear()

    # ── Un-acted tickets (P3 drift) ──
    recon, recon_err = _fetch(f"/api/bot/prop/reconcile?account_id={account_id}")
    if not recon_err and isinstance(recon, dict):
        summ = recon.get("summary") or {}
        st.subheader("Reconciliation")
        rc = st.columns(3)
        rc[0].metric("Tickets emitted", summ.get("tickets_total", 0))
        rc[1].metric("Fills reported", summ.get("fills_total", 0))
        rc[2].metric("Un-acted tickets", summ.get("unacted_count", 0))
        unacted = recon.get("unacted_tickets") or []
        if unacted:
            st.warning(
                f"{len(unacted)} ticket(s) emitted, past validity, with no "
                "fill reported back — placed-but-unreported, or never acted on."
            )
            st.dataframe(pd.DataFrame(unacted), hide_index=True,
                         use_container_width=True)

    # ── Journal: fills + outbound tickets ──
    st.subheader("Fills (inbound)")
    fills, fills_err = _fetch(f"/api/bot/prop/fills?account_id={account_id}&limit=200")
    if fills_err:
        _prop_err(fills_err)
    elif isinstance(fills, dict) and fills.get("fills"):
        st.dataframe(pd.DataFrame(fills["fills"]), hide_index=True,
                     use_container_width=True, height=320)
    else:
        st.caption("No fills reported yet.")

    st.subheader("Sent messages (outbound tickets)")
    st.caption("Every trade-setup ticket the bot sent out, newest first — "
               "expand a row to see the exact message.")
    if tickets_err:
        _prop_err(tickets_err)
    elif all_tickets:
        for t in all_tickets:
            when = t.get("signal_time") or t.get("created_at") or ""
            sym = t.get("symbol") or "?"
            direction = str(t.get("direction") or "").upper()
            status = t.get("status") or "—"
            with st.expander(f"{when} · {sym} {direction} · {status}"):
                msg = t.get("message")
                if msg:
                    st.code(msg)
                else:
                    st.caption("No message text stored for this ticket.")
                st.json({k: t.get(k) for k in (
                    "ticket_id", "entry", "sl", "tp", "qty", "risk_usd",
                    "valid_until", "order_package_id")})
    else:
        st.caption("No prop tickets emitted yet.")


_REPORT_GRADE_DOT = {
    "healthy": "🟢", "ok": "🟢",
    "caution": "🟡", "watch": "🟡", "mixed": "🟡",
    "investigate": "🔴", "concern": "🔴",
}


def page_reports() -> None:
    """Log of consolidated /system-report executive reports + an inline viewer.

    Reads the file-backed `/api/bot/reports` index (the master `/system-report`
    skill's output) and embeds a selected report's self-contained responsive
    HTML via `components.html`. Each report also links to its stable GitHub blob.
    Read-only — the dashboard never generates a report (that's the bot-side skill).
    """
    st.header("Reports")
    st.caption(
        "Consolidated executive reports from `/system-report` — health + trading "
        "(real/paper/prop) + ML, per window. Newest first."
    )
    idx, err = _fetch("/api/bot/reports?limit=200")
    if err:
        st.warning(err)
        return
    reports = (idx or {}).get("reports") or []
    if not reports:
        st.info(
            "No reports yet. Run `/system-report` in a bot session (the report "
            "renders to `comms/reports/` and appears here once it's committed)."
        )
        return

    windows = ["All"] + sorted({r.get("window") for r in reports if r.get("window")})
    wsel = _segmented_or_radio("Window", windows, index=0, key="reports_window")
    rows = reports if wsel == "All" else [r for r in reports if r.get("window") == wsel]
    if not rows:
        st.caption("No reports in this window.")
        return

    # The index/log table.
    table = [
        {
            "Generated": (r.get("generated_at") or "—")[:19].replace("T", " "),
            "Window": r.get("window") or "—",
            "Grade": f"{_REPORT_GRADE_DOT.get(str(r.get('roll_up_grade')).lower(), '')} "
                     f"{r.get('roll_up_grade') or '—'}".strip(),
            "Headline": r.get("headline") or "—",
            "id": r.get("id") or "—",
        }
        for r in rows
    ]
    st.dataframe(pd.DataFrame(table), hide_index=True, use_container_width=True)

    # Pick one and view it inline.
    labels = [
        f"{(r.get('generated_at') or '—')[:16].replace('T', ' ')} · {r.get('window') or '—'} · "
        f"{_REPORT_GRADE_DOT.get(str(r.get('roll_up_grade')).lower(), '')}{r.get('roll_up_grade') or '—'}"
        for r in rows
    ]
    # If we arrived via a ``?report=<id>`` deep link, pre-select that report
    # (the window was already forced to "All" so it's present). Consume the id
    # once so the user can freely pick others afterwards.
    deep_rid = st.session_state.pop("_deep_report_id", None)
    if deep_rid:
        match = next((i for i, r in enumerate(rows) if r.get("id") == deep_rid), None)
        if match is not None:
            st.session_state["reports_pick"] = match
    pick = st.selectbox("Open a report", list(range(len(rows))), format_func=lambda i: labels[i],
                        key="reports_pick")
    chosen = rows[pick]
    rid = chosen.get("id")

    detail, derr = _fetch(f"/api/bot/reports/{rid}")
    if derr:
        st.warning(derr)
        return
    body = (detail or {}).get("html")
    if not body:
        st.caption("Report HTML not available (artifact may not be mirrored yet).")
        return
    # Download the self-contained HTML so it can be opened/saved in a normal
    # browser (the repo is private, so a GitHub link would only show source).
    st.download_button(
        "⬇ Download HTML (open in your browser)",
        data=body,
        file_name=f"{rid or 'system-report'}.html",
        mime="text/html",
        use_container_width=True,
    )
    components.html(body, height=900, scrolling=True)


def page_logs() -> None:
    st.header("Logs")
    st.caption(
        "Merged pipeline audit + operator outcomes (WARN/ERROR/CRITICAL), newest "
        "first. Filter by window + level (both applied server-side)."
    )
    # Window + level filters (parity with the Android Logs screen) — the bot's
    # /api/bot/logs accepts since= + level= (CSV ∈ {info,warn,error,trade}).
    c1, c2 = st.columns([1, 2])
    with c1:
        win = _segmented_or_radio(
            "Window", ["1h", "6h", "24h", "7d"], index=2, key="logs_window",
            help="How far back to pull log rows.",
        )
    with c2:
        all_levels = ["trade", "info", "warn", "error"]
        levels = st.multiselect(
            "Levels", all_levels, default=all_levels, key="logs_levels",
            help="Filter by log level (server-side). Empty = all.",
        )
    hours = {"1h": 1, "6h": 6, "24h": 24, "7d": 168}.get(win, 24)
    since = (dt.datetime.utcnow() - dt.timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    q = f"/api/bot/logs?limit=1000&since={since}"
    # Only narrow when a strict subset is chosen (empty or full = no level filter).
    if levels and len(levels) < len(all_levels):
        q += "&level=" + ",".join(levels)

    rows, err = _fetch(q)
    if err:
        st.warning(err)
        return
    if not rows:
        st.caption("No log entries for this window / level filter.")
        return
    st.caption(f"{len(rows)} entries · last {win}")
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True, height=600)


# ── Roadmap ────────────────────────────────────────────────────────────────
# Progress visualization over ROADMAP.md → milestones → sprints, drilling into
# the notes/summaries of each work-session log. Backed by the bot's read-only
# /api/bot/roadmap[/sprint/{id}] endpoints (file-backed from ROADMAP.md +
# docs/sprint-logs/, Tier-1). Roadmap is a top-level section rendered directly
# (like Overview) rather than a card stack.

# Milestone status token → (emoji, colour) for the progress badges.
_MS_STATUS_STYLE: dict[str, tuple[str, str]] = {
    "done":        ("✅", _TV_GREEN),
    "in_progress": ("🔄", "#f5a623"),
    "next":        ("🔜", "#4a90e2"),
    "reopened":    ("⚠️", "#f5a623"),
    "planned":     ("📋", "#6b7488"),
    "blocked":     ("⛔", _TV_RED),
    "unknown":     ("⚪", "#6b7488"),
}


def _ms_style(token: str) -> tuple[str, str]:
    return _MS_STATUS_STYLE.get(token, _MS_STATUS_STYLE["unknown"])


def _render_sprint_detail(sid: str, key_prefix: str) -> None:
    """Fetch + render one sprint log's parsed sections (the work-session notes).

    Rendered inline (no nested st.expander — that's illegal in Streamlit), so
    the section bodies go out as markdown under bold sub-headers, with the raw
    markdown behind a checkbox toggle. `key_prefix` namespaces the toggle so the
    same sprint opened from two pickers (Jump + its milestone) can't collide."""
    detail, err = _fetch(f"/api/bot/roadmap/sprint/{sid}")
    if err:
        st.warning(err)
        return
    if not detail or not detail.get("present"):
        st.caption("No log found for this session.")
        return
    meta_bits = []
    if detail.get("milestone"):
        meta_bits.append(f"milestone **{detail['milestone']}**")
    span = " → ".join(x for x in (detail.get("dateStart"), detail.get("dateEnd")) if x)
    if span:
        meta_bits.append(span)
    if meta_bits:
        st.caption(" · ".join(meta_bits))
    if detail.get("objective"):
        st.markdown(f"**Objective** — {detail['objective']}")
    for sec in detail.get("sections", []):
        heading = sec.get("heading", "").strip()
        body = (sec.get("body") or "").strip()
        if not heading and not body:
            continue
        st.markdown(f"**{heading}**")
        if body:
            st.markdown(body)
    if st.checkbox("Show raw markdown", key=f"rm_raw_{key_prefix}_{sid}"):
        st.code(detail.get("markdown", ""), language="markdown")


def _sprint_picker(sprints: list[dict], key: str, label: str) -> None:
    """A selectbox over `sprints` (newest-first) that renders the picked log
    inline below. `sprints` are index rows carrying id/title/dateEnd/objective."""
    if not sprints:
        st.caption("No work-session logs mapped here yet.")
        return
    opts = ["— open a session log —"]
    id_by_label: dict[str, str] = {}
    for s in sprints:
        lbl = f"{s.get('dateEnd') or '—'} · {s['id']}"
        opts.append(lbl)
        id_by_label[lbl] = s["id"]
    choice = st.selectbox(label, opts, key=key)
    sid = id_by_label.get(choice)
    if sid:
        with st.container(border=True):
            st.markdown(f"### {sid}")
            _render_sprint_detail(sid, key_prefix=key)


def _render_sprint_list(rows: list[dict], key_prefix: str) -> None:
    """Render `rows` as a clickable table (Date · Milestone · Session ·
    Objective); selecting a row opens that session's notes below. Falls back to
    a table + selectbox on older Streamlit without dataframe row-selection."""
    if not rows:
        st.caption("No sessions match these filters.")
        return
    df = pd.DataFrame(
        [
            {
                "Date": s.get("dateEnd") or "—",
                "Milestone": s.get("milestone") or "—",
                "Session": s["id"],
                "Objective": (s.get("objective") or "—")[:90],
            }
            for s in rows
        ]
    )
    picked: str | None = None
    if _df_row_selection_supported():
        event = st.dataframe(
            df, hide_index=True, use_container_width=True,
            on_select="rerun", selection_mode="single-row", key=f"{key_prefix}_df",
        )
        try:
            sel = event.selection.rows  # type: ignore[union-attr]
        except AttributeError:
            sel = []
        if sel:
            picked = rows[sel[0]]["id"]
    else:
        st.dataframe(df, hide_index=True, use_container_width=True)
        label_by = {f"{s.get('dateEnd') or '—'} · {s['id']}": s["id"] for s in rows}
        choice = st.selectbox("Open a session", ["—", *label_by.keys()], key=f"{key_prefix}_pick")
        picked = label_by.get(choice)
    if picked:
        with st.container(border=True):
            st.markdown(f"### {picked}")
            _render_sprint_detail(picked, key_prefix=key_prefix)


def _all_sessions_browser(sprints: list[dict], ms_order: list[str]) -> None:
    """A flat list of every work session with organize-by + filter controls."""
    c1, c2 = st.columns([1.2, 1])
    with c1:
        organize = st.radio(
            "Organize by", ["Recent", "Milestone", "A–Z"],
            horizontal=True, key="rm_all_org",
        )
    with c2:
        has_unmapped = any(not s.get("milestone") for s in sprints)
        opts = ["All", *ms_order, *(["Unmapped"] if has_unmapped else [])]
        focus = st.selectbox("Filter by milestone", opts, key="rm_all_filter")
    q = st.text_input(
        "Search", key="rm_all_q", placeholder="session id or objective…",
    ).strip().lower()

    rows = list(sprints)
    if focus == "Unmapped":
        rows = [s for s in rows if not s.get("milestone")]
    elif focus != "All":
        rows = [s for s in rows if s.get("milestone") == focus]
    if q:
        rows = [s for s in rows
                if q in s["id"].lower() or q in (s.get("objective") or "").lower()]

    if organize == "Recent":
        rows.sort(key=lambda s: (s.get("dateEnd") or "", s["id"]), reverse=True)
    elif organize == "A–Z":
        rows.sort(key=lambda s: s["id"].lower())
    else:  # Milestone — roadmap order, then newest-first within each
        order = {m: i for i, m in enumerate(ms_order)}
        rows.sort(key=lambda s: (order.get(s.get("milestone"), 999),
                                 "" if s.get("dateEnd") is None else s["dateEnd"]),
                  reverse=False)
    st.caption(f"{len(rows)} of {len(sprints)} sessions")
    _render_sprint_list(rows, key_prefix="rm_all")


def page_roadmap() -> None:
    st.header("🗺️ Roadmap")
    data, err = _fetch("/api/bot/roadmap")
    if err:
        st.warning(err)
        return
    if not data or not data.get("present"):
        st.info("The roadmap isn't available yet (the bot returned no ROADMAP.md).")
        return

    lu = data.get("lastUpdated")
    hl = data.get("lastUpdatedHeadline")
    if lu or hl:
        st.caption("Roadmap last updated: "
                   + " — ".join(str(x) for x in (lu, hl) if x))

    # ── Progress roll-up ──────────────────────────────────────────────────
    summ = data.get("summary", {})
    total = summ.get("total", 0) or 0
    done = summ.get("done", 0) or 0
    active = summ.get("active", 0) or 0
    pending = summ.get("pending", 0) or 0
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Milestones", total)
    c2.metric("✅ Done", done)
    c3.metric("🔄 Active", active)
    c4.metric("📋 Planned", pending)
    if total:
        st.progress(done / total, text=f"{done}/{total} milestones complete "
                                        f"({done / total * 100:.0f}%)")
    st.caption(f"{data.get('sprintCount', 0)} work-session logs on record.")

    sprints = data.get("sprints", [])
    by_ms: dict[str, list[dict]] = {}
    for s in sprints:
        if s.get("milestone"):
            by_ms.setdefault(s["milestone"], []).append(s)

    st.divider()

    milestones = data.get("milestones", [])
    ms_order = [m["id"] for m in milestones]
    tab_ms, tab_all = st.tabs(["Milestones", "All sessions"])

    # ── Milestones → sprints ──────────────────────────────────────────────
    with tab_ms:
        for m in milestones:
            emoji, colour = _ms_style(m.get("status", "unknown"))
            focus = (m.get("focus") or "").replace("*", "").strip()
            focus = (focus[:70] + "…") if len(focus) > 70 else focus
            n = m.get("sprintCount", 0)
            label = f"{emoji} **{m['id']}** · {focus}"
            if n:
                label += f"  ·  {n} session{'s' if n != 1 else ''}"
            with st.expander(label, expanded=False):
                st.markdown(
                    f"<span style='color:{colour};font-weight:600'>"
                    f"{m.get('statusLabel') or m.get('status', '')}</span>"
                    + (f" · <span style='color:#6b7488'>{m.get('type', '')}</span>"
                       if m.get('type') else ""),
                    unsafe_allow_html=True,
                )
                detail = (m.get("statusDetail") or "").strip()
                if detail:
                    st.markdown(detail)
                st.divider()
                _sprint_picker(by_ms.get(m["id"], []), key=f"rm_ms_{m['id']}",
                               label=f"Work sessions under {m['id']}")
        unmapped = [s for s in sprints if not s.get("milestone")]
        if unmapped:
            with st.expander(f"⚪ Other sessions — not tied to a milestone ({len(unmapped)})",
                             expanded=False):
                _sprint_picker(unmapped, key="rm_unmapped",
                               label="Work sessions (newest first)")

    # ── Flat, filterable/organizable list of every work session ───────────
    with tab_all:
        _all_sessions_browser(sprints, ms_order)


def _learning_curriculum() -> tuple[dict | None, str | None]:
    """Return (curriculum, source_note). Prefer the bot's
    /api/bot/learning/curriculum; fall back to the bundled copy committed in
    this repo (so the tab works before the bot endpoint is deployed)."""
    data, _err = _fetch("/api/bot/learning/curriculum")
    cur = (data or {}).get("curriculum") if isinstance(data, dict) else None
    if cur:
        return cur, None
    try:
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "data", "learning_curriculum.json")
        with open(p, encoding="utf-8") as fh:
            return json.load(fh), (
                "Showing the bundled curriculum — the bot's learning endpoint "
                "isn't live yet, so progress tracking is read-only until it is."
            )
    except Exception:  # noqa: BLE001
        return None, None


# ── Interactive course: TTS "podcast" player + graded quiz ──────────────────
# The player is a self-contained Web Speech API embed (no Python round-trip, no
# audio files, no API key) — the browser's built-in voices read a two-host
# script. Same components.html pattern as the lightweight-charts embed; a real
# TTS-service upgrade (natural voices) is a documented follow-up.
_COURSE_TTS_HTML = r"""
<div id="pod">
  <style>
    #pod{font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;color:#1b2130;}
    #pod .row{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:8px;}
    #pod button{font:inherit;font-weight:600;border:1px solid #cbd2dc;background:#fff;
      color:#1b2130;border-radius:8px;padding:7px 12px;cursor:pointer;}
    #pod button:hover{border-color:#7c8595;}
    #pod button.primary{background:#a9700f;color:#fff;border-color:#a9700f;}
    #pod select{font:inherit;border:1px solid #cbd2dc;border-radius:8px;padding:6px 8px;background:#fff;color:#1b2130;max-width:160px;}
    #pod label{font-size:.8rem;color:#4a5265;display:inline-flex;gap:5px;align-items:center;}
    #pod .prog{font-variant-numeric:tabular-nums;font-size:.8rem;color:#4a5265;margin-left:auto;}
    #pod #transcript{max-height:340px;overflow:auto;border:1px solid #e2e6ec;border-radius:10px;
      padding:10px 12px;background:#fbfcfd;line-height:1.55;}
    #pod .line{padding:5px 7px;border-radius:7px;cursor:pointer;margin-bottom:2px;}
    #pod .line:hover{background:#eef1f5;}
    #pod .line.active{background:#f4e6cd;}
    #pod .who{font-weight:700;font-size:.72rem;text-transform:uppercase;letter-spacing:.04em;
      padding:1px 6px;border-radius:5px;margin-right:6px;}
    #pod .whoa{background:#e7f0ea;color:#2f7d5b;}
    #pod .whob{background:#e6ecf5;color:#31558f;}
    #pod .note{font-size:.74rem;color:#8a93a1;margin-top:6px;}
    @media (prefers-color-scheme:dark){
      #pod{color:#e9e6dd;}
      #pod button{background:#1c2431;color:#e9e6dd;border-color:#39424f;}
      #pod button.primary{background:#e2ac52;color:#161d28;border-color:#e2ac52;}
      #pod select{background:#1c2431;color:#e9e6dd;border-color:#39424f;}
      #pod label,#pod .prog{color:#a8b0be;}
      #pod #transcript{background:#141b25;border-color:#28303d;}
      #pod .line:hover{background:#1f2836;}
      #pod .line.active{background:#3a2f14;}
      #pod .whoa{background:#16281e;color:#57b78d;}
      #pod .whob{background:#161f2e;color:#7ba0d6;}
      #pod .note{color:#69717f;}
    }
  </style>
  <div class="row">
    <button id="play" class="primary">▶ Play</button>
    <button id="pause">⏸ Pause</button>
    <button id="stop">⏹ Stop</button>
    <label>Speed
      <select id="rate">
        <option value="0.85">0.85×</option>
        <option value="1" selected>1×</option>
        <option value="1.15">1.15×</option>
        <option value="1.3">1.3×</option>
        <option value="1.5">1.5×</option>
      </select></label>
    <span class="prog" id="prog"></span>
  </div>
  <div class="row">
    <label id="lblA">Voice A <select id="vA"></select></label>
    <label id="lblB">Voice B <select id="vB"></select></label>
  </div>
  <div id="transcript"></div>
  <div class="note" id="note"></div>
  <script>
    var DATA = __PAYLOAD__;
    var synth = window.speechSynthesis;
    var lines = DATA.lines || [];
    var hosts = DATA.hosts || {a:"Host A", b:"Host B"};
    var voices = [], idx = 0, playing = false;
    var tEl = document.getElementById("transcript");

    function esc(s){var d=document.createElement("div");d.textContent=s;return d.innerHTML;}
    document.getElementById("lblA").firstChild.textContent = (hosts.a||"Voice A") + " ";
    document.getElementById("lblB").firstChild.textContent = (hosts.b||"Voice B") + " ";

    lines.forEach(function(ln,i){
      var d=document.createElement("div");
      d.className="line"; d.id="ln"+i;
      var who = ln.s==="a" ? (hosts.a||"A") : (hosts.b||"B");
      d.innerHTML = '<span class="who who'+(ln.s==="a"?"a":"b")+'">'+esc(who)+'</span>'+esc(ln.t);
      d.onclick=function(){ idx=i; highlight(i); };
      tEl.appendChild(d);
    });

    function populateVoices(){
      voices = synth.getVoices() || [];
      var en = voices.filter(function(v){return /^en/i.test(v.lang);});
      var list = en.length ? en : voices;
      var vA=document.getElementById("vA"), vB=document.getElementById("vB");
      vA.innerHTML=""; vB.innerHTML="";
      list.forEach(function(v){
        var gi = voices.indexOf(v);
        var o=document.createElement("option"); o.value=gi; o.textContent=v.name;
        vA.appendChild(o); vB.appendChild(o.cloneNode(true));
      });
      if(list.length){
        vA.value = voices.indexOf(list[0]);
        vB.value = voices.indexOf(list[list.length>1?1:0]);
      }
      document.getElementById("note").textContent = list.length
        ? "Tip: pick two different voices so the hosts sound distinct."
        : "No speech voices detected in this browser — read the transcript above.";
    }
    populateVoices();
    if(typeof speechSynthesis!=="undefined" && "onvoiceschanged" in speechSynthesis){
      speechSynthesis.onvoiceschanged = populateVoices;
    }

    function highlight(i){
      var els=document.querySelectorAll(".line");
      for(var k=0;k<els.length;k++){ els[k].classList.remove("active"); }
      var el=document.getElementById("ln"+i);
      if(el){ el.classList.add("active"); el.scrollIntoView({block:"center",behavior:"smooth"}); }
      document.getElementById("prog").textContent = lines.length ? (i+1)+" / "+lines.length : "";
    }

    function speakFrom(i){
      if(i>=lines.length){ playing=false; idx=0; return; }
      idx=i; highlight(i);
      var ln=lines[i];
      var u=new SpeechSynthesisUtterance(ln.t);
      var sel = ln.s==="a" ? document.getElementById("vA") : document.getElementById("vB");
      var vi = parseInt(sel.value,10);
      if(!isNaN(vi) && voices[vi]) u.voice=voices[vi];
      u.rate = parseFloat(document.getElementById("rate").value)||1;
      u.pitch = ln.s==="a" ? 1.06 : 0.94;
      u.onend = function(){ if(playing){ speakFrom(i+1); } };
      u.onerror = function(){ if(playing){ speakFrom(i+1); } };
      synth.speak(u);
    }

    function play(){
      if(!lines.length) return;
      if(synth.paused){ synth.resume(); playing=true; return; }
      if(playing) return;
      playing=true; synth.cancel(); speakFrom(idx);
    }
    function pause(){ if(playing && !synth.paused){ synth.pause(); playing=false; } }
    function stop(){ playing=false; synth.cancel(); idx=0; highlight(0); }

    document.getElementById("play").onclick=play;
    document.getElementById("pause").onclick=pause;
    document.getElementById("stop").onclick=stop;
    // Chrome silently pauses long queues; a periodic resume keeps playback alive.
    setInterval(function(){ if(playing && synth.paused){ synth.resume(); } }, 9000);
    // Stop speech if the embed is torn down (episode switch / navigation).
    window.addEventListener("pagehide", function(){ try{ synth.cancel(); }catch(e){} });
    highlight(0);
  </script>
</div>
"""


def _load_course(course_id: str) -> dict | None:
    """Load one course. Prefer the bot's /api/bot/learning/courses/<id> (the
    central content store both apps read); fall back to the bundled copy in
    data/courses/<id>.json so the tab works before the bot endpoint deploys."""
    data, _err = _fetch(f"/api/bot/learning/courses/{course_id}")
    course = (data or {}).get("course") if isinstance(data, dict) else None
    if course:
        return course
    try:
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "data", "courses", f"{course_id}.json")
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:  # noqa: BLE001
        return None


def _courses_library() -> list[dict]:
    """Available courses as [{course_id, title, subtitle, …}], newest-first by
    the bot index; falls back to scanning the bundled data/courses/ dir."""
    data, _err = _fetch("/api/bot/learning/courses")
    rows = (data or {}).get("courses") if isinstance(data, dict) else None
    if rows:
        return rows
    out = []
    try:
        d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "courses")
        for name in sorted(os.listdir(d)):
            if not name.endswith(".json"):
                continue
            try:
                with open(os.path.join(d, name), encoding="utf-8") as fh:
                    c = json.load(fh)
                out.append({"course_id": c.get("course_id") or name[:-5],
                            "title": c.get("title", name[:-5]),
                            "subtitle": c.get("subtitle", "")})
            except Exception:  # noqa: BLE001
                continue
    except Exception:  # noqa: BLE001
        return out
    return out


def _course_player_html(ep: dict, hosts: dict) -> str:
    payload = {"lines": ep.get("script", []), "hosts": hosts}
    return _COURSE_TTS_HTML.replace("__PAYLOAD__", json.dumps(payload))


# Persistent "now playing" bar, pinned to the bottom of the app (injected into
# the PARENT document so it survives Streamlit reruns + page navigation — a
# normal inline iframe/audio remounts + stops on every rerun). It is DUAL-MODE:
#   * mode "audio"  → a real <audio> element for a directly-playable URL (our
#     GitHub-Release-hosted mp3s). Carries a big tappable playback-SPEED button
#     (0.75/1/1.25/1.5/1.75/2×) — the whole point of re-hosting off Drive.
#   * mode "iframe" → Drive's own /preview player for a `drive_id`. Google now
#     needs a scan-confirmation token a plain <audio> can't provide, so its
#     embedded player is the only thing that reliably plays a Drive file — but
#     it has NO speed control (that's why real audio goes to GitHub Releases).
# Mobile: the bar reserves right-edge padding so its controls never hide under
# Streamlit Cloud's floating bottom-right "Manage app" button, the speed button
# + close sit on the LEFT (always reachable), and the title is dropped on narrow
# viewports to give the scrubber room.
_AUDIO_PLAYER_TMPL = r"""
<div id="ict-ap"></div>
<script>
(function(){
  var URL=__URL__, TITLE=__TITLE__, EPID=__EPID__, VIEW=__VIEW__, MODE=__MODE__;
  var CSS="#ict-gap{position:fixed;left:0;right:0;bottom:0;z-index:2147483000;display:flex;align-items:center;gap:8px;"
    +"padding:8px 10px;padding-right:64px;box-sizing:border-box;background:#12161d;border-top:1px solid #2a3038;color:#e9edf2;"
    +"font-family:system-ui,-apple-system,sans-serif;box-shadow:0 -2px 12px rgba(0,0,0,.4);}"
    +"#ict-gap .cl{background:transparent;color:#8b949e;border:0;width:34px;height:40px;font-size:22px;cursor:pointer;flex:0 0 auto;}"
    +"#ict-gap .spd{background:#a9700f;color:#fff;border:0;border-radius:8px;min-width:56px;height:40px;font:700 15px system-ui;cursor:pointer;flex:0 0 auto;}"
    +"#ict-gap .ttl{font-size:12px;color:#c9d1d9;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:26%;flex:0 1 auto;}"
    +"#ict-gap audio{flex:1 1 auto;height:40px;min-width:0;}"
    +"#ict-gap iframe{flex:1 1 auto;border:0;height:62px;min-width:0;border-radius:8px;}"
    +"body{padding-bottom:104px !important;}"
    +"@media(max-width:640px){#ict-gap{padding-right:56px;}#ict-gap .ttl{display:none;}}";
  var SPEEDS=[1,1.25,1.5,1.75,2,0.75];
  function buildBar(doc){
    var win=doc.defaultView;
    if(!doc.getElementById('ict-gap-style')){var st=doc.createElement('style');st.id='ict-gap-style';st.textContent=CSS;doc.head.appendChild(st);}
    var bar=doc.getElementById('ict-gap');
    if(!bar){
      bar=doc.createElement('div');bar.id='ict-gap';bar.style.display='none';
      bar.innerHTML='<button class="cl" id="ict-gap-x" title="Close">&times;</button>'
        +'<button class="spd" id="ict-gap-spd" title="Playback speed" style="display:none;">1&times;</button>'
        +'<div class="ttl" id="ict-gap-t"></div>'
        +'<audio id="ict-gap-au" controls preload="none" style="display:none;"></audio>'
        +'<iframe id="ict-gap-if" allow="autoplay" allowfullscreen style="display:none;"></iframe>';
      doc.body.appendChild(bar);
      var au=doc.getElementById('ict-gap-au');
      var spd=doc.getElementById('ict-gap-spd');
      spd.onclick=function(){
        var i=(SPEEDS.indexOf(au.playbackRate)+1)%SPEEDS.length;
        var r=SPEEDS[i];au.playbackRate=r;
        spd.textContent=(r===Math.floor(r)?r:r.toFixed(2).replace(/0$/,''))+'×';
      };
      bar.querySelector('#ict-gap-x').onclick=function(){
        au.pause();au.removeAttribute('src');au.load();au.dataset.epid='';
        var f=doc.getElementById('ict-gap-if');f.src='about:blank';f.dataset.epid='';
        bar.style.display='none';
      };
      win.ictLoadAudio=function(url,title,epid,mode){
        var f=doc.getElementById('ict-gap-if');bar.style.display='flex';
        doc.getElementById('ict-gap-t').textContent=title;
        if(mode==='audio'){
          f.style.display='none';au.style.display='';spd.style.display='';
          if(au.dataset.epid!==epid){au.dataset.epid=epid;au.src=url;au.play().catch(function(){});}
        }else{
          au.pause();au.style.display='none';spd.style.display='none';f.style.display='';
          if(f.dataset.epid!==epid){f.dataset.epid=epid;f.src=url;}
        }
      };
    }
    return bar;
  }
  var host=document.getElementById('ict-ap');
  try{
    buildBar(window.parent.document);
    host.innerHTML='<button class="ict-inline">&#9654; Open player</button>'
      +'<div class="note">Opens the player pinned at the bottom &mdash; keeps playing as you browse'
      +(MODE==='audio'?', with a speed control.':'.')
      +(VIEW?' <a href="'+VIEW+'" target="_blank" style="color:#58a6ff">Open in Drive ↗</a>':'')+'</div>';
    var s1=document.createElement('style');
    s1.textContent='.ict-inline{background:#a9700f;color:#fff;border:0;border-radius:8px;padding:11px 16px;font:600 14px system-ui;cursor:pointer;}'
      +'.note{font:12px/1.4 system-ui;color:#8b949e;margin-top:6px;}';
    document.head.appendChild(s1);
    host.querySelector('.ict-inline').onclick=function(){window.parent.ictLoadAudio(URL,TITLE,EPID,MODE);};
  }catch(e){
    // Fallback (parent-document injection blocked): inline, no persistence.
    if(MODE==='audio'){
      host.innerHTML='<audio src="'+URL+'" controls preload="none" style="width:100%;"></audio>';
    }else{
      host.innerHTML='<iframe src="'+URL+'" width="100%" height="70" allow="autoplay" style="border:0;border-radius:8px;"></iframe>'
        +(VIEW?'<div class="note"><a href="'+VIEW+'" target="_blank" style="color:#58a6ff">Open in Drive ↗</a></div>':'');
      var s2=document.createElement('style');s2.textContent='.note{font:12px system-ui;color:#8b949e;margin-top:6px;}';document.head.appendChild(s2);
    }
  }
})();
</script>
"""


def _audio_player_html(page_url: str, title: str, ep_id: str, view_url: str = "",
                       mode: str = "iframe") -> str:
    return (_AUDIO_PLAYER_TMPL
            .replace("__URL__", json.dumps(page_url))
            .replace("__TITLE__", json.dumps(title))
            .replace("__EPID__", json.dumps(ep_id))
            .replace("__VIEW__", json.dumps(view_url or ""))
            .replace("__MODE__", json.dumps(mode)))


def _course_slug(course: dict) -> str:
    """A stable per-course session-state prefix so multiple courses don't share
    quiz/episode widget state."""
    cid = (course.get("course_id") or "course").lower()
    return "course_" + re.sub(r"[^a-z0-9]+", "_", cid).strip("_")


def _render_course_quiz(course: dict) -> None:
    quiz = course.get("quiz", [])
    if not quiz:
        st.info("No quiz for this course yet.")
        return
    ns = _course_slug(course)
    st.caption(f"{len(quiz)} questions — pick an answer for each, then submit. "
               "You'll see what you got right and why.")
    submitted = bool(st.session_state.get(f"{ns}_submitted"))
    for i, q in enumerate(quiz):
        st.markdown(f"**{i + 1}. {q['q']}**")
        st.radio(
            "answer", list(range(len(q["options"]))),
            format_func=lambda j, q=q: q["options"][j],
            key=f"{ns}_q_{q['id']}", index=None,
            label_visibility="collapsed",
        )
        if submitted:
            sel = st.session_state.get(f"{ns}_q_{q['id']}")
            ans = q["options"][q["answer"]]
            if sel == q["answer"]:
                st.success(f"✅ Correct — {q.get('explain', '')}")
            elif sel is None:
                st.warning(f"⬜ Unanswered. Answer: **{ans}**. {q.get('explain', '')}")
            else:
                st.error(f"❌ Not quite. Answer: **{ans}**. {q.get('explain', '')}")
        st.write("")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Submit answers", key=f"{ns}_submit", type="primary",
                     use_container_width=True):
            st.session_state[f"{ns}_submitted"] = True
            st.rerun()
    with c2:
        if st.button("Reset quiz", key=f"{ns}_reset", use_container_width=True):
            for q in quiz:
                st.session_state.pop(f"{ns}_q_{q['id']}", None)
            st.session_state.pop(f"{ns}_submitted", None)
            st.rerun()
    if submitted:
        correct = sum(1 for q in quiz
                      if st.session_state.get(f"{ns}_q_{q['id']}") == q["answer"])
        pct = correct / len(quiz) * 100 if quiz else 0
        st.metric("Score", f"{correct} / {len(quiz)}", f"{pct:.0f}%")
        if pct >= 80:
            st.success("Great — you've got this one down. 🎓")
        elif pct >= 50:
            st.info("Solid start — relisten to the episodes covering the ones you missed.")
        else:
            st.warning("Worth another listen, then retake it.")


def _render_course_transcript(ep: dict, hosts: dict) -> None:
    # A `transcript_url` (e.g. the NotebookLM notebook, which holds the audio's
    # transcript) renders as a link; a freeform `transcript` string or the
    # two-host `script` render inline in an expander.
    url = ep.get("transcript_url")
    if url:
        st.markdown(f"[📄 Open the transcript in NotebookLM ↗]({url})")
    text = ep.get("transcript")
    if text:
        with st.expander("📄 Transcript", expanded=False):
            st.markdown(str(text))
    elif ep.get("script"):
        with st.expander("📄 Transcript", expanded=False):
            for ln in ep.get("script", []):
                who = hosts.get(ln.get("s"), "")
                st.markdown(f"**{who}:** {ln.get('t', '')}")


def _render_course(course: dict) -> None:
    st.markdown(f"##### {course.get('title', '')}")
    if course.get("subtitle"):
        st.caption(course["subtitle"])
    tab_ep, tab_quiz = st.tabs(["🎧 Episodes", "📝 Quiz"])
    with tab_ep:
        eps = course.get("episodes", [])
        if not eps:
            st.info("No episodes yet.")
        else:
            idx = st.radio(
                "Episode", list(range(len(eps))),
                format_func=lambda i: eps[i].get("title", f"Episode {i + 1}"),
                key=f"{_course_slug(course)}_ep",
            )
            ep = eps[idx]
            mins = ep.get("minutes")
            cap = ep.get("summary", "")
            if mins:
                cap = (cap + f"  ·  ~{mins} min").strip()
            if cap:
                st.caption(cap)
            audio_path = None
            if ep.get("audio"):
                cand = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "data", "courses", ep["audio"])
                if os.path.exists(cand):
                    audio_path = cand
            has_script = bool(ep.get("script"))
            if audio_path:
                # Real generated (or hand-supplied) audio committed in-repo.
                with open(audio_path, "rb") as fh:
                    st.audio(fh.read())
                _render_course_transcript(ep, course.get("hosts", {}))
            elif ep.get("drive_id"):
                # Audio in the shared Drive folder — Drive's own /preview player
                # (the only thing that reliably plays a Drive file) in a
                # persistent bottom bar.
                did = ep["drive_id"]
                components.html(
                    _audio_player_html(
                        f"https://drive.google.com/file/d/{did}/preview",
                        ep.get("title", ""), ep.get("id", ""),
                        f"https://drive.google.com/file/d/{did}/view"),
                    height=90)
                _render_course_transcript(ep, course.get("hosts", {}))
            elif ep.get("audio_url"):
                # A directly-playable hosted audio URL (our GitHub-Release mp3s).
                # The persistent bottom bar in "audio" mode — keeps playing as
                # you browse AND carries the playback-speed button.
                components.html(
                    _audio_player_html(
                        ep["audio_url"], ep.get("title", ""), ep.get("id", ""),
                        mode="audio"),
                    height=90)
                _render_course_transcript(ep, course.get("hosts", {}))
            elif has_script:
                # No audio file — the browser reads the script with built-in TTS.
                st.caption("▶ Play uses your browser's built-in voice. Pick two "
                           "voices for the two hosts, adjust speed, or tap any line "
                           "to jump. (No sound? Your browser may block speech — the "
                           "transcript is right there to read.)")
                components.html(_course_player_html(ep, course.get("hosts", {})),
                                height=560, scrolling=False)
            else:
                st.info("Audio for this episode is coming soon.")
    with tab_quiz:
        _render_course_quiz(course)
    if course.get("attribution"):
        st.caption("ℹ️ " + course["attribution"])


def _render_featured_course() -> None:
    """Interactive-course library at the top of the Learning tab. Lists every
    available course (bot-served, bundled fallback) with a picker; a single
    course renders directly."""
    library = _courses_library()
    if not library:
        return
    # Keep the Elements of AI Ch.1 course first (the featured on-ramp).
    library = sorted(library, key=lambda c: c.get("course_id") != "elements-of-ai-ch1")
    with st.container(border=True):
        st.markdown("#### 🎧 Interactive courses — listen & test  ·  *new*")
        st.caption("Audio + quiz versions of curriculum resources — a full "
                   "**audio deep dive** plus short recap episodes and a graded "
                   "quiz each. Starting with Elements of AI; more modules can be "
                   "generated and added over time.")
        if len(library) > 1:
            ids = [c.get("course_id") for c in library]
            labels = {c.get("course_id"): c.get("title", c.get("course_id"))
                      for c in library}
            chosen = st.selectbox(
                "Course", ids, format_func=lambda cid: labels.get(cid, cid),
                key="course_library_pick",
            )
        else:
            chosen = library[0].get("course_id")
        course = _load_course(chosen) if chosen else None
        if course:
            _render_course(course)


def page_learning() -> None:
    """Learning Center — the curriculum (trading + AI) with progress tracking.

    A READING/interaction surface (special-cased top-level view like Roadmap).
    Content comes from the bot's /api/bot/learning/curriculum (bundled fallback
    committed here); per-resource progress is read from and written to
    /api/bot/learning/progress (durable + cross-device). No auto-refresh."""
    st.header("📚 Learning Center")

    cur, source_note = _learning_curriculum()
    if not cur:
        st.info("The learning curriculum isn't available yet.")
        return

    if cur.get("subtitle"):
        st.caption(cur["subtitle"])

    # Progress store — durable, from the bot. If unavailable (endpoint not
    # deployed), the tab stays a read-only reading surface.
    prog, _perr = _fetch("/api/bot/learning/progress")
    progress_available = bool(isinstance(prog, dict) and prog.get("present"))
    items = prog.get("items", {}) if progress_available else {}

    if source_note:
        st.warning(source_note)
    elif not progress_available:
        st.caption("ℹ️ Progress tracking activates once the bot's learning "
                   "endpoint is live — content below is fully browsable now.")

    tracks = cur.get("tracks", [])

    def _key(rid: str) -> str:
        return f"lrn_{rid}"

    # Seed every checkbox's session_state from the server ONCE (before both the
    # roll-up and the widgets), so the roll-up can be computed from widget state
    # and stay in lock-step with the checkboxes on screen.
    all_ids = [r["id"] for t in tracks for m in t.get("modules", [])
               for r in m.get("resources", [])]
    for rid in all_ids:
        k = _key(rid)
        if k not in st.session_state:
            st.session_state[k] = (items.get(rid, {}).get("status") == "done")

    total = len(all_ids)
    done = sum(1 for rid in all_ids if st.session_state.get(_key(rid)))

    c1, c2, c3 = st.columns(3)
    c1.metric("Resources", total)
    c2.metric("✅ Done", done)
    c3.metric("Remaining", total - done)
    if total:
        st.progress(done / total,
                    text=f"{done}/{total} complete ({done / total * 100:.0f}%)")
    if st.session_state.get("_lrn_err"):
        st.error(f"Couldn't save progress: {st.session_state['_lrn_err']}")

    qs = cur.get("quickstart")
    if qs:
        with st.expander(f"⭐ {qs.get('title', 'Quick start')}", expanded=False):
            for s in qs.get("steps", []):
                st.markdown(f"- {s}")

    _render_featured_course()

    st.divider()

    def _toggle(rid: str, k: str) -> None:
        checked = bool(st.session_state.get(k))
        _, err = _post("/api/bot/learning/progress",
                       {"resource_id": rid,
                        "status": "done" if checked else "not_started"})
        if err:
            st.session_state[k] = not checked  # revert the widget on failure
            st.session_state["_lrn_err"] = err
        else:
            st.session_state.pop("_lrn_err", None)
            _fetch_cached.clear()

    for t in tracks:
        st.subheader(t.get("name", ""))
        if t.get("blurb"):
            st.caption(t["blurb"])
        for m in t.get("modules", []):
            mres = m.get("resources", [])
            mdone = sum(1 for r in mres if st.session_state.get(_key(r["id"])))
            num = m.get("num", "")
            label = f"{num}. {m.get('title', '')}  ·  {mdone}/{len(mres)}"
            with st.expander(label, expanded=False):
                if m.get("goal"):
                    st.markdown(f"*{m['goal']}*")
                goals = m.get("goals", [])
                if goals:
                    st.markdown("**You'll be able to:**")
                    for g in goals:
                        st.markdown(f"- {g}")
                if m.get("in_your_system"):
                    st.info(f"**◢ In your system** — {m['in_your_system']}")
                st.markdown("")
                for r in mres:
                    rid = r["id"]
                    k = _key(rid)
                    col1, col2 = st.columns([0.08, 0.92])
                    with col1:
                        st.checkbox(
                            "Mark done", key=k, on_change=_toggle, args=(rid, k),
                            disabled=not progress_available,
                            label_visibility="collapsed",
                        )
                    with col2:
                        flag = f" · *{r['flag']}*" if r.get("flag") else ""
                        st.markdown(
                            f"**[{r.get('title', '')}]({r.get('url', '')})**  ·  "
                            f"`{r.get('format', '')}` · {r.get('cost', '')}{flag}"
                        )
                        meta = " — ".join(
                            x for x in (r.get("by"), r.get("note")) if x)
                        if meta:
                            st.caption(meta)
        st.divider()

    cad = cur.get("cadence")
    if cad:
        with st.expander(f"🗓️ {cad.get('title', 'Suggested cadence')}",
                         expanded=False):
            for s in cad.get("steps", []):
                st.markdown(f"- {s}")
    scam = cur.get("scam_flags")
    if scam:
        with st.expander(f"🚩 {scam.get('title', 'What to avoid')}",
                         expanded=False):
            for s in scam.get("items", []):
                st.markdown(f"- {s}")
    shelf = cur.get("shelf")
    if shelf:
        st.markdown("**📌 Reference shelf**")
        cols = st.columns(3)
        for i, s in enumerate(shelf):
            with cols[i % 3]:
                st.markdown(f"[{s.get('name', '')}]({s.get('url', '')}) — "
                            f"{s.get('desc', '')}")
    if cur.get("updated"):
        st.caption(f"Curriculum updated {cur['updated']}.")


def page_gpu_spend() -> None:
    """M19 Tier-1 spot-GPU burst spend — per-training-session cost + monthly total vs cap.

    Read-only view of the bot's `/api/bot/gpu/spend` (committed
    `comms/gpu_spend_ledger.json`). Shows the running month vs the $10 cap, then a
    per-session table (each training run's cost) + a by-month rollup.
    """
    st.subheader("🖥️ GPU training spend")
    st.caption(
        "M19 Tier-1 spot-GPU burst tier — every training session's cost, tracked "
        "against the monthly cap. Free CPU work (corpus/Tier-0) never appears here."
    )

    def _f(v: Any) -> float:
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    data, err = _fetch("/api/bot/gpu/spend")
    if err:
        st.warning(f"Could not load GPU spend: {err}")
        return
    if not data or not data.get("present"):
        st.info("GPU spend tracking not available yet.")
        return

    budget = data.get("budget_usd_per_month")
    cur = data.get("current_month_usd")
    runs = data.get("runs") or []
    month = data.get("current_month") or "—"
    provider = data.get("provider") or "—"

    c1, c2, c3, c4 = st.columns(4)
    c1.metric(f"This month ({month})", _money(cur))
    c2.metric("Monthly cap", _money(budget))
    c3.metric("Remaining", _money(data.get("budget_remaining_usd")))
    c4.metric("Sessions this month", data.get("current_month_runs", 0))

    if budget:
        pct = min(1.0, max(0.0, _f(cur) / _f(budget))) if _f(budget) else 0.0
        st.progress(pct, text=f"{_money(cur)} / {_money(budget)} ({pct*100:.0f}%)")
    if data.get("over_budget"):
        st.error("🔴 Over the monthly GPU budget — the burst workflow's gate will refuse new runs.")

    st.caption(
        f"Provider: **{provider}** · lifetime spend: **{_money(data.get('lifetime_usd'))}** "
        f"over {data.get('run_count', 0)} session(s)."
    )

    st.markdown("#### Training sessions")
    if not runs:
        st.info(
            "No GPU training sessions billed yet. Each burst run appends its cost here "
            "(the first is the ~1-GPU-hr T1.1 deep-head bake-off once the provider key is set)."
        )
    else:
        rows = [
            {
                "Ended": (r.get("ended_at") or r.get("started_at") or "—"),
                "Experiment": r.get("experiment") or "—",
                "GPU": r.get("gpu_type") or "—",
                "GPU-hrs": r.get("gpu_hours") if r.get("gpu_hours") is not None else "—",
                "$/hr": _money(r.get("rate_usd_per_hour")),
                "Cost": _money(r.get("cost_usd")),
                "Month cumul.": _money(r.get("cumulative_month_usd")),
                "Status": r.get("status") or "—",
            }
            for r in runs
        ]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    by_month = data.get("by_month") or []
    if by_month:
        st.markdown("#### By month")
        mrows = [
            {"Month": m.get("month"), "Spend": _money(m.get("usd")), "Sessions": m.get("runs")}
            for m in by_month
        ]
        st.dataframe(pd.DataFrame(mrows), use_container_width=True, hide_index=True)


# ── Detail-page dispatch (sub-page key → render fn) — reused as the detail
# views behind the section landings. Overview is special (needs stats), handled
# in main().
def _detail_dispatch() -> dict:
    return {
        "Performance":   page_performance,
        "Insights":      page_insights,
        "Reports":       page_reports,
        "Strategies":    page_strategies,
        "Models":        page_models,
        "GPU Spend":     page_gpu_spend,
        "Exit Ladder":   page_exit_ladder,
        "Backtesting":   page_backtesting,
        "Promotion":     page_promotion,
        "News":          page_news,
        "Accounts":      page_accounts,
        "Prop":          page_prop,
        "Positions":     page_positions,
        "Trades":        page_trades,
        "Order Packages": page_order_packages,
        "Signals":       page_signals,
        "Data Explorer": page_data_explorer,
        "Logs":          page_logs,
        "Health":        page_health,
    }


def _render_section_landing(section: str) -> None:
    """Render a section as a stack of summary cards that EXPAND/COLLAPSE in place.

    Each sub-page is a bordered card: title + one-line blurb + an Open/Close
    toggle. When open, the page's full content renders inline below — multiple
    can be open at once (stacked), and switching sections keeps each card's
    open state. We deliberately use a toggle + container (NOT st.expander): the
    detail pages use st.expander internally and nested expanders are illegal."""
    st.header(section)
    st.caption("Tap **Open** to expand a card in place; tap again to collapse.")
    expanded: set = st.session_state.setdefault("expanded_pages", set())
    dispatch = _detail_dispatch()
    for pg in SECTIONS.get(section, []):
        is_open = pg in expanded
        with st.container(border=True):
            head, ctrl = st.columns([5, 1])
            with head:
                st.markdown(f"**{pg}**")
                st.caption(PAGE_DESC.get(pg, ""))
            with ctrl:
                if st.button("▾ Close" if is_open else "▸ Open",
                             key=f"toggle_{pg}", use_container_width=True):
                    expanded.discard(pg) if is_open else expanded.add(pg)
                    st.rerun()
            if is_open:
                st.divider()
                # Each open card renders inside its own fragment: live pages
                # (per _PAGE_REFRESH_S) update in place on their cadence;
                # static pages get interaction-scoped reruns only. Either way
                # the rest of the page — other open cards included — never
                # re-renders underneath you.
                _live_fragment(
                    dispatch.get(pg, lambda: st.caption("—")),
                    every=_PAGE_REFRESH_S.get(pg),
                )


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    # Data refresh is fragment-scoped (see _live_fragment): live regions
    # re-render in place on their own cadence and the page never reloads
    # around you. The streamlit-autorefresh component is kept for two jobs
    # only: (1) the "fresh browser (re)load" signal — it REMOUNTS on a true
    # document load, so its counter resets to 0 even when Streamlit resumes
    # the Python session_state; a 0 that follows a non-0 (or the very first
    # run) is a fresh-load pulse, distinct from periodic ticks and from
    # interaction reruns — and (2) a slow HEARTBEAT_S safety-net full rerun so
    # a long-idle tab can't drift stale. On old Streamlit without fragments it
    # falls back to being the primary POLL_INTERVAL_S full-page poller. We
    # read it BEFORE the sidebar so the nav radio can be reset on this same
    # run. `live` uses the last-known toggle value (the toggle itself is
    # rendered inside render_sidebar).
    live = bool(st.session_state.get("live_data", _DEFAULT_LIVE))
    _hb_s = HEARTBEAT_S if _FRAGMENT_OK else POLL_INTERVAL_S
    poll_count = (st_autorefresh(interval=_hb_s * 1000, key="poll")
                  if (live and _AUTOREFRESH_AVAILABLE) else None)
    _poll_prev = st.session_state.get("_poll_prev")
    st.session_state["_poll_prev"] = poll_count
    _seen = st.session_state.get("_session_seen")
    st.session_state["_session_seen"] = True
    fresh_load = (
        (poll_count == 0 and _poll_prev != 0)   # autorefresh on: remount pulse
        or (poll_count is None and not _seen)    # autorefresh off: first run only
    )

    # A fresh (re)load always opens on Overview. We rotate the nav radio's
    # per-session key nonce (`_nav_key`) so the radio has NO browser-cached value
    # to restore and falls back to its Overview default — this is what makes a
    # refresh land on Overview instead of reopening the last-viewed section
    # (pre-setting session_state did NOT work: Streamlit restored the cached
    # radio value over it). Skipped when a ?report= deeplink targets a section,
    # so the Telegram report link still opens Reports.
    if fresh_load and not st.query_params.get("report"):
        st.session_state["_nav_nonce"] = uuid.uuid4().hex[:8]

    # Honor a ?report=<id> deep link BEFORE the nav widgets render, so its queued
    # section lands on this run (uses the just-rotated nonce when fresh).
    _consume_report_deeplink()

    # Render the sidebar — it owns the "Live data" toggle and the section nav.
    section = render_sidebar()

    if section == "Overview":
        # Overview is the exec glance + live monitor (no card stack). Wrapped in
        # an interaction-scoped fragment (every=None): a tap reruns only this
        # region (the sidebar/nav stay put), but there is NO wall-clock timer —
        # the constant re-fetch churn was pushing the app over its memory cap and
        # racing taps (BL-20260710-DASH-MEMORY). Fresh data comes on any
        # interaction / navigation / ↻ Refresh / the 300 s heartbeat.
        def _overview_region() -> None:
            stats, stats_err = _fetch("/api/bot/stats")
            page_overview(stats, stats_err)

        _live_fragment(_overview_region, every=None)
    elif section == "Roadmap":
        # Roadmap is a full-page progress visualization (no card stack) and a
        # READING surface — no auto-refresh, interaction-scoped reruns only.
        # Alert-severity banners (trainer/account down) stay visible here too.
        _render_notification_banner(alerts_only=True)
        _live_fragment(page_roadmap)
    elif section == "Learning":
        # Learning Center — a READING/interaction surface (curriculum + the
        # operator's progress marks). No auto-refresh; interaction-scoped reruns
        # only, like Roadmap. Alert-severity banners stay visible here too.
        _render_notification_banner(alerts_only=True)
        _live_fragment(page_learning)
    else:
        # Section landing: stacked cards that expand/collapse in place. Show
        # can't-miss ALERTS (trainer/account down) on every section — the full
        # banner (incl. the info trade-open line) lives on Overview.
        _render_notification_banner(alerts_only=True)
        _render_section_landing(section)

    # Legacy fallback: no fragments AND no autorefresh component — blocking
    # sleep+rerun is the only way to poll at all.
    if live and not _AUTOREFRESH_AVAILABLE and not _FRAGMENT_OK:
        time.sleep(POLL_INTERVAL_S)
        st.rerun()


if __name__ == "__main__":
    main()
