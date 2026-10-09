"""trdex Streamlit dashboard MVP.

Run with:
    streamlit run src/trdex/dashboard/app.py
"""

from __future__ import annotations

import os
import time

import httpx
import plotly.express as px
import streamlit as st

st.set_page_config(page_title="trdex", page_icon="📈", layout="wide")

# Default API URL resolution order:
#   1. TRDEX_DASHBOARD_API_URL env var (set in docker-compose for the
#      containerised deploy — resolves to http://app:8000 via the
#      internal Docker network)
#   2. http://localhost:8000 fallback for developers running
#      `streamlit run ...` directly on their laptop against a local
#      uvicorn. The user can always override via the sidebar input.
_DEFAULT_BASE_URL = os.environ.get("TRDEX_DASHBOARD_API_URL", "http://localhost:8000")
_DEFAULT_API_KEY = os.environ.get("TRDEX_DASHBOARD_API_KEY", "")

# ── Sidebar config ──────────────────────────────────────────────────────────

with st.sidebar:
    st.title("⚙️ Config")
    base_url = st.text_input("API URL", value=_DEFAULT_BASE_URL)
    api_key = st.text_input("API Key", value=_DEFAULT_API_KEY, type="password")
    refresh_interval = st.selectbox("Auto-refresh", [5, 15, 30, 60], index=1)
    manual_refresh = st.button("🔄 Refresh now")

_headers = {"X-API-Key": api_key} if api_key else {}


# ── Data fetchers (cached) ──────────────────────────────────────────────────


def _format_http_error(path: str, verb: str, exc: Exception) -> str:
    """Build a human-readable error string from an httpx exception.

    FastAPI raises ``HTTPException(status_code=..., detail="message")``
    which serialises as ``{"detail": "message"}`` in the response body.
    The default ``raise_for_status()`` error only carries the status
    line (``Server error '503 Service Unavailable' ...``) which is
    useless for the operator — the interesting bit is the ``detail``
    field. This helper unwraps it whenever possible and falls back to
    the generic message otherwise.
    """
    if isinstance(exc, httpx.HTTPStatusError):
        try:
            payload = exc.response.json()
            detail = payload.get("detail") if isinstance(payload, dict) else None
            if detail:
                return f"{verb} {path} → {exc.response.status_code}: {detail}"
        except Exception:
            pass
        return f"{verb} {path} → {exc.response.status_code} {exc.response.reason_phrase}"
    return f"{verb} {path} → {type(exc).__name__}: {exc}"


@st.cache_data(ttl=30)
def fetch(path: str, base: str, key: str) -> dict | None:
    headers = {"X-API-Key": key} if key else {}
    try:
        r = httpx.get(f"{base}{path}", headers=headers, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        st.error(_format_http_error(path, "GET", e))
        return None


def get(path: str) -> dict | None:
    return fetch(path, base_url, api_key)


def post(path: str, *, params: dict | None = None, json_body: dict | None = None, timeout: int = 60) -> dict | None:
    """POST to the configured API base URL with the current API key."""
    headers = {"X-API-Key": api_key} if api_key else {}
    try:
        r = httpx.post(
            f"{base_url}{path}",
            params=params,
            json=json_body,
            headers=headers,
            timeout=timeout,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        st.error(_format_http_error(path, "POST", e))
        return None


def put(path: str, json_body: dict, timeout: int = 10) -> dict | None:
    """PUT to the configured API base URL with the current API key."""
    headers = {"X-API-Key": api_key} if api_key else {}
    try:
        r = httpx.put(f"{base_url}{path}", json=json_body, headers=headers, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        st.error(_format_http_error(path, "PUT", e))
        return None


# ── Layout ───────────────────────────────────────────────────────────────────

st.title("📈 trdex Dashboard")

# Health check
health = get("/v1/health")
if health:
    st.caption(f"API status: ✅ v{health.get('version', '?')}")
else:
    st.error("Cannot reach the trdex API. Is it running?")
    st.stop()

# ── Readiness check (sim → live gate) ──────────────────────────────────────

readiness = get("/v1/system/readiness")
if readiness:
    verdict = readiness.get("verdict", "UNKNOWN")
    if verdict == "READY":
        st.success("Simulation gate: READY for live trading")
    else:
        failures = readiness.get("failures", [])
        st.warning(f"Simulation gate: NOT READY — {'; '.join(failures)}")
    for _w in readiness.get("warnings", []):
        st.info(f"Readiness warning: {_w}")
    with st.expander("Readiness details"):
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Sim days", readiness.get("sim_days", 0))
        c2.metric("Trades", readiness.get("total_trades", 0))
        c3.metric("Win rate", f"{readiness.get('win_rate', 0):.1%}")
        c4.metric("Max DD", f"{readiness.get('max_drawdown_pct', 0):.1%}")
        criteria = readiness.get("criteria", {})
        st.caption(
            f"Criteria: {criteria.get('min_days', '?')} days, "
            f"{criteria.get('min_trades', '?')} trades, "
            f">{criteria.get('min_win_rate', '?'):.0%} win rate, "
            f"<{criteria.get('max_drawdown', '?'):.0%} drawdown"
        )
        st.caption(
            f"Regime bounds: CV {criteria.get('regime_cv_min') or 'unset'}"
            f" to {criteria.get('regime_cv_max') or 'unset'}, "
            f"data end {criteria.get('regime_data_end') or 'unset'} "
            f"(max age {criteria.get('regime_max_age_days', '?')} days), "
            f"changed {criteria.get('regime_set_at') or 'unknown'}"
        )

# ── Portfolio snapshot ──────────────────────────────────────────��─────────────

st.header("Portfolio")
snapshot = get("/v1/portfolio")
if snapshot:
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Equity", f"${float(snapshot.get('equity', 0)):,.2f}")
    c2.metric("Balance", f"${float(snapshot.get('balance', 0)):,.2f}")
    c3.metric("Realized P&L", f"${float(snapshot.get('total_pnl', 0)):+,.2f}")
    c4.metric("Total Trades", snapshot.get("total_trades", 0))
    win_rate = snapshot.get("win_rate", 0)
    c5.metric("Win Rate", f"{win_rate:.1%}")

# ── Open positions ────────────────────────────────────────────────────────────

st.subheader("Open Positions")
positions_data = get("/v1/portfolio/positions")
if positions_data and positions_data.get("positions"):
    import pandas as pd
    rows = positions_data["positions"]
    df = pd.DataFrame(rows)
    for col in ["entry_price", "current_price", "amount", "unrealized_pnl", "unrealized_pnl_pct"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    # Format prices with enough decimals for microcap coins (e.g. ENJ $0.03077)
    for col in ["entry_price", "current_price"]:
        if col in df.columns:
            df[col] = df[col].map(lambda x: f"{x:.8g}" if x is not None else "")
    if "amount" in df.columns:
        df["amount"] = df["amount"].map(lambda x: f"{x:,.2f}" if x is not None else "")
    if "unrealized_pnl" in df.columns:
        df["unrealized_pnl"] = df["unrealized_pnl"].map(lambda x: f"${x:+,.4f}" if x is not None else "")
    if "unrealized_pnl_pct" in df.columns:
        df["unrealized_pnl_pct"] = df["unrealized_pnl_pct"].map(lambda x: f"{x:.2%}" if x is not None else "")
    st.dataframe(df, use_container_width=True)

    # Per-position manual close button
    st.caption("Manual close")
    for row in rows:
        pos_id = row.get("id")
        if pos_id is None:
            continue
        cols = st.columns([3, 2, 2, 2])
        cols[0].write(f"**{row['symbol']}** — {row['side']} (id={pos_id})")
        cols[1].write(f"entry ${row['entry_price']}")
        cols[2].write(f"pnl {row.get('unrealized_pnl_pct', '')}")
        if cols[3].button("Close", key=f"close_{pos_id}"):
            result = post(f"/v1/portfolio/close/{pos_id}")
            if result:
                st.success(
                    f"Closed position {pos_id}: pnl={result.get('pnl')} new_balance={result.get('new_balance')}"
                )
                st.cache_data.clear()
                st.rerun()
else:
    st.info("No open positions.")

with st.expander("Manual Open Position"):
    with st.form("manual_open_form", clear_on_submit=True):
        mo_symbol = st.text_input("Symbol (e.g. BTC/USDT)", key="mo_symbol")
        mo_side = st.selectbox("Side", options=["BUY", "SELL"], key="mo_side")
        mo_amount = st.text_input("Amount (USDT quote — e.g. 500)", key="mo_amount", value="500")
        if st.form_submit_button("Open Position"):
            try:
                amt = float(mo_amount)
            except ValueError:
                st.error("Amount must be a number.")
                amt = None
            if amt is not None and mo_symbol:
                result = post(
                    "/v1/portfolio/open",
                    json_body={"symbol": mo_symbol.upper(), "side": mo_side, "amount": str(amt)},
                )
                if result:
                    st.success(
                        f"Opened position {result.get('position_id')}: "
                        f"{result.get('amount')} {result.get('symbol')} @ {result.get('entry_price')}"
                    )
                    st.cache_data.clear()
                    st.rerun()

# ── P&L history chart ─────────────────────────────────────────────────────────

st.subheader("Realized P&L History (30d)")
history_data = get("/v1/portfolio/pnl_history?days=30")
if history_data and history_data.get("history"):
    import pandas as pd
    df_hist = pd.DataFrame(history_data["history"])
    df_hist["timestamp"] = pd.to_datetime(df_hist["timestamp"])
    fig = px.line(
        df_hist,
        x="timestamp",
        y="cumulative_pnl",
        labels={"cumulative_pnl": "Cumulative P&L (USDT)", "timestamp": ""},
        template="plotly_dark",
    )
    fig.update_traces(line_color="#00d4aa")
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("No closed trades yet — P&L history will appear here.")

# ── P&L by source ────────────────────────────────────────────────────────────

st.subheader("Realized P&L by Source")
pnl_source = get("/v1/portfolio/pnl_by_source")
if pnl_source and pnl_source.get("by_source"):
    import pandas as pd
    df_src = pd.DataFrame(pnl_source["by_source"])
    if not df_src.empty:
        fig2 = px.bar(
            df_src,
            x="source",
            y="realized_pnl",
            color="realized_pnl",
            color_continuous_scale=["#e05555", "#00d4aa"],
            labels={"realized_pnl": "Realized P&L (USDT)", "source": "Source"},
            template="plotly_dark",
        )
        st.plotly_chart(fig2, use_container_width=True)
else:
    st.info("No closed trades by source yet.")

# ── Agent Decisions ──────────────────────────────────────────────────────────

st.header("🤖 Agent Decisions")

col_run, col_sym, col_tf = st.columns([1, 2, 1])
with col_sym:
    agent_symbol = st.text_input("Symbol", value="BTC/USDT", key="agent_symbol")
with col_tf:
    agent_tf = st.selectbox("Timeframe", ["1h", "4h", "1d", "15m"], key="agent_tf")
with col_run:
    st.write("")
    run_agent = st.button("▶ Run Agent Now", key="run_agent_btn")

if run_agent:
    with st.spinner(f"Running agent cycle for {agent_symbol}..."):
        result = post("/v1/agent/run", params={"symbol": agent_symbol, "timeframe": agent_tf})
        if result:
            _intent_display = {
                "open_long": ("🟢", "OPEN LONG"), "close_long": ("🔴", "CLOSE LONG"),
                "open_short": ("🔴", "OPEN SHORT"), "close_short": ("🟢", "CLOSE SHORT"),
                "hold": ("🟡", "HOLD"),
                # Legacy values (pre-intent refactor rows still in DB)
                "BUY": ("🟢", "BUY"), "SELL": ("🔴", "SELL"), "HOLD": ("🟡", "HOLD"),
            }
            _icon, _label = _intent_display.get(result.get("signal", ""), ("⚪", result.get("signal", "?")))
            st.success(f"{_icon} Intent: **{_label}** | Confidence: {result.get('confidence', 0):.1%} | Order: {result.get('order_status')}")
            st.caption(f"Reasoning: {result.get('reasoning', '—')}")
            if result.get("indicators"):
                st.json(result["indicators"])
            if result.get("error"):
                st.error(f"Error: {result['error']}")

st.subheader("Recent Agent History")
history = get(f"/v1/agent/history?limit=20")
if history:
    import pandas as pd
    df_agent = pd.DataFrame(history)
    if not df_agent.empty:
        df_agent["confidence"] = pd.to_numeric(df_agent["confidence"], errors="coerce").map(lambda x: f"{x:.1%}")
        # Bug 11 fix: HOLD intents have no order to approve/reject.
        # Showing ❌ on every HOLD row suggests the system is blocking
        # something when in reality there is nothing to block. Use "—"
        # for HOLD, ✅/❌ only for actionable intents.
        _hold_intents = {"hold", "HOLD"}
        df_agent["risk_approved"] = df_agent.apply(
            lambda row: "—" if row.get("signal", "") in _hold_intents else ("✅" if row["risk_approved"] else "❌"),
            axis=1,
        )
        intent_icons = {
            "open_long": "🟢 OPEN LONG", "close_long": "🔴 CLOSE LONG",
            "open_short": "🔴 OPEN SHORT", "close_short": "🟢 CLOSE SHORT",
            "hold": "🟡 HOLD",
            # Legacy values (pre-intent refactor rows still in DB)
            "BUY": "🟢 BUY", "SELL": "🔴 SELL", "HOLD": "🟡 HOLD",
        }
        df_agent["intent"] = df_agent["signal"].map(lambda s: intent_icons.get(s, s))
        st.dataframe(
            df_agent[["symbol", "intent", "confidence", "risk_approved", "order_status", "ran_at"]],
            use_container_width=True,
        )
    else:
        st.info("No agent runs yet. Click 'Run Agent Now' above.")
else:
    st.info("No agent runs yet.")

# ── Risk / Stop-Loss ──────────────────────────────────────────────────────────

st.header("🛡️ Risk Monitor")

risk_status = get("/v1/risk/status")
if risk_status:
    ks = risk_status.get("kill_switch", {})
    if ks.get("active"):
        st.error(f"🚨 KILL SWITCH ACTIVE — {ks.get('reason', '')}")
        if st.button("⚠️ Reset Kill Switch", key="ks_reset"):
            if post("/v1/risk/kill-switch/reset") is not None:
                st.success("Kill switch reset. Trading re-enabled.")
                st.cache_data.clear()
                st.rerun()
    else:
        st.success("✅ Kill switch inactive — trading enabled")

    with st.expander("Stop-Loss Thresholds (base — adaptive scales up for volatile coins)"):
        thresholds = risk_status.get("thresholds", {})
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Position SL", f"{thresholds.get('position_sl_pct', 0):.1%}")
        c2.metric("Position TP", f"{thresholds.get('position_tp_pct', 0):.1%}")
        c3.metric("Trailing Stop", f"{thresholds.get('trailing_stop_pct', 0):.1%}")
        c4.metric("Daily DD limit", f"{thresholds.get('daily_drawdown_pct', 0):.1%}")
        c5.metric("Max DD limit", f"{thresholds.get('max_drawdown_pct', 0):.1%}")

        with st.form("edit_thresholds_form"):
            st.caption("Edit base thresholds (runtime, not persisted — reverts on restart)")
            tc1, tc2, tc3, tc4, tc5 = st.columns(5)
            with tc1:
                new_sl = st.number_input("SL %", value=thresholds.get("position_sl_pct", 0.05) * 100, min_value=0.1, max_value=50.0, step=0.5, format="%.1f")
            with tc2:
                new_tp = st.number_input("TP %", value=thresholds.get("position_tp_pct", 0.10) * 100, min_value=1.0, max_value=100.0, step=1.0, format="%.1f")
            with tc3:
                new_trail = st.number_input("Trail %", value=thresholds.get("trailing_stop_pct", 0.03) * 100, min_value=0.5, max_value=50.0, step=0.5, format="%.1f")
            with tc4:
                new_dd = st.number_input("Daily DD %", value=thresholds.get("daily_drawdown_pct", 0.10) * 100, min_value=1.0, max_value=50.0, step=1.0, format="%.1f")
            with tc5:
                new_maxdd = st.number_input("Max DD %", value=thresholds.get("max_drawdown_pct", 0.20) * 100, min_value=5.0, max_value=100.0, step=5.0, format="%.1f")
            if st.form_submit_button("Apply"):
                import httpx as _httpx
                headers = {"X-API-Key": api_key} if api_key else {}
                try:
                    r = _httpx.put(
                        f"{base_url}/v1/risk/thresholds",
                        json={
                            "position_sl_pct": new_sl / 100,
                            "position_tp_pct": new_tp / 100,
                            "trailing_stop_pct": new_trail / 100,
                            "daily_drawdown_pct": new_dd / 100,
                            "max_drawdown_pct": new_maxdd / 100,
                        },
                        headers=headers,
                        timeout=10,
                    )
                    r.raise_for_status()
                    st.success("Thresholds updated")
                    st.cache_data.clear()
                    st.rerun()
                except Exception as e:
                    st.error(_format_http_error("/v1/risk/thresholds", "PUT", e))

    col_check, col_kill = st.columns(2)
    with col_check:
        if st.button("🔍 Check Now", key="sl_check"):
            data = post("/v1/risk/check", timeout=30)
            if data is not None:
                st.info(f"Check complete — {data.get('events_fired', 0)} event(s) fired")
    with col_kill:
        kill_reason = st.text_input("Kill switch reason", value="Manual override", key="kill_reason")
        if st.button("🔴 Activate Kill Switch", key="ks_activate", type="secondary"):
            if post("/v1/risk/kill-switch/activate", params={"reason": kill_reason}) is not None:
                st.warning("Kill switch activated.")
                st.cache_data.clear()
                st.rerun()

risk_events = get("/v1/risk/events")
if risk_events and risk_events.get("events"):
    with st.expander(f"Recent Stop-Loss Events ({len(risk_events['events'])})"):
        import pandas as pd
        df_ev = pd.DataFrame(risk_events["events"])
        st.dataframe(df_ev, use_container_width=True)

# ── Per-symbol risk config ─────────────────────────────────────────────────────

with st.expander("⚙️ Per-Symbol Risk Thresholds"):
    st.caption(
        "Override SL/TP/trailing per symbol. Leave blank = adaptive default "
        "(proportional to the symbol's volatility CV). The adaptive formula "
        "is: max(global_base, multiplier × CV)."
    )
    sym_configs = get("/v1/risk/symbol-config")
    if sym_configs and sym_configs.get("configs"):
        import pandas as pd
        df_sc = pd.DataFrame(sym_configs["configs"])
        for col in ["sl_pct", "tp_pct", "trailing_pct"]:
            if col in df_sc.columns:
                df_sc[col] = df_sc[col].map(
                    lambda x: f"{x:.2%}" if x is not None else "adaptive"
                )
        st.dataframe(df_sc, use_container_width=True)
    else:
        st.info("No per-symbol overrides — all symbols use adaptive CV-based defaults.")

    with st.form("symbol_config_form", clear_on_submit=True):
        sc_cols = st.columns([2, 1, 1, 1, 2])
        with sc_cols[0]:
            sc_symbol = st.text_input("Symbol", placeholder="ENJ/USDT")
        with sc_cols[1]:
            sc_sl = st.text_input("SL %", placeholder="auto")
        with sc_cols[2]:
            sc_tp = st.text_input("TP %", placeholder="auto")
        with sc_cols[3]:
            sc_trail = st.text_input("Trail %", placeholder="auto")
        with sc_cols[4]:
            sc_notes = st.text_input("Notes", placeholder="optional")
        sc_submit = st.form_submit_button("Save Override")

    if sc_submit and sc_symbol:
        body = {"notes": sc_notes}
        if sc_sl:
            body["sl_pct"] = float(sc_sl) / 100
        if sc_tp:
            body["tp_pct"] = float(sc_tp) / 100
        if sc_trail:
            body["trailing_pct"] = float(sc_trail) / 100
        import httpx as _httpx
        headers = {"X-API-Key": api_key} if api_key else {}
        try:
            r = _httpx.put(
                f"{base_url}/v1/risk/symbol-config/{sc_symbol}",
                json=body,
                headers=headers,
                timeout=10,
            )
            r.raise_for_status()
            st.success(f"Saved config for {sc_symbol}")
            st.cache_data.clear()
            st.rerun()
        except Exception as e:
            st.error(_format_http_error(f"/v1/risk/symbol-config/{sc_symbol}", "PUT", e))

# ── Context / Ingestion ───────────────────────────────────────────────────────

with st.expander("📰 News Ingestion Status"):
    ctx_status = get("/v1/context/status")
    if ctx_status:
        sources_list = ctx_status.get("sources", [])
        c1, c2, c3 = st.columns(3)
        c1.metric("Sources", len(sources_list))
        c2.metric("Symbols", len(ctx_status.get("symbols", [])))
        c3.metric("Running", "✅" if ctx_status.get("running") else "❌")
        st.caption(f"Last run: {ctx_status.get('last_run', 'never')}")
        st.caption(f"Sources: {', '.join(sources_list) or 'none'}")
        # Only show Ingest Now when there is at least one source registered.
        # The backend returns 503 if called without sources — avoid the
        # noisy error by hiding the button entirely in that state.
        if sources_list:
            if st.button("🔄 Ingest Now", key="ingest_now"):
                data = post("/v1/context/run", timeout=120)
                if data is not None:
                    st.success(f"Ingested {data.get('docs_ingested', 0)} documents.")
        else:
            st.info(
                "No news sources configured. Set TRDEX_CRYPTOCOMPARE_API_KEY "
                "or TRDEX_STOCKDATA_API_KEY in the environment to enable."
            )

# ── Telegram Signals (observe-only) ────────────────────────────────────────

with st.expander("🟣 Telegram Signals (observe-only)"):
    sig_data = get("/v1/signals")
    if sig_data:
        report_rows = sig_data.get("report", []) or []
        recent_rows = sig_data.get("recent", []) or []

        # Observe-only mode persists budget=0, so the tracker's roi_pct
        # and total_pnl aggregates are always 0. Compute a synthetic
        # per-signal ROI from entry/exit prices and pretend each signal
        # was sized at SIMULATED_BUDGET — gives a comparable $ figure
        # without opening any real position.
        SIMULATED_BUDGET = 100.0

        def _signal_roi_pct(row: dict) -> float | None:
            entry = row.get("entry_price") or 0.0
            exit_p = row.get("exit_price")
            if exit_p is None or entry == 0:
                return None
            direction_sign = 1.0 if row.get("direction") == "BUY" else -1.0
            return (exit_p - entry) / entry * 100.0 * direction_sign

        for r in recent_rows:
            roi = _signal_roi_pct(r)
            r["_roi_pct"] = roi
            r["_pnl_sim"] = (SIMULATED_BUDGET * roi / 100.0) if roi is not None else None

        closed_recent = [r for r in recent_rows if r["_roi_pct"] is not None]
        sim_pnl_total = sum((r["_pnl_sim"] or 0.0) for r in closed_recent)
        wins_recent = sum(1 for r in closed_recent if (r["_roi_pct"] or 0) > 0)
        winrate_recent = (wins_recent / len(closed_recent)) if closed_recent else 0.0

        total_signals = sum(r.get("total_signals", 0) for r in report_rows)
        total_open = sum(r.get("open_signals", 0) for r in report_rows)
        total_closed = sum(r.get("closed_signals", 0) for r in report_rows)

        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Signals", total_signals)
        c2.metric("Open", total_open)
        c3.metric("Closed", total_closed)
        c4.metric("Win rate", f"{winrate_recent:.1%}")
        c5.metric("Sim P&L ($100/sig)", f"${sim_pnl_total:+.2f}")

        per_source: dict[str, dict] = {}
        for r in closed_recent:
            src = r.get("source", "")
            a = per_source.setdefault(src, {"closed": 0, "wins": 0, "losses": 0, "roi_sum": 0.0, "pnl_sim": 0.0})
            roi = r["_roi_pct"] or 0.0
            a["closed"] += 1
            a["roi_sum"] += roi
            a["pnl_sim"] += r["_pnl_sim"] or 0.0
            if roi >= 0:
                a["wins"] += 1
            else:
                a["losses"] += 1

        if per_source:
            st.caption(f"Per-source reliability (last {len(closed_recent)} resolved, simulated ${SIMULATED_BUDGET:.0f}/signal)")
            table_rows = []
            for src, a in sorted(per_source.items(), key=lambda kv: kv[1]["pnl_sim"], reverse=True):
                wr = (a["wins"] / a["closed"]) if a["closed"] else 0.0
                avg_roi = (a["roi_sum"] / a["closed"]) if a["closed"] else 0.0
                table_rows.append({
                    "source": src,
                    "closed": a["closed"],
                    "wins": a["wins"],
                    "losses": a["losses"],
                    "win_rate": f"{wr * 100:.1f}%",
                    "avg_roi": f"{avg_roi:+.2f}%",
                    "sim_pnl": f"${a['pnl_sim']:+.2f}",
                })
            st.dataframe(table_rows, hide_index=True, use_container_width=True)
        else:
            status_data = get("/v1/status")
            tg_streaming = (
                status_data.get("telegram", {}).get("streaming", False)
                if status_data else False
            )
            if tg_streaming:
                st.info(
                    "Monitor is active. No resolved signals yet — "
                    "waiting for evaluator to close TP/SL/stale."
                )
            else:
                st.info(
                    "Telegram monitor is not streaming. Check that API "
                    "credentials (api_id, api_hash, phone) are set in "
                    "API Keys below, channels are configured, and the "
                    "session file exists on the server."
                )

        if recent_rows:
            st.caption(f"Last {len(recent_rows)} signals")
            recent_table = []
            for row in recent_rows:
                entry = row.get("entry_price", 0.0)
                exit_p = row.get("exit_price")
                exit_str = f"{exit_p:.5g}" if exit_p is not None else "—"
                roi = row.get("_roi_pct")
                roi_str = f"{roi:+.2f}%" if roi is not None else "—"
                pnl_sim = row.get("_pnl_sim")
                pnl_sim_str = f"${pnl_sim:+.2f}" if pnl_sim is not None else "—"
                recent_table.append({
                    "when": (row.get("executed_at") or "")[:19].replace("T", " "),
                    "source": row.get("source", ""),
                    "symbol": row.get("symbol", ""),
                    "dir": row.get("direction", ""),
                    "entry": f"{entry:.5g}",
                    "exit": exit_str,
                    "roi%": roi_str,
                    "sim_pnl": pnl_sim_str,
                    "status": row.get("status", "open"),
                })
            st.dataframe(recent_table, hide_index=True, use_container_width=True)

        st.caption(
            "Observe-only mode: signals are recorded with no capital at risk. "
            f"Simulated P&L assumes ${SIMULATED_BUDGET:.0f} per signal. "
            "Post-hoc TP/SL evaluation runs hourly and updates status to "
            "`tp` / `sl` / `stale` once the window resolves."
        )
    else:
        st.info("Signals endpoint unavailable.")

# ── Telegram Channel Management ────────────────────────────────────────────

with st.expander("📡 Telegram Channels"):
    tg_settings = get("/v1/settings/telegram")
    tg_channels_csv = ""
    tg_titles_json = ""
    if tg_settings:
        tg_channels_csv = tg_settings.get("values", {}).get("telegram_channels", "")
        tg_titles_json = tg_settings.get("values", {}).get("telegram_channel_titles", "")
    tg_channels = [c.strip() for c in tg_channels_csv.split(",") if c.strip()] if tg_channels_csv else []

    # Resolve chat_id → human title. The backend persists this map on
    # every save of telegram_channels (see api/app.py _resolve_and_store_titles).
    tg_titles: dict[str, str] = {}
    if tg_titles_json:
        try:
            import json as _json
            tg_titles = _json.loads(tg_titles_json) or {}
        except (ValueError, TypeError):
            tg_titles = {}

    resolved = sum(1 for ch in tg_channels if ch in tg_titles)
    st.caption(
        f"{len(tg_channels)} channels monitored ({resolved} with resolved name; "
        "signals + news auto-classified)"
    )

    if tg_channels:
        cols = st.columns(min(len(tg_channels), 4))
        for i, ch in enumerate(tg_channels):
            with cols[i % len(cols)]:
                label = tg_titles.get(ch, ch)
                if label != ch:
                    # Truncate long titles so 4-col grid stays readable
                    display_label = label if len(label) <= 22 else label[:20] + "…"
                    btn_text = f"X {display_label}"
                else:
                    btn_text = f"X {ch}"
                if st.button(btn_text, key=f"rm_tg_{ch}", help=ch if label != ch else None):
                    new_list = [c for c in tg_channels if c != ch]
                    import httpx as _httpx
                    headers = {"X-API-Key": api_key} if api_key else {}
                    try:
                        _httpx.put(
                            f"{base_url}/v1/settings/telegram",
                            json={"values": {"telegram_channels": ",".join(new_list)}},
                            headers=headers,
                            timeout=10,
                        )
                        st.cache_data.clear()
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))

    col_add, col_btn = st.columns([3, 1])
    with col_add:
        new_channel = st.text_input(
            "Add channel (chat_id or @username)",
            key="add_tg_channel",
            value="",
        )
    with col_btn:
        st.write("")
        if st.button("+ Add", key="add_tg_btn") and new_channel:
            new_list = tg_channels + [new_channel.strip()]
            import httpx as _httpx
            headers = {"X-API-Key": api_key} if api_key else {}
            try:
                _httpx.put(
                    f"{base_url}/v1/settings/telegram",
                    json={"values": {"telegram_channels": ",".join(new_list)}},
                    headers=headers,
                    timeout=10,
                )
                st.success(f"Added {new_channel}")
                st.cache_data.clear()
                st.rerun()
            except Exception as e:
                st.error(str(e))

    st.caption(
        "Changes apply immediately via hot-reload (no redeploy needed). "
        "The parser auto-classifies each channel as signal source or news context."
    )

# ── Integrations (enable/disable components) ──────────────────────────────

_INTEGRATIONS_SPEC = [
    # (key, label, credential_key or None, group)
    ("binance_feed", "Binance feed (spot OHLCV + ticker)", None, "Feeds"),
    ("binance_ws_feed", "Binance WebSocket (real-time ticker)", None, "Feeds"),
    ("coingecko_feed", "CoinGecko feed", "coingecko_api_key", "Feeds"),
    ("cryptocompare_feed", "CryptoCompare feed", "cryptocompare_api_key", "Feeds"),
    ("alphavantage_feed", "AlphaVantage feed (FX, equity)", "alphavantage_api_key", "Feeds"),
    ("twelvedata_feed", "Twelve Data feed (FX, commodity)", "twelve_data_api_key", "Feeds"),
    ("yfinance_feed", "Yahoo Finance feed (fallback)", None, "Feeds"),
    ("freecryptoapi_feed", "FreeCryptoAPI feed", "freecryptoapi_key", "Feeds"),
    ("forex_feed", "Forex feed (exchangerate-api)", "forex_api_key", "Feeds"),
    ("cryptocompare_news", "CryptoCompare news ingestion", "cryptocompare_api_key", "News"),
    ("stockdata_news", "StockData news ingestion", "stockdata_api_key", "News"),
    ("perplexity_news", "Perplexity news ingestion", "perplexity_api_key", "News"),
    ("telegram_monitor", "Telegram signal/news monitor", None, "Other"),
    ("qdrant_embeddings", "Qdrant embeddings (context vector store)", "jina_api_key", "Other"),
]

with st.expander("🔌 Integrations"):
    st.caption(
        "Enable or disable each component independently of whether its API "
        "key is configured. **Changes require a container restart** (no hot-reload yet)."
    )

    ig_settings = get("/v1/settings/integrations")
    ig_values: dict[str, str] = {}
    if ig_settings:
        ig_values = ig_settings.get("values", {}) or {}

    cred_settings = get("/v1/settings/credentials")
    cred_values: dict[str, str] = {}
    if cred_settings:
        cred_values = cred_settings.get("values", {}) or {}

    def _has_key(cred_key: str | None) -> bool:
        if cred_key is None:
            return True
        v = cred_values.get(cred_key, "")
        return bool(v and v != "***")

    groups: dict[str, list[tuple[str, str, str | None]]] = {}
    for key, label, cred_key, group in _INTEGRATIONS_SPEC:
        groups.setdefault(group, []).append((key, label, cred_key))

    pending_updates: dict[str, str] = {}
    for group, items in groups.items():
        st.markdown(f"**{group}**")
        for key, label, cred_key in items:
            flag_key = f"{key}_enabled"
            current = ig_values.get(flag_key, "").strip().lower() in ("true", "1", "yes", "on")
            key_ok = _has_key(cred_key)
            help_text = (
                "No API key required" if cred_key is None
                else (f"API key `{cred_key}` OK" if key_ok else f"Missing API key `{cred_key}` — set it under Runtime Config → Credentials first")
            )
            new_val = st.checkbox(
                f"{label}" + ("" if key_ok else "  ⚠️"),
                value=current,
                key=f"ig_toggle_{flag_key}",
                help=help_text,
                disabled=not key_ok and not current,
            )
            if new_val != current:
                pending_updates[flag_key] = "true" if new_val else "false"

    if pending_updates:
        if st.button(f"Apply {len(pending_updates)} change(s)", key="ig_apply"):
            import httpx as _httpx
            headers = {"X-API-Key": api_key} if api_key else {}
            try:
                _httpx.put(
                    f"{base_url}/v1/settings/integrations",
                    json={"values": pending_updates},
                    headers=headers,
                    timeout=10,
                )
                st.success(f"Updated {len(pending_updates)} flag(s). Restart the app container for changes to take effect.")
                st.cache_data.clear()
                st.rerun()
            except Exception as e:
                st.error(str(e))

    st.caption(
        "⚠️ Components marked with a warning have no API key configured — "
        "their toggle is locked off. Add the key under Runtime Config → Credentials, "
        "then refresh this page to enable the toggle."
    )

# ── Scheduler Symbol Watchlist ──────────────────────────────────────────────

with st.expander("📋 Scheduler Symbols"):
    sched_data = get("/v1/agent/scheduler/symbols")
    if sched_data:
        current_symbols = sched_data.get("symbols", [])
        rl = sched_data.get("rate_limit_estimate", {})
        util_pct = rl.get("utilization_pct", 0)

        # Rate limit budget bar
        if util_pct < 50:
            st.progress(util_pct / 100, text=f"Binance API budget: {util_pct:.0f}%")
        elif util_pct < 80:
            st.warning(f"Binance API budget: {util_pct:.0f}% — consider reducing symbols")
        else:
            st.error(f"Binance API budget: {util_pct:.0f}% — risk of rate limiting!")

        st.caption(
            f"{sched_data.get('count', 0)} symbols | "
            f"Agent ~{rl.get('agent_rpm', 0):.0f} rpm + "
            f"StopLoss ~{rl.get('stoploss_rpm_max', 0):.0f} rpm max = "
            f"~{rl.get('total_rpm_max', 0):.0f} / {rl.get('binance_budget_rpm', 120)} rpm"
        )

        if current_symbols:
            cols = st.columns(min(len(current_symbols), 6))
            for i, sym in enumerate(current_symbols):
                with cols[i % len(cols)]:
                    if st.button(f"✕ {sym}", key=f"rm_sched_{sym}"):
                        new_list = [s for s in current_symbols if s != sym]
                        import httpx as _httpx
                        headers = {"X-API-Key": api_key} if api_key else {}
                        try:
                            _httpx.put(
                                f"{base_url}/v1/agent/scheduler/symbols",
                                json={"symbols": new_list},
                                headers=headers,
                                timeout=10,
                            )
                            st.cache_data.clear()
                            st.rerun()
                        except Exception as e:
                            st.error(_format_http_error("/v1/agent/scheduler/symbols", "PUT", e))

        col_add, col_btn = st.columns([3, 1])
        with col_add:
            new_symbol = st.text_input(
                "Add symbol (e.g. SOL/USDT)",
                key="add_sched_sym",
                value="",
            )
        with col_btn:
            st.write("")
            if st.button("+ Add", key="add_sched_btn") and new_symbol:
                new_list = current_symbols + [new_symbol.strip().upper()]
                import httpx as _httpx
                headers = {"X-API-Key": api_key} if api_key else {}
                try:
                    _httpx.put(
                        f"{base_url}/v1/agent/scheduler/symbols",
                        json={"symbols": new_list},
                        headers=headers,
                        timeout=10,
                    )
                    st.success(f"Added {new_symbol.upper()}")
                    st.cache_data.clear()
                    st.rerun()
                except Exception as e:
                    st.error(_format_http_error("/v1/agent/scheduler/symbols", "PUT", e))

        st.caption(
            "Changes are runtime-only. For permanent changes, update "
            "TRDEX_AGENT_SCHEDULER_SYMBOLS in Coolify and restart."
        )
    else:
        st.info("Scheduler not running or API unreachable.")

# ── Price Feed Selection ───────────────────────────────────────────────────

with st.expander("📡 Price Feeds (aggregation)"):
    feed_data = get("/v1/agent/feeds")
    if feed_data:
        available = feed_data.get("available", [])
        selected = feed_data.get("selected", [])

        st.caption(
            f"{len(selected)}/{len(available)} feeds selected. "
            f"{'Median price from multiple sources.' if len(selected) > 1 else 'Single source (no aggregation).'}"
        )

        # Checkbox per feed
        new_selection = []
        cols = st.columns(min(len(available), 4)) if available else []
        for i, feed_name in enumerate(available):
            with cols[i % len(cols)] if cols else st.container():
                checked = st.checkbox(
                    feed_name,
                    value=feed_name in selected,
                    key=f"feed_{feed_name}",
                )
                if checked:
                    new_selection.append(feed_name)

        if st.button("Apply feed selection", key="apply_feeds"):
            if not new_selection:
                st.error("Select at least one feed.")
            else:
                import httpx as _httpx
                headers = {"X-API-Key": api_key} if api_key else {}
                try:
                    _httpx.put(
                        f"{base_url}/v1/agent/feeds",
                        json={"feeds": new_selection},
                        headers=headers,
                        timeout=10,
                    )
                    st.success(f"Selected: {', '.join(new_selection)}")
                    st.cache_data.clear()
                    st.rerun()
                except Exception as e:
                    st.error(_format_http_error("/v1/agent/feeds", "PUT", e))

        st.caption("Runtime-only. On restart, all feeds are selected by default.")
    else:
        st.info("Feed manager not available.")

# ── Status ────────────────────────────────────────────────────────────────────

with st.expander("System Status"):
    status = get("/v1/status")
    if status:
        st.json(status)

# ── Settings (persistent, DB-backed) ─────────────────────────────────────────

st.header("Settings")
st.caption("Changes take effect immediately and persist across restarts.")

_settings_data = get("/v1/settings")
_all_cfg = _settings_data.get("categories", {}) if _settings_data else {}

with st.expander("API Keys"):
    _creds = _all_cfg.get("credentials", {})
    with st.form("settings_credentials", clear_on_submit=False):
        st.caption("Leave blank to keep current value. Displayed values are masked.")
        _cred_inputs = {}
        for cred_key in [
            "cryptocompare_api_key", "stockdata_api_key", "perplexity_api_key",
            "jina_api_key", "binance_api_key", "binance_api_secret",
            "telegram_api_id", "telegram_api_hash",
        ]:
            current = _creds.get(cred_key, "")
            _cred_inputs[cred_key] = st.text_input(
                cred_key.replace("_", " ").title(),
                value="",
                type="password",
                placeholder=current or "(not set)",
                key=f"cred_{cred_key}",
            )
        if st.form_submit_button("Save API Keys"):
            pairs = {k: v for k, v in _cred_inputs.items() if v}
            if pairs:
                result = put("/v1/settings/credentials", {"values": pairs})
                if result:
                    st.success(f"Updated {len(pairs)} key(s)")
                    st.cache_data.clear()
                    st.rerun()
            else:
                st.warning("No changes — all fields were left blank")

with st.expander("Symbols"):
    _syms = _all_cfg.get("symbols", {})
    with st.form("settings_symbols", clear_on_submit=False):
        sched_syms = st.text_area(
            "Agent Scheduler Symbols (comma-separated)",
            value=_syms.get("agent_scheduler_symbols", ""),
            height=80,
            key="cfg_sched_syms",
        )
        ingest_syms = st.text_area(
            "News Ingestion Symbols (comma-separated)",
            value=_syms.get("ingestion_symbols", ""),
            height=80,
            key="cfg_ingest_syms",
        )
        if st.form_submit_button("Save Symbols"):
            pairs = {}
            if sched_syms.strip():
                pairs["agent_scheduler_symbols"] = sched_syms.strip()
            if ingest_syms.strip():
                pairs["ingestion_symbols"] = ingest_syms.strip()
            if pairs:
                result = put("/v1/settings/symbols", {"values": pairs})
                if result:
                    st.success("Symbols updated — active immediately")
                    st.cache_data.clear()
                    st.rerun()

with st.expander("Risk Thresholds"):
    _thr = _all_cfg.get("thresholds", {})
    with st.form("settings_thresholds", clear_on_submit=False):
        _thr_inputs = {}
        for thr_key, label, default in [
            ("sl_position_pct", "Stop Loss %", "0.05"),
            ("sl_take_profit_pct", "Take Profit %", "0.10"),
            ("sl_trailing_stop_pct", "Trailing Stop %", "0.03"),
            ("sl_daily_drawdown_pct", "Daily Drawdown Limit %", "0.10"),
            ("gate_max_drawdown", "Max Drawdown Limit %", "0.20"),
            ("max_position_pct", "Max Position Size %", "0.02"),
            ("risk_per_trade_pct", "Risk per Trade % (size = risk / stop)", "0.001"),
            ("regime_cv_min", "Regime CV min (from regime_range.py)", ""),
            ("regime_cv_max", "Regime CV max (from regime_range.py)", ""),
            ("regime_data_end", "Regime data end YYYY-MM-DD (from regime_range.py)", ""),
            ("regime_max_age_days", "Regime bounds max age (days, readiness)", "90"),
            ("gate_min_days", "Gate Min Simulation Days", "20"),
        ]:
            _thr_inputs[thr_key] = st.text_input(
                label,
                value=_thr.get(thr_key, default),
                key=f"thr_{thr_key}",
            )
        st.caption(
            "Regime bounds last changed: "
            f"{_thr.get('regime_set_at') or 'unknown'} (stamped automatically)"
        )
        if st.form_submit_button("Save Thresholds"):
            pairs = {k: v for k, v in _thr_inputs.items() if v}
            if pairs:
                result = put("/v1/settings/thresholds", {"values": pairs})
                if result:
                    st.success("Thresholds updated — active immediately")
                    st.cache_data.clear()
                    st.rerun()

with st.expander("Scheduler"):
    _sch = _all_cfg.get("scheduler", {})
    with st.form("settings_scheduler", clear_on_submit=False):
        sch_enabled = st.selectbox(
            "Agent Scheduler Enabled",
            ["true", "false"],
            index=0 if _sch.get("agent_scheduler_enabled", "false").lower() in ("true", "1") else 1,
            key="cfg_sch_enabled",
        )
        sch_interval = st.text_input(
            "Agent Scheduler Interval (seconds)",
            value=_sch.get("agent_scheduler_interval", "300"),
            key="cfg_sch_interval",
        )
        sch_hours = st.text_input(
            "Active Hours (HH:MM-HH:MM UTC, empty = H24)",
            value=_sch.get("agent_scheduler_active_hours", ""),
            key="cfg_sch_hours",
        )
        sch_sl_interval = st.text_input(
            "Stop-Loss Check Interval (seconds)",
            value=_sch.get("sl_check_interval", "30"),
            key="cfg_sl_interval",
        )
        sch_ingest_interval = st.text_input(
            "News Ingestion Interval (seconds)",
            value=_sch.get("ingestion_interval", "300"),
            key="cfg_ingest_interval",
        )
        if st.form_submit_button("Save Scheduler Settings"):
            pairs = {
                "agent_scheduler_enabled": sch_enabled,
                "agent_scheduler_interval": sch_interval,
                "agent_scheduler_active_hours": sch_hours,
                "sl_check_interval": sch_sl_interval,
                "ingestion_interval": sch_ingest_interval,
            }
            result = put("/v1/settings/scheduler", {"values": {k: v for k, v in pairs.items() if v}})
            if result:
                st.success("Scheduler settings updated")
                st.cache_data.clear()
                st.rerun()

with st.expander("Price Feeds"):
    _feeds_cfg = _all_cfg.get("feeds", {})
    current_feeds = _feeds_cfg.get("selected_feeds", "")
    with st.form("settings_feeds", clear_on_submit=False):
        feeds_input = st.text_input(
            "Selected Feeds (comma-separated, empty = ALL)",
            value=current_feeds,
            key="cfg_feeds",
        )
        if st.form_submit_button("Save Feed Selection"):
            result = put("/v1/settings/feeds", {"values": {"selected_feeds": feeds_input}})
            if result:
                st.success("Feed selection updated")
                st.cache_data.clear()
                st.rerun()

# ── Debug Section (collapsible) ──────────────────────────────────────────────

st.divider()
show_debug = st.checkbox("Show debug panels", value=False, key="debug_toggle")

if show_debug:
    st.header("Debug")

    # Balance Ledger History
    with st.expander("Balance Ledger (raw events)"):
        ledger_data = get("/v1/debug/balance-ledger?limit=100")
        if ledger_data and ledger_data.get("entries"):
            import pandas as pd
            df_ledger = pd.DataFrame(ledger_data["entries"])
            df_ledger["amount"] = pd.to_numeric(df_ledger["amount"], errors="coerce")
            df_ledger["balance_after"] = pd.to_numeric(df_ledger["balance_after"], errors="coerce")
            st.dataframe(df_ledger, use_container_width=True)
        else:
            st.info("No balance events recorded yet.")

    # Entity Graph Viewer
    with st.expander("Entity Graph (active facts)"):
        col_st, col_si, col_pr = st.columns(3)
        with col_st:
            eg_subject_type = st.text_input("Subject type", value="", key="eg_st", placeholder="e.g. symbol")
        with col_si:
            eg_subject_id = st.text_input("Subject ID", value="", key="eg_si", placeholder="e.g. BTC/USDT")
        with col_pr:
            eg_predicate = st.text_input("Predicate", value="", key="eg_pr", placeholder="e.g. volatility_regime")

        params = {}
        if eg_subject_type:
            params["subject_type"] = eg_subject_type
        if eg_subject_id:
            params["subject_id"] = eg_subject_id
        if eg_predicate:
            params["predicate"] = eg_predicate

        query_str = "&".join(f"{k}={v}" for k, v in params.items())
        eg_url = f"/v1/debug/entity-graph?{query_str}" if query_str else "/v1/debug/entity-graph"
        eg_data = get(eg_url)
        if eg_data and eg_data.get("facts"):
            import pandas as pd
            df_eg = pd.DataFrame(eg_data["facts"])
            st.dataframe(df_eg, use_container_width=True)
        else:
            st.info("No active facts match the filter.")

# ── Auto-refresh ──────────────────────────────────────────────────────────────

if not manual_refresh:
    time.sleep(refresh_interval)
    st.cache_data.clear()
    st.rerun()
