"""
Analytics — Volume trends, state funnel, per-schema performance, edit rates.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import pandas as pd
import streamlit as st

import cached_api
from components import (
    render_header, state_badge, conf_pill, empty_state,
    callout, section_header, STATE_COLORS,
)

st.set_page_config(page_title="Analytics — IDP", page_icon="📈", layout="wide")

render_header("Analytics")

# ── Controls ───────────────────────────────────────────────────────────────

col_ctrl, _, col_r = st.columns([2, 6, 1])
with col_ctrl:
    days = st.selectbox("Lookback", [7, 14, 30, 60, 90], index=2, label_visibility="collapsed")
with col_r:
    st.write("")
    if st.button("🔄", help="Refresh analytics", key="ana_refresh"):
        cached_api.invalidate_live()
        st.rerun()

st.caption(f"Showing data for the last **{days} days**")

try:
    data = cached_api.get_dashboard_analytics(days=days)
except Exception as e:
    callout(f"Backend unavailable: {e}", kind="warning")
    st.stop()

# ── Overall KPIs ──────────────────────────────────────────────────────────

section_header("Performance Overview")

c1, c2, c3, c4 = st.columns(4)
overall_conf = data.get("overall_avg_confidence")
c1.metric(
    "🎯  Avg Confidence",
    f"{overall_conf:.0%}" if overall_conf else "—",
    help="Average confidence across all AI-extracted fields",
)
human_edit_rate = data.get("human_edit_rate")
c2.metric(
    "✏️  Human Edit Rate",
    f"{human_edit_rate:.1%}" if human_edit_rate is not None else "—",
    help="Fraction of extracted fields manually corrected by reviewers",
)
avg_ms = data.get("avg_processing_ms")
c3.metric(
    "⏱️  Avg Processing",
    f"{avg_ms:,.0f} ms" if avg_ms else "—",
    help="Average time from upload to extraction complete",
)
total_docs = sum(d.get("count", 0) for d in data.get("daily_volume", []))
c4.metric(f"📄  Total Docs ({days}d)", total_docs, help=f"Documents processed in the last {days} days")

if overall_conf and overall_conf < 0.75:
    callout(
        f"Average confidence is <strong>{overall_conf:.0%}</strong> — below 75%. "
        "Consider improving your schema hints or reviewing extraction rules.",
        kind="warning",
    )
elif overall_conf and overall_conf >= 0.90:
    callout(
        f"Excellent! Average confidence is <strong>{overall_conf:.0%}</strong>. "
        "Your schema rules are working well.",
        kind="success",
    )

if human_edit_rate is not None and human_edit_rate > 0.20:
    callout(
        f"Human edit rate is <strong>{human_edit_rate:.1%}</strong> — reviewers are correcting more than 1 in 5 fields. "
        "Apply feedback in Schema Builder to let the AI learn from corrections.",
        kind="tip",
    )

st.markdown("<br>", unsafe_allow_html=True)

# ── Daily Volume ──────────────────────────────────────────────────────────

section_header(f"Daily Volume", f"documents processed per day — last {days} days")
callout(
    "Each bar represents documents received on that date. "
    "A spike may indicate a batch upload or ERP push.",
    kind="info",
)

daily = data.get("daily_volume", [])
# Normalise: API may return a dict {date: count} or a list [{date, count}]
if isinstance(daily, dict):
    daily = [{"date": k, "count": v} for k, v in sorted(daily.items())]
if daily:
    df_daily = pd.DataFrame(daily).set_index("date")
    st.bar_chart(df_daily["count"], use_container_width=True, height=200)
else:
    empty_state("📅", "No volume data", f"No documents were processed in the last {days} days.")

st.markdown("<br>", unsafe_allow_html=True)

# ── State Funnel ──────────────────────────────────────────────────────────

section_header("State Distribution", "where documents end up")
callout(
    "Shows the count of documents in each final state. "
    "A large <strong>FAILED</strong> bar suggests pipeline issues — check the Dashboard for details.",
    kind="info",
)

funnel = data.get("state_funnel", [])
# Normalise: API may return a dict {state: count} or a list [{state, count}]
if isinstance(funnel, dict):
    funnel = [{"state": k, "count": v} for k, v in funnel.items()]
if funnel:
    col_chart, col_table = st.columns([3, 2], gap="large")
    df_funnel = pd.DataFrame(funnel)

    with col_chart:
        st.bar_chart(
            df_funnel.set_index("state")["count"],
            use_container_width=True,
            height=200,
        )
    with col_table:
        total_funnel = df_funnel["count"].sum()
        rows_html = ""
        for _, row in df_funnel.iterrows():
            state = row["state"]
            count = int(row["count"])
            pct = f'{count / total_funnel * 100:.1f}%' if total_funnel else "—"
            badge = state_badge(state)
            rows_html += (
                f'<div style="display:flex;align-items:center;gap:10px;padding:6px 0;'
                f'border-bottom:1px solid #21262d">'
                f'<span style="flex:1">{badge}</span>'
                f'<span style="color:#e6edf3;font-weight:600">{count}</span>'
                f'<span style="color:#8b949e;font-size:.8rem;width:48px;text-align:right">{pct}</span>'
                f'</div>'
            )
        st.markdown(
            f'<div style="background:#161b22;border:1px solid #21262d;border-radius:8px;padding:12px 16px">'
            f'{rows_html}</div>',
            unsafe_allow_html=True,
        )
else:
    empty_state("📊", "No state data", "No documents found for this period.")

st.markdown("<br>", unsafe_allow_html=True)

# ── Per-Schema Performance ────────────────────────────────────────────────

section_header("Per-Schema Performance", "compare extraction quality across schemas")
callout(
    "Human edit rate shows how often reviewers corrected the AI's extractions for each schema. "
    "Lower is better. Use the Feedback loop to improve schemas with high edit rates.",
    kind="tip",
)

by_schema = data.get("by_schema", [])
if by_schema:
    col_tbl, col_chart = st.columns([3, 2], gap="large")

    with col_tbl:
        rows = []
        for s in by_schema:
            conf = s.get("avg_confidence")
            edit_rate = s.get("human_edit_rate")
            rows.append({
                "Schema":          s.get("schema_name") or s.get("schema_id", "")[:12],
                "Documents":       s.get("doc_count", 0),
                "Avg Confidence":  f"{conf:.0%}" if conf else "—",
                "Edit Rate":       f"{edit_rate:.1%}" if edit_rate is not None else "—",
                "Avg Time (ms)":   f"{s.get('avg_processing_ms', 0):,.0f}" if s.get("avg_processing_ms") else "—",
                "Failed":          s.get("failed_count", 0),
            })
        st.dataframe(rows, use_container_width=True, hide_index=True)

    with col_chart:
        if len(by_schema) > 1:
            section_header("Confidence by Schema")
            conf_data = {
                s.get("schema_name") or s.get("schema_id", "")[:12]: s.get("avg_confidence") or 0
                for s in by_schema
                if s.get("avg_confidence") is not None
            }
            if conf_data:
                st.bar_chart(conf_data, use_container_width=True, height=180)
else:
    empty_state("🔧", "No schema data", "No documents with schema matches found for this period.")


