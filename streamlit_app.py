"""RETIRED — this Streamlit dashboard is no longer a consumer of the bot API.

Retired 2026-09-01 by operator decision
(``BL-20260901-RETIRE-ANDROID-AND-STREAMLIT-FROM-THE-LIVE-FEED`` in the bot
repo). **Replaced by the Svelte SPA in this same repository** (``webapp/``),
served from GitHub Pages at
https://benbaichmankass.github.io/ict-trader-dashboard/ .

WHY THIS FILE STILL EXISTS AND IS NOT JUST DELETED. Streamlit Community Cloud
deploys whatever ``streamlit_app.py`` is on ``main``. Deleting it would leave
the deployed app serving its last good build — a live-looking dashboard,
still polling the bot, that no longer corresponds to anything in this repo.
Replacing it with this stub is what actually takes the app OFF the live feed:
the next deploy serves a page that **makes no upstream call at all**.

⚠️ THIS FILE MUST NOT REGAIN A NETWORK CALL. It has no ``requests`` import, no
``BOT_API_URL``, and no bot-API access of any kind, deliberately. The whole
point of the retirement is that the consumer set is now exactly one (the SPA),
which is the precondition for gating the bot's read surface — see Phase H in
the bot repo's ``docs/design/operating-layer-build-plan-DESIGN.md``. Re-adding
a call here silently re-opens a question the operator has already closed.

The previous 9,628-line implementation is preserved verbatim, and in git
history, at ``archive/streamlit_app_RETIRED_2026-09-01.py``.
"""
from __future__ import annotations

import streamlit as st

SPA_URL = "https://benbaichmankass.github.io/ict-trader-dashboard/"
RETIRED_ON = "2026-09-01"
ARCHIVED_AT = "archive/streamlit_app_RETIRED_2026-09-01.py"

st.set_page_config(page_title="ICT Trader — dashboard moved", page_icon="🗄️")

st.title("🗄️ This dashboard has been retired")

st.warning(
    f"**Retired {RETIRED_ON}.** The Streamlit dashboard is no longer connected "
    "to the trading bot and shows no live data. It has been replaced by the "
    "**Svelte SPA**, which is the only live consumer of the bot API."
)

st.markdown(f"### 👉 [Open the current dashboard]({SPA_URL})")

st.divider()

st.markdown(
    f"""
**What happened**

- The Streamlit app read the bot API server-side over plain HTTP. The SPA
  reads it browser-direct over HTTPS through Caddy — a different transport,
  and now the only one.
- This entry point was replaced with a notice on {RETIRED_ON}. It makes **no
  request to the bot API**, so nothing here can be stale or half-live.
- The previous implementation is preserved at `{ARCHIVED_AT}` and in git
  history. It is kept for reference only and is **not** maintained.

**If you are a Claude session:** do not restore this app or point it back at
the bot. The retirement is what makes gating the bot's read surface tractable
(Phase H). Read the bot repo's `docs/design/operating-layer-build-plan-DESIGN.md`
before changing anything here.
"""
)
