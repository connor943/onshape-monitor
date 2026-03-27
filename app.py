import streamlit as st
import requests
import time
import datetime
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import statistics

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="OnShape Connection Monitor",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Constants ─────────────────────────────────────────────────────────────────
ONSHAPE_ENDPOINTS = {
    "Main App":     "https://cad.onshape.com",
    "API":          "https://cad.onshape.com/api/v6/users/sessioninfo",
    "Static CDN":   "https://cad.onshape.com/favicon.ico",
}

MAX_HISTORY = 200

# ── Session state bootstrap ───────────────────────────────────────────────────
def init_state():
    defaults = {
        "history":      [],
        "running":      False,
        "total_checks": 0,
        "fail_count":   0,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_state()

# ── Measurement logic ─────────────────────────────────────────────────────────
def measure_endpoint(name: str, url: str, timeout: int = 10) -> dict:
    ts = datetime.datetime.now()
    try:
        t0 = time.perf_counter()
        resp = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": "OnShape-SpeedMonitor/1.0"},
            allow_redirects=True,
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000
        return {
            "timestamp":   ts,
            "endpoint":    name,
            "latency_ms":  round(elapsed_ms, 1),
            "status_code": resp.status_code,
            "success":     resp.status_code < 400,
            "error":       None,
        }
    except requests.exceptions.Timeout:
        return {
            "timestamp":   ts,
            "endpoint":    name,
            "latency_ms":  None,
            "status_code": None,
            "success":     False,
            "error":       "Timeout",
        }
    except requests.exceptions.ConnectionError:
        return {
            "timestamp":   ts,
            "endpoint":    name,
            "latency_ms":  None,
            "status_code": None,
            "success":     False,
            "error":       "Connection Error",
        }
    except Exception as e:
        return {
            "timestamp":   ts,
            "endpoint":    name,
            "latency_ms":  None,
            "status_code": None,
            "success":     False,
            "error":       str(e),
        }


def run_checks(endpoints: dict, timeout: int) -> list:
    return [measure_endpoint(n, u, timeout) for n, u in endpoints.items()]


# ── Colour helpers ────────────────────────────────────────────────────────────
def latency_colour(ms):
    if ms is None:  return "🔴"
    if ms < 200:    return "🟢"
    if ms < 600:    return "🟡"
    return "🔴"

def quality_label(ms):
    if ms is None:  return "❌ Failed"
    if ms < 200:    return "✅ Excellent"
    if ms < 400:    return "🟡 Good"
    if ms < 800:    return "🟠 Fair"
    return "🔴 Poor"


# ── Sidebar controls ──────────────────────────────────────────────────────────
with st.sidebar:
    st.title("⚙️ Settings")
    interval   = st.slider("Check interval (seconds)", 2, 60, 5)
    timeout    = st.slider("Request timeout (seconds)", 3, 30, 10)
    max_points = st.slider("Max points on graph", 20, MAX_HISTORY, 60)

    selected_eps = st.multiselect(
        "Endpoints to monitor",
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

    if st.button("🗑 Clear Data", use_container_width=True):
        st.session_state.history      = []
        st.session_state.total_checks = 0
        st.session_state.fail_count   = 0

    st.markdown("---")
    st.markdown("**Status:** " + ("🟢 Running" if st.session_state.running else "🔴 Stopped"))
    st.markdown(f"**Total checks:** {st.session_state.total_checks}")
    uptime = (
        f"{100*(1 - st.session_state.fail_count / max(st.session_state.total_checks, 1)):.1f}%"
        if st.session_state.total_checks else "N/A"
    )
    st.markdown(f"**Uptime:** {uptime}")


# ── Main layout ───────────────────────────────────────────────────────────────
st.title("📡 OnShape Connection Speed Monitor")
st.caption("Live latency tracking — auto-refreshes every check interval")

metrics_ph = st.empty()
chart_ph   = st.empty()
stats_ph   = st.empty()
table_ph   = st.empty()


# ── Chart builder ─────────────────────────────────────────────────────────────
def build_figure(history: list, max_points: int, selected_eps: list):
    if not history:
        return go.Figure()

    df = pd.DataFrame(history)

    # Guard: make sure expected columns exist
    required = {"timestamp", "endpoint", "latency_ms", "success"}
    if not required.issubset(df.columns):
        return go.Figure()

    df = df[df["endpoint"].isin(selected_eps)].tail(max_points * len(selected_eps))

    colours = {
        "Main App":   "#4A90D9",
        "API":        "#7ED321",
        "Static CDN": "#F5A623",
    }

    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        row_heights=[0.7, 0.3],
        subplot_titles=("Latency over time (ms)", "Success / Failure"),
        vertical_spacing=0.08,
    )

    for ep in selected_eps:
        sub = df[df["endpoint"] == ep]
        if sub.empty:
            continue
        colour = colours.get(ep, "#AAAAAA")

        fig.add_trace(
            go.Scatter(
                x=sub["timestamp"],
                y=sub["latency_ms"],
                name=ep,
                mode="lines+markers",
                line=dict(width=2, color=colour),
                marker=dict(size=5),
                connectgaps=False,
                hovertemplate=(
                    "<b>%{fullData.name}</b><br>"
                    "Time: %{x|%H:%M:%S}<br>"
                    "Latency: %{y} ms<extra></extra>"
                ),
            ),
            row=1, col=1,
        )

        fig.add_trace(
            go.Bar(
                x=sub["timestamp"],
                y=sub["success"].astype(int),
                name=ep + " ok",
                marker_color=colour,
                opacity=0.6,
                showlegend=False,
                hovertemplate="<b>%{fullData.name}</b><br>%{x|%H:%M:%S}<extra></extra>",
            ),
            row=2, col=1,
        )

    fig.add_hrect(y0=0,   y1=200,  fillcolor="green",  opacity=0.05, row=1, col=1, line_width=0)
    fig.add_hrect(y0=200, y1=600,  fillcolor="yellow", opacity=0.05, row=1, col=1, line_width=0)
    fig.add_hrect(y0=600, y1=3000, fillcolor="red",    opacity=0.05, row=1, col=1, line_width=0)

    fig.update_layout(
        template="plotly_dark",
        height=500,
        legend=dict(orientation="h", y=1.05),
        margin=dict(l=40, r=20, t=60, b=20),
        hovermode="x unified",
    )
    fig.update_yaxes(title_text="ms", row=1, col=1, rangemode="tozero")
    fig.update_yaxes(title_text="OK", row=2, col=1, range=[0, 1.2],
                     tickvals=[0, 1], ticktext=["Fail", "OK"])
    fig.update_xaxes(title_text="Time", row=2, col=1)

    return fig


# ── Metric cards ──────────────────────────────────────────────────────────────
def render_metrics(history, selected_eps):
    if not history:
        metrics_ph.info("No data yet — press ▶ Start in the sidebar")
        return

    df = pd.DataFrame(history)
    if "endpoint" not in df.columns:
        return

    df_recent = df.tail(60 * len(selected_eps))
    cols = metrics_ph.columns(max(len(selected_eps), 1))

    for i, ep in enumerate(selected_eps):
        sub = df_recent[(df_recent["endpoint"] == ep) & (df_recent["success"] == True)]
        latencies = sub["latency_ms"].dropna().tolist()

        if latencies:
            avg  = statistics.mean(latencies)
            p95  = sorted(latencies)[int(len(latencies) * 0.95)]
            last = latencies[-1]
        else:
            avg = p95 = last = None

        with cols[i]:
            st.metric(
                label=f"{latency_colour(last)} {ep}",
                value=f"{last:.0f} ms" if last is not None else "N/A",
                delta=f"avg {avg:.0f} ms | p95 {p95:.0f} ms" if avg is not None else "no data",
            )
            st.caption(quality_label(last))


# ── Stats table ───────────────────────────────────────────────────────────────
def render_stats(history, selected_eps):
    if not history:
        return

    df = pd.DataFrame(history)
    if "endpoint" not in df.columns:
        return

    rows = []
    for ep in selected_eps:
        sub = df[df["endpoint"] == ep]
        ok  = sub[sub["success"] == True]
        latencies = ok["latency_ms"].dropna().tolist()
        rows.append({
            "Endpoint":  ep,
            "Checks":    len(sub),
            "Failures":  int((sub["success"] == False).sum()),
            "Uptime %":  f"{100 * len(ok) / max(len(sub), 1):.1f}",
            "Min ms":    f"{min(latencies):.0f}"  if latencies else "–",
            "Avg ms":    f"{statistics.mean(latencies):.0f}" if latencies else "–",
            "Max ms":    f"{max(latencies):.0f}"  if latencies else "–",
            "p95 ms":    f"{sorted(latencies)[int(len(latencies) * 0.95)]:.0f}" if latencies else "–",
        })

    stats_ph.dataframe(
        pd.DataFrame(rows),
        use_container_width=True,
        hide_index=True,
    )


# ── Raw data table ────────────────────────────────────────────────────────────
def render_table(history):
    if not history:
        return

    df = pd.DataFrame(history)

    # Safety check — only sort if column exists
    if "timestamp" not in df.columns:
        with table_ph.expander("📋 Raw data (last 50 rows)"):
            st.dataframe(df.tail(50), use_container_width=True, hide_index=True)
        return

    with table_ph.expander("📋 Raw data (last 50 rows)"):
        df_display = (
            df.tail(50)
            .sort_values("timestamp", ascending=False)
            .copy()
        )
        df_display["timestamp"] = df_display["timestamp"].dt.strftime("%H:%M:%S")
        st.dataframe(df_display, use_container_width=True, hide_index=True)


# ── Main loop ─────────────────────────────────────────────────────────────────
active_endpoints = {k: v for k, v in ONSHAPE_ENDPOINTS.items() if k in selected_eps}

if st.session_state.running:
    results = run_checks(active_endpoints, timeout)
    st.session_state.history.extend(results)
    st.session_state.total_checks += len(results)
    st.session_state.fail_count   += sum(1 for r in results if not r["success"])

    # Trim history
    max_stored = MAX_HISTORY * max(len(ONSHAPE_ENDPOINTS), 1)
    if len(st.session_state.history) > max_stored:
        st.session_state.history = st.session_state.history[-max_stored:]

# Render (works whether running or stopped)
render_metrics(st.session_state.history, selected_eps)
chart_ph.plotly_chart(
    build_figure(st.session_state.history, max_points, selected_eps),
    use_container_width=True,
)
render_stats(st.session_state.history, selected_eps)
render_table(st.session_state.history)

# Auto-rerun while running
if st.session_state.running:
    time.sleep(interval)
    st.rerun()
