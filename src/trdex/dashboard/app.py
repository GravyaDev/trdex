"""trdex Streamlit dashboard MVP.

Run with:
    streamlit run src/trdex/dashboard/app.py
"""

from __future__ import annotations

import time

import httpx
import plotly.express as px
import streamlit as st

st.set_page_config(page_title="trdex", page_icon="📈", layout="wide")

# ── Sidebar config ──────────────────────────────────────────────────────────

with st.sidebar:
    st.title("⚙️ Config")
    base_url = st.text_input("API URL", value="http://localhost:8000")
    api_key = st.text_input("API Key", value="", type="password")
    refresh_interval = st.selectbox("Auto-refresh", [5, 15, 30, 60], index=1)
    manual_refresh = st.button("🔄 Refresh now")

_headers = {"X-API-Key": api_key} if api_key else {}


# ── Data fetchers (cached) ──────────────────────────────────────────────────

@st.cache_data(ttl=30)
def fetch(path: str, base: str, key: str) -> dict | None:
    headers = {"X-API-Key": key} if key else {}
    try:
        r = httpx.get(f"{base}{path}", headers=headers, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        st.error(f"API error ({path}): {e}")
        return None


def get(path: str) -> dict | None:
    return fetch(path, base_url, api_key)


def post(path: str, *, params: dict | None = None, timeout: int = 60) -> dict | None:
    """POST to the configured API base URL with the current API key."""
    headers = {"X-API-Key": api_key} if api_key else {}
    try:
        r = httpx.post(f"{base_url}{path}", params=params, headers=headers, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        st.error(f"API error (POST {path}): {e}")
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
    df = pd.DataFrame(positions_data["positions"])
    for col in ["entry_price", "current_price", "amount", "unrealized_pnl", "unrealized_pnl_pct"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df["unrealized_pnl_pct"] = df["unrealized_pnl_pct"].map(lambda x: f"{x:.2%}")
    st.dataframe(df, use_container_width=True)
else:
    st.info("No open positions.")

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

# ── Signal tracker ────────────────────────────────────────────────────────────

st.header("Telegram Signal Tracker")
signals_data = get("/v1/signals")
if signals_data and signals_data.get("report"):
    import pandas as pd
    df_sig = pd.DataFrame(signals_data["report"])
    if not df_sig.empty:
        df_sig = df_sig.sort_values("roi_pct", ascending=False)
        st.dataframe(df_sig, use_container_width=True)
    else:
        st.info("No signals tracked yet.")
else:
    st.info("No signals tracked yet.")

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
            signal_color = {"BUY": "🟢", "SELL": "🔴", "HOLD": "🟡"}.get(result.get("signal", ""), "⚪")
            st.success(f"{signal_color} Signal: **{result.get('signal')}** | Confidence: {result.get('confidence', 0):.1%} | Order: {result.get('order_status')}")
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
        df_agent["risk_approved"] = df_agent["risk_approved"].map(lambda x: "✅" if x else "❌")
        signal_icons = {"BUY": "🟢 BUY", "SELL": "🔴 SELL", "HOLD": "🟡 HOLD"}
        df_agent["signal"] = df_agent["signal"].map(lambda s: signal_icons.get(s, s))
        st.dataframe(
            df_agent[["symbol", "signal", "confidence", "risk_approved", "order_status", "ran_at"]],
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

    with st.expander("Stop-Loss Thresholds"):
        thresholds = risk_status.get("thresholds", {})
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Position SL", f"{thresholds.get('position_sl_pct', 0):.1%}")
        c2.metric("Position TP", f"{thresholds.get('position_tp_pct', 0):.1%}")
        c3.metric("Daily DD limit", f"{thresholds.get('daily_drawdown_pct', 0):.1%}")
        c4.metric("Max DD limit", f"{thresholds.get('max_drawdown_pct', 0):.1%}")

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

# ── Context / Ingestion ───────────────────────────────────────────────────────

with st.expander("📰 News Ingestion Status"):
    ctx_status = get("/v1/context/status")
    if ctx_status:
        c1, c2, c3 = st.columns(3)
        c1.metric("Sources", len(ctx_status.get("sources", [])))
        c2.metric("Symbols", len(ctx_status.get("symbols", [])))
        c3.metric("Running", "✅" if ctx_status.get("running") else "❌")
        st.caption(f"Last run: {ctx_status.get('last_run', 'never')}")
        st.caption(f"Sources: {', '.join(ctx_status.get('sources', [])) or 'none'}")
        if st.button("🔄 Ingest Now", key="ingest_now"):
            data = post("/v1/context/run", timeout=120)
            if data is not None:
                st.success(f"Ingested {data.get('docs_ingested', 0)} documents.")

# ── Status ────────────────────────────────────────────────────────────────────

with st.expander("System Status"):
    status = get("/v1/status")
    if status:
        st.json(status)

# ── Auto-refresh ──────────────────────────────────────────────────────────────

if not manual_refresh:
    time.sleep(refresh_interval)
    st.cache_data.clear()
    st.rerun()
