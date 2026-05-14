"""
Dashboard — Live queue, quick stats, and searchable document history.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import streamlit as st

import cached_api
from components import (
    render_header, state_badge, conf_pill, empty_state,
    callout, section_header, queue_row,
    STATE_COLORS, STATE_ICONS,
)

st.set_page_config(page_title="Dashboard — IDP", page_icon="📊", layout="wide")

render_header("Dashboard")

# ── Stats row ─────────────────────────────────────────────────────────────

try:
    stats = cached_api.get_dashboard_stats()
except Exception as e:
    callout(f"Backend unavailable: {e}", kind="warning")
    st.stop()

col_s1, col_s2, col_s3, col_s4, col_s5, col_s6, col_r = st.columns([2, 2, 2, 2, 2, 2, 1])
col_s1.metric("📨  Today",           stats["documents_today"],  help="Documents received today")
col_s2.metric("🔍  Pending Review",  stats["pending_review"],   help="Awaiting human review")
col_s3.metric("✅  Verified",        stats["verified_today"],   help="Verified or downloaded today")
col_s4.metric("❌  Failed",          stats["failed_today"],     help="Failed today")
col_s5.metric("⚡  Processing",      stats["processing_now"],   help="In pipeline right now")
avg = stats.get("avg_confidence_today")
col_s6.metric("🎯  Confidence",      f"{avg:.0%}" if avg else "—", help="Avg extraction confidence today")
with col_r:
    st.write("")
    st.write("")
    if st.button("🔄", help="Refresh all", key="dash_refresh"):
        cached_api.invalidate_live()
        st.rerun()

if stats["pending_review"] > 0:
    callout(
        f"<strong>{stats['pending_review']} document(s)</strong> are waiting for review. "
        "Open <strong>Documents</strong> to approve or reject them.",
        kind="warning",
    )

st.markdown("<br>", unsafe_allow_html=True)

# ── Live Queue ─────────────────────────────────────────────────────────────

section_header("Live Queue", "documents currently in the pipeline")

try:
    queue_data = cached_api.get_dashboard_queue()
    queue = queue_data.get("items", [])
except Exception as e:
    st.error(str(e))
    queue = []

if not queue:
    empty_state("🎉", "Queue is empty", "No documents are processing or awaiting review right now.")
else:
    # Header row
    st.markdown(
        '<div style="display:flex;gap:12px;padding:4px 16px;font-size:.72rem;'
        'color:#6e7681;font-weight:600;text-transform:uppercase;letter-spacing:.05em">'
        '<span style="width:24px"></span>'
        '<span style="flex:1">Document</span>'
        '<span style="width:120px">Progress</span>'
        '<span style="width:60px">Source</span>'
        '<span style="width:70px;text-align:right">Review?</span>'
        '<span style="width:60px;text-align:right">In state</span>'
        '</div>',
        unsafe_allow_html=True,
    )
    for d in queue:
        state = d.get("state", "")
        fg, _ = STATE_COLORS.get(state, ("#8b949e", "#21262d"))
        icon  = STATE_ICONS.get(state, "⚪")
        name  = d.get("label") or d.get("filename", "—")
        prog  = d.get("progress") or state
        secs  = d.get("time_in_state_seconds", 0)
        src   = d.get("source", "—")
        rev   = "✓" if d.get("require_review") else "—"
        st.markdown(
            f'<div class="idp-queue-row">'
            f'<span style="color:{fg};font-size:1.1rem;width:24px">{icon}</span>'
            f'<span style="flex:1;color:#e6edf3;font-weight:500;font-size:.88rem">{name}</span>'
            f'<span style="width:120px;color:#8b949e;font-size:.78rem">{prog}</span>'
            f'<span style="width:60px;color:#8b949e;font-size:.78rem">{src}</span>'
            f'<span style="width:70px;color:#8b949e;font-size:.78rem;text-align:right">{rev}</span>'
            f'<span style="width:60px;color:#6e7681;font-size:.76rem;text-align:right">{secs}s</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

st.markdown("<br>", unsafe_allow_html=True)

# ── Document History ───────────────────────────────────────────────────────

section_header("Document History", "searchable and filterable")

col_f1, col_f2, col_f3, col_f4, col_f5 = st.columns([2, 2, 2, 1, 1])
with col_f1:
    hist_state = st.selectbox(
        "State",
        ["All", "VERIFIED", "PENDING_REVIEW", "PROCESSING",
         "FAILED", "ABANDONED", "DOWNLOADED", "REJECTED"],
        label_visibility="collapsed",
        placeholder="Filter by state…",
    )
with col_f2:
    hist_source = st.selectbox(
        "Source", ["All", "ui", "erp"],
        label_visibility="collapsed",
        placeholder="Source…",
    )
with col_f3:
    hist_search = st.text_input(
        "Search", placeholder="🔍  Search label or filename…",
        label_visibility="collapsed",
    )
with col_f4:
    hist_limit = st.selectbox("Rows", [25, 50, 100], label_visibility="collapsed")
with col_f5:
    hist_offset = st.number_input("Offset", min_value=0, step=25, value=0, label_visibility="collapsed")

try:
    hist = cached_api.get_dashboard_history(
        state=None if hist_state == "All" else hist_state,
        source=None if hist_source == "All" else hist_source,
        search=hist_search or None,
        limit=hist_limit,
        offset=int(hist_offset),
    )
    items = hist.get("items", [])
    total = hist.get("total", 0)
except Exception as e:
    st.error(str(e))
    items, total = [], 0

st.caption(f"**{total}** documents total — showing {len(items)}")

if items:
    # Build table rows with HTML badges
    header = (
        '<div style="display:flex;gap:10px;padding:4px 16px;font-size:.72rem;'
        'color:#6e7681;font-weight:600;text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px">'
        '<span style="flex:1.5">Document</span>'
        '<span style="flex:1">State</span>'
        '<span style="flex:1">Confidence</span>'
        '<span style="flex:0.6">Source</span>'
        '<span style="flex:0.6">Retries</span>'
        '<span style="flex:1">Created</span>'
        '</div>'
    )
    st.markdown(header, unsafe_allow_html=True)
    for d in items:
        name  = d.get("label") or d.get("filename", "—")
        state = d.get("state", "—")
        conf  = d.get("avg_confidence")
        err   = d.get("error_code")
        retries = d.get("retry_count", 0)
        created = d.get("created_at", "")[:16]
        src   = d.get("source", "—")

        state_html = state_badge(state)
        conf_html  = conf_pill(conf)
        err_html   = (
            f'<span style="color:#f87171;font-size:.75rem">{err}</span>'
            if err else ""
        )
        retry_html = (
            f'<span style="color:#fbbf24;font-size:.76rem">↺ {retries}</span>'
            if retries else '<span style="color:#6e7681;font-size:.76rem">—</span>'
        )

        st.markdown(
            f'<div class="idp-queue-row">'
            f'<span style="flex:1.5;color:#e6edf3;font-size:.88rem;font-weight:500">{name}</span>'
            f'<span style="flex:1">{state_html} {err_html}</span>'
            f'<span style="flex:1">{conf_html}</span>'
            f'<span style="flex:0.6;color:#8b949e;font-size:.78rem">{src}</span>'
            f'<span style="flex:0.6">{retry_html}</span>'
            f'<span style="flex:1;color:#6e7681;font-size:.78rem">{created}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )
else:
    empty_state("📋", "No documents found", "Try adjusting the filters above.")


