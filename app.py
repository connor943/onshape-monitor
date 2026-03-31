import streamlit as st
import requests
import time
import datetime
import os
import threading
import statistics

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

import keepalive

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="OnShape Connection Monitor",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Constants ─────────────────────────────────────────────────────────────────
ONSHAPE_ENDPOINTS = {
    "Main App":   "https://cad.onshape.com",
    "API":        "https://cad.onshape.com/api/v6/users/sessioninfo",
    "Static CDN": "https://cad.onshape.com/fonts/roboto/Roboto-Regular.woff2",
}

DATA_DIR    = "data"
MAX_DISPLAY = 200   # max points shown on graph at once

APP_URL_ENV = "STREAMLIT_APP_URL"  # set this in Streamlit Cloud secrets (optional)

# ── Data directory ────────────────────────────────────────────────────────────
os.makedirs(DATA_DIR, exist_ok=True)


def today_csv() -> str:
    return os.path.join(DATA_DIR, f"{datetime.date.today().isoformat()}.csv")


CSV_COLUMNS = ["timestamp", "endpoint", "latency_ms", "status_code", "success", "error"]


# ── CSV helpers ───────────────────────────────────────────────────────────────
def append_to_csv(records: list[dict]):
    """Append a list of result dicts to today's CSV, creating it if needed."""
    df = pd.DataFrame(records, columns=CSV_COLUMNS)
    path = today_csv()
    write_header = not os.path.exists(path)
    df.to_csv(path, mode="a", header=write_header, index=False)


def load_csv(path: str) -> pd.DataFrame:
    """Load a CSV log file and parse timestamps."""
    if not os.path.exists(path):
        return pd.DataFrame(columns=CSV_COLUMNS)
    df = pd.read_csv(path, parse_dates=["timestamp"])
    df["success"] = df["success"].astype(bool)
    df["latency_ms"] = pd.to_numeric(df["latency_ms"], errors="coerce")
    return df


def load_today() -> list[dict]:
    """Load today's CSV into a list of dicts for session state."""
    df = load_csv(today_csv())
    if df.empty:
        return []
    return df.to_dict("records")


def available_dates() -> list[str]:
    """Return sorted list of dates we have log files for."""
    files = [f for f in os.listdir(DATA_DIR) if f.endswith(".csv")]
    dates = sorted([f.replace(".csv", "") for f in files], reverse=True)
    return dates


# ── Session state bootstrap ───────────────────────────────────────────────────
def init_state():
    if "history" not in st.session_state:
        # Restore today's data on first load
        st.session_state.history = load_today()

    defaults = {
        "running":      False,
        "total_checks": len(st.session_state.get("history", [])),
        "fail_count":   sum(
            1 for r in st.session_state.get("history", [])
            if not r.get("success", True)
        ),
        "keepalive_started": False,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


init_state()


# ── Keepalive bootstrap ───────────────────────────────────────────────────────
if not st.session_state.keepalive_started:
    app_url = os.environ.get(APP_URL_ENV, "")
    if app_url:
        keepalive.start(app_url)
        st.session_state.keepalive_started = True


# ── Measurement ───────────────────────────────────────────────────────────────
def measure_endpoint(name: str, url: str, timeout: int = 10) -> dict:
    ts = datetime.datetime.now()
    try:
        t0   = time.perf_counter()
        resp = requests.get(
            url, timeout=timeout,
            headers={"User-Agent": "OnShape-SpeedMonitor/1.0"},
            allow_redirects=True,
        )
        ms = (time.perf_counter() - t0) * 1000
        return dict(
            timestamp=ts, endpoint=name,
            latency_ms=round(ms, 1), status_code=resp.status_code,
            success=resp.status_code < 400, error=None,
        )
    except requests.exceptions.Timeout:
        return dict(timestamp=ts, endpoint=name, latency_ms=None,
                    status_code=None, success=False, error="Timeout")
    except requests.exceptions.ConnectionError:
        return dict(timestamp=ts, endpoint=name, latency_ms=None,
                    status_code=None, success=False, error="Connection Error")
    except Exception as e:
        return dict(timestamp=ts, endpoint=name, latency_ms=None,
                    status_code=None, success=False, error=str(e))


def run_checks(endpoints: dict, timeout: int) -> list[dict]:
    return [measure_endpoint(n, u, timeout) for n, u in endpoints.items()]


# ── Colour helpers ────────────────────────────────────────────────────────────
def latency_icon(ms):
    if ms is None: return "🔴"
    if ms < 200:   return "🟢"
    if ms < 600:   return "🟡"
    return "🔴"


def quality_label(ms):
    if ms is None: return "❌ Failed"
    if ms < 200:   return "✅ Excellent"
    if ms < 400:   return "🟡 Good"
    if ms < 800:   return "🟠 Fair"
    return "🔴 Poor"


# ── Chart builder ─────────────────────────────────────────────────────────────
COLOURS = {
    "Main App":   "#4A90D9",
    "API":        "#7ED321",
    "Static CDN": "#F5A623",
}


def build_figure(df: pd.DataFrame, selected_eps: list[str]) -> go.Figure:
    if df.empty:
        fig = go.Figure()
        fig.update_layout(
            template="plotly_dark", height=480,
            annotations=[dict(text="No data — press ▶ Start",
                              showarrow=False, font=dict(size=18))],
        )
        return fig

    df = df[df["endpoint"].isin(selected_eps)]

    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        row_heights=[0.72, 0.28],
        subplot_titles=("Latency (ms)", "Pass / Fail"),
        vertical_spacing=0.08,
    )

    for ep in selected_eps:
        sub    = df[df["endpoint"] == ep]
        colour = COLOURS.get(ep, "#AAAAAA")

        fig.add_trace(go.Scatter(
            x=sub["timestamp"], y=sub["latency_ms"],
            name=ep, mode="lines+markers",
            line=dict(width=2, color=colour),
            marker=dict(size=5), connectgaps=False,
            hovertemplate=(
                "<b>%{fullData.name}</b><br>"
                "%{x|%H:%M:%S} → %{y:.0f} ms<extra></extra>"
            ),
        ), row=1, col=1)

        fig.add_trace(go.Bar(
            x=sub["timestamp"],
            y=sub["success"].astype(int),
            name=ep + " ok",
            marker_color=colour,
            opacity=0.55,
            showlegend=False,
            hovertemplate="%{x|%H:%M:%S}<extra></extra>",
        ), row=2, col=1)

    # Quality bands
    fig.add_hrect(y0=0,   y1=200,  fillcolor="green",  opacity=0.05, row=1, col=1, line_width=0)
    fig.add_hrect(y0=200, y1=600,  fillcolor="yellow", opacity=0.05, row=1, col=1, line_width=0)
    fig.add_hrect(y0=600, y1=5000, fillcolor="red",    opacity=0.05, row=1, col=1, line_width=0)

    fig.update_layout(
        template="plotly_dark", height=500,
        legend=dict(orientation="h", y=1.06),
        margin=dict(l=50, r=20, t=60, b=20),
        hovermode="x unified",
    )
    fig.update_yaxes(title_text="ms",  rangemode="tozero", row=1, col=1)
    fig.update_yaxes(title_text="",    range=[0, 1.3],
                     tickvals=[0, 1], ticktext=["✗", "✓"], row=2, col=1)
    fig.update_xaxes(title_text="Time", row=2, col=1)
    return fig


# ── Stats table ───────────────────────────────────────────────────────────────
def stats_df(df: pd.DataFrame, selected_eps: list[str]) -> pd.DataFrame:
    rows = []
    for ep in selected_eps:
        sub = df[df["endpoint"] == ep]
        ok  = sub[sub["success"]]
        lat = ok["latency_ms"].dropna().tolist()
        rows.append({
            "Endpoint": ep,
            "Checks":   len(sub),
            "Failures": int((~sub["success"]).sum()),
            "Uptime %": f"{100 * len(ok) / max(len(sub), 1):.1f}",
            "Min ms":   f"{min(lat):.0f}"  if lat else "–",
            "Avg ms":   f"{statistics.mean(lat):.0f}" if lat else "–",
            "p95 ms":   f"{sorted(lat)[int(len(lat) * 0.95)]:.0f}" if lat else "–",
            "Max ms":   f"{max(lat):.0f}"  if lat else "–",
        })
    return pd.DataFrame(rows)


# ════════════════════════════════════════════════════════════════════════════
#  SIDEBAR
# ════════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.title("⚙️ Settings")

    interval   = st.slider("Check interval (s)",  2, 60, 5)
    timeout    = st.slider("Request timeout (s)", 3, 30, 10)
    max_points = st.slider("Graph window (pts)",  20, MAX_DISPLAY, 60)

    selected_eps = st.multiselect(
        "Endpoints",
        options=list(ONSHAPE_ENDPOINTS.keys()),
        default=list(ONSHAPE_ENDPOINTS.keys()),
    )

    st.markdown("---")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("▶ Start", use_container_width=True):
            st.session_state.running = True
    with col2:
        if st.button("⏹ Stop", use_container_width=True):
            st.session_state.running = False

    if st.button("🔄 Reload today's data", use_container_width=True):
        st.session_state.history = load_today()

    if st.button("🗑 Clear display", use_container_width=True):
        # Clears in-memory display only — CSV files are NOT deleted
        st.session_state.history      = []
        st.session_state.total_checks = 0
        st.session_state.fail_count   = 0

    st.markdown("---")
    st.markdown("**Status:** " + ("🟢 Running" if st.session_state.running else "🔴 Stopped"))

    total = st.session_state.total_checks
    fails = st.session_state.fail_count
    uptime = f"{100 * (1 - fails / max(total, 1)):.1f}%" if total else "N/A"
    st.markdown(f"**Session checks:** {total}")
    st.markdown(f"**Session uptime:**  {uptime}")
    st.markdown(f"**CSV rows today:**  {len(load_today())}")

    st.markdown("---")

    # ── Historical log browser ────────────────────────────────────────────
    st.subheader("📂 Historical Logs")
    dates = available_dates()

    if dates:
        selected_date = st.selectbox("View date", dates)
        hist_df = load_csv(os.path.join(DATA_DIR, f"{selected_date}.csv"))

        if not hist_df.empty:
            csv_bytes = hist_df.to_csv(index=False).encode()
            st.download_button(
                label=f"⬇ Download {selected_date}.csv",
                data=csv_bytes,
                file_name=f"onshape-monitor-{selected_date}.csv",
                mime="text/csv",
                use_container_width=True,
            )
            st.caption(f"{len(hist_df):,} rows · "
                       f"{hist_df['success'].mean()*100:.1f}% uptime")
        else:
            st.caption("Empty file.")
    else:
        st.caption("No logs yet.")

    # ── Keepalive status ──────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("💓 Keepalive")
    app_url_input = st.text_input(
        "App URL (paste your Streamlit URL)",
        value=os.environ.get(APP_URL_ENV, ""),
        placeholder="https://your-app.streamlit.app",
    )
    if st.button("Activate keepalive", use_container_width=True):
        if app_url_input:
            keepalive.start(app_url_input)
            st.session_state.keepalive_started = True
            st.success("Keepalive running ✅")
        else:
            st.warning("Paste your app URL first.")
    if st.session_state.keepalive_started:
        st.caption("💓 Active — pinging every 4 min")
    else:
        st.caption("⚪ Not started")


# ════════════════════════════════════════════════════════════════════════════
#  MAIN AREA
# ════════════════════════════════════════════════════════════════════════════
st.title("📡 OnShape Connection Monitor")
st.caption(
    f"Logging to `{today_csv()}` · "
    f"History reloaded on startup · "
    f"Auto-refreshes every {interval}s"
)

metrics_ph = st.empty()
chart_ph   = st.empty()
stats_ph   = st.empty()
table_ph   = st.empty()


# ── Render helpers ────────────────────────────────────────────────────────────
def render_metrics(df: pd.DataFrame, selected_eps: list[str]):
    if df.empty:
        metrics_ph.info("No data yet — press ▶ Start in the sidebar")
        return

    cols = metrics_ph.columns(len(selected_eps))
    for i, ep in enumerate(selected_eps):
        sub = df[(df["endpoint"] == ep) & df["success"]]
        lat = sub["latency_ms"].dropna().tolist()

        last = lat[-1]  if lat else None
        avg  = statistics.mean(lat) if lat else None
        p95  = sorted(lat)[int(len(lat) * 0.95)] if lat else None

        with cols[i]:
            st.metric(
                label=f"{latency_icon(last)} {ep}",
                value=f"{last:.0f} ms" if last is not None else "N/A",
                delta=f"avg {avg:.0f} | p95 {p95:.0f} ms" if avg else "no data",
            )
            st.caption(quality_label(last))


def render_chart(df: pd.DataFrame, max_points: int, selected_eps: list[str]):
    display_df = df.tail(max_points * len(selected_eps))
    chart_ph.plotly_chart(
        build_figure(display_df, selected_eps),
        use_container_width=True,
    )


def render_stats_table(df: pd.DataFrame, selected_eps: list[str]):
    if df.empty:
        return
    stats_ph.dataframe(
        stats_df(df, selected_eps),
        use_container_width=True,
        hide_index=True,
    )


def render_raw_table(df: pd.DataFrame):
    with table_ph.expander("📋 Raw data (last 100 rows)"):
        recent = df.tail(100).sort_values("timestamp", ascending=False).copy()
        recent["timestamp"] = recent["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")
        st.dataframe(recent, use_container_width=True, hide_index=True)


# ── Historical day view (in main area) ───────────────────────────────────────
dates = available_dates()
if len(dates) > 1:
    with st.expander("📅 View a historical day"):
        view_date = st.selectbox(
            "Pick a date", dates, key="main_date_picker"
        )
        hist_df = load_csv(os.path.join(DATA_DIR, f"{view_date}.csv"))
        if not hist_df.empty:
            st.plotly_chart(
                build_figure(hist_df, selected_eps),
                use_container_width=True,
            )
            st.dataframe(
                stats_df(hist_df, selected_eps),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("No data for this date.")

st.markdown("---")


# ════════════════════════════════════════════════════════════════════════════
#  MAIN LOOP
# ════════════════════════════════════════════════════════════════════════════
active_eps = {k: v for k, v in ONSHAPE_ENDPOINTS.items() if k in selected_eps}

if st.session_state.running:
    results = run_checks(active_eps, timeout)

    # ── Persist to CSV ────────────────────────────────────────────────────
    append_to_csv(results)

    # ── Update in-memory state ────────────────────────────────────────────
    st.session_state.history.extend(results)
    st.session_state.total_checks += len(results)
    st.session_state.fail_count   += sum(1 for r in results if not r["success"])

    # Keep display window manageable (CSV retains everything)
    trim_to = MAX_DISPLAY * len(ONSHAPE_ENDPOINTS) * 2
    if len(st.session_state.history) > trim_to:
        st.session_state.history = st.session_state.history[-trim_to:]

# Build display dataframe from session state
display_df = pd.DataFrame(st.session_state.history) if st.session_state.history else pd.DataFrame()
if not display_df.empty:
    display_df["timestamp"] = pd.to_datetime(display_df["timestamp"])
    display_df["latency_ms"] = pd.to_numeric(display_df["latency_ms"], errors="coerce")
    display_df["success"]    = display_df["success"].astype(bool)

render_metrics(display_df, selected_eps)
render_chart(display_df, max_points, selected_eps)
render_stats_table(display_df, selected_eps)
render_raw_table(display_df)

# Auto-rerun
if st.session_state.running:
    time.sleep(interval)
    st.rerun()
