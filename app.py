import streamlit as st
import requests
import time
import datetime
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import statistics

st.set_page_config(
    page_title="OnShape Connection Monitor",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded",
)

ONSHAPE_ENDPOINTS = {
    "Main App":     "https://cad.onshape.com",
    "API":          "https://cad.onshape.com/api/v6/users/sessioninfo",
    "Static CDN":   "https://cad.onshape.com/fonts/roboto/Roboto-Regular.woff2",
}

MAX_HISTORY = 200

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

def latency_colour(ms):
    if ms is None:   return "🔴"
    if ms < 200:     return "🟢"
    if ms < 600:     return "🟡"
    return "🔴"

def quality_label(ms):
    if ms is None:   return "❌ Failed"
    if ms < 200:     return "✅ Excellent"
    if ms < 400:     return "🟡 Good"
    if ms < 800:     return "🟠 Fair"
    return "🔴 Poor"

with st.sidebar:
    st.title("⚙️ Settings")
    interval   = st.slider("Check interval (seconds)", 2, 60, 5)
    timeout    = st.slider("Request timeout (seconds)", 3, 30, 10)
    max_points = st.slider("Max points on graph",       20, MAX_HISTORY, 60)

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
        st.session_state.history   = []
        st.session_state.total_checks = 0
        st.session_state.fail_count   = 0

    st.markdown("---")
    st.markdown("**Status:** " + ("🟢 Running" if st.session_state.running else "🔴 Stopped"))
    st.markdown(f"**Total checks:** {st.session_state.total_checks}")
    uptime = (
        f"{100*(1 - st.session_state.fail_count / max(st.session_state.total_checks,1)):.1f}%"
        if st.session_state.total_checks else "N/A"
    )
    st.markdown(f"**Uptime:** {uptime}")

st.title("📡 OnShape Connection Speed Monitor")
st.caption("Live latency tracking — auto-refreshes every check interval")

metrics_ph  = st.empty()
chart_ph    = st.empty()
stats_ph    = st.empty()
table_ph    = st.empty()

def build_figure(history: list[dict], max_points: int, selected_eps: list[str]):
    df = pd.DataFrame(history).tail(max_points)
    if df.empty:
        return go.Figure()

    df = df[df["endpoint"].isin(selected_eps)]

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

    fig.add_hrect(y0=0, y1=200,   fillcolor="green",  opacity=0.05, row=1, col=1, line_width=0)
    fig.add_hrect(y0=200, y1=600, fillcolor="yellow", opacity=0.05, row=1, col=1, line_width=0)
    fig.add_hrect(y0=600, y1=3000,fillcolor="red",    opacity=0.05, row=1, col=1, line_width=0)

    fig.update_layout(
        template="plotly_dark",
        height=500,
        legend=dict(orientation="h", y=1.05),
        margin=dict(l=40, r=20, t=60, b=20),
        hovermode="x unified",
    )
    fig.update_yaxes(title_text="ms",      row=1, col=1, rangemode="tozero")
    fig.update_yaxes(title_text="OK",      row=2, col=1, range=[0, 1.2],
                     tickvals=[0, 1], ticktext=["Fail", "OK"])
    fig.update_xaxes(title_text="Time",    row=2, col=1)

    return fig

def render_metrics(history, selected_eps):
    if not history:
        metrics_ph.info("No data yet — press ▶ Start")
        return

    df = pd.DataFrame(history).tail(60)
    cols = metrics_ph.columns(len(selected_eps))

    for i, ep in enumerate(selected_eps):
        sub = df[(df["endpoint"] == ep) & df["success"]]
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
                value=f"{last:.0f} ms" if last else "N/A",
                delta=f"avg {avg:.0f} ms | p95 {p95:.0f} ms" if avg else "no data",
            )
            st.caption(quality_label(last))

def render_stats(history, selected_eps):
    if not history:
        return
    df = pd.DataFrame(history)
    rows = []
    for ep in selected_eps:
        sub = df[df["endpoint"] == ep]
        ok  = sub[sub["success"]]
        latencies = ok["latency_ms"].dropna().tolist()
        rows.append({
            "Endpoint":   ep,
            "Checks":     len(sub),
            "Failures":   int(sub["success"].eq(False).sum()),
            "Uptime %":   f"{100*len(ok)/max(len(sub),1):.1f}",
            "Min ms":     f"{min(latencies):.0f}"  if latencies else "–",
            "Avg ms":     f"{statistics.mean(latencies):.0f}" if latencies else "–",
            "Max ms":     f"{max(latencies):.0f}"  if latencies else "–",
            "p95 ms":     f"{sorted(latencies)[int(len(latencies)*0.95)]:.0f}" if latencies else "–",
        })
    stats_ph.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

def render_table(history):
    with table_ph.expander("📋 Raw data (last 50 rows)"):
        df = pd.DataFrame(history).tail(50).sort_values("timestamp", ascending=False)
        df["timestamp"] = df["timestamp"].dt.strftime("%H:%M:%S")
        st.dataframe(df, use_container_width=True, hide_index=True)

active_endpoints = {k: v for k, v in ONSHAPE_ENDPOINTS.items() if k in selected_eps}

if st.session_state.running:
    results = run_checks(active_endpoints, timeout)
    st.session_state.history.extend(results)
    st.session_state.total_checks += len(results)
    st.session_state.fail_count   += sum(1 for r in results if not r["success"])

    if len(st.session_state.history) > MAX_HISTORY * len(ONSHAPE_ENDPOINTS):
        st.session_state.history = st.session_state.history[-(MAX_HISTORY * len(ONSHAPE_ENDPOINTS)):]

render_metrics(st.session_state.history, selected_eps)
chart_ph.plotly_chart(
    build_figure(st.session_state.history, max_points, selected_eps),
    use_container_width=True,
)
render_stats(st.session_state.history, selected_eps)
render_table(st.session_state.history)

if st.session_state.running:
    time.sleep(interval)
    st.rerun()
