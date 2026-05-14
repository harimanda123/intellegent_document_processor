"""
IDP — Intelligent Document Processing
Home page — hero banner, KPI cards, live queue, and getting-started guide.

Run from the project root:
    streamlit run ui/app.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st

import api_client as api
import cached_api
from components import (
    render_header, empty_state, callout,
    section_header, step_card, queue_row,
    STATE_COLORS, STATE_ICONS,
)

st.set_page_config(
    page_title="IDP — Intelligent Document Processing",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="expanded",
)

render_header()

# ── Backend health check ───────────────────────────────────────────────────

try:
    stats = cached_api.get_dashboard_stats()
except Exception as e:
    callout(
        f"Cannot connect to backend at <code>{api.BASE_URL}</code>. "
        "Start the server: <code>python main.py</code>",
        kind="warning",
    )
    st.code(str(e))
    st.stop()

# ── Hero banner ────────────────────────────────────────────────────────────

st.markdown(
    """
    <div class="idp-hero">
        <div class="idp-hero-tags">
            <span class="idp-hero-tag">AI-Powered</span>
            <span class="idp-hero-tag">Multi-provider LLM</span>
            <span class="idp-hero-tag">ERP Ready</span>
        </div>
        <h1 class="idp-hero-title">Extract. Review. Deliver.</h1>
        <p class="idp-hero-sub">
            Upload PDFs and images — the AI reads every field, extracts structured data,
            and delivers clean JSON to your team or ERP system automatically.
        </p>
    </div>
    """,
    unsafe_allow_html=True,
)

col_cta1, col_cta2, _ = st.columns([2, 2, 5])
with col_cta1:
    if st.button("📤  Upload a Document", type="primary", use_container_width=True):
        st.switch_page("pages/2_Documents.py")
with col_cta2:
    if st.button("🔧  Build a Schema", use_container_width=True):
            st.switch_page("pages/2_Schema_Builder.py")
st.markdown("<br>", unsafe_allow_html=True)

# ── KPI cards ─────────────────────────────────────────────────────────────

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("📨  Uploaded Today",   stats["documents_today"],
          help="Total documents received today")
c2.metric("🔍  Pending Review",   stats["pending_review"],
          help="Documents waiting for manual review")
c3.metric("✅  Verified Today",   stats["verified_today"],
          help="Documents verified or downloaded today")
c4.metric("❌  Failed Today",     stats["failed_today"],
          help="Documents that failed extraction today")
c5.metric("⚡  Processing Now",   stats["processing_now"],
          help="Documents currently running through the pipeline")

avg = stats.get("avg_confidence_today")
if avg:
    st.caption(f"Avg extraction confidence today: **{avg:.0%}**")

st.markdown("<br>", unsafe_allow_html=True)

# ── Live queue + getting started ───────────────────────────────────────────

col_queue, col_guide = st.columns([3, 2], gap="large")

with col_queue:
    c_title, c_refresh = st.columns([6, 1])
    with c_title:
        section_header("Live Queue", "documents processing right now")
    with c_refresh:
        if st.button("🔄", help="Refresh queue", key="home_refresh"):
            cached_api.invalidate_live()
            st.rerun()

    try:
        queue_data = cached_api.get_dashboard_queue()
        queue = queue_data.get("items", [])
    except Exception as e:
        st.error(str(e))
        queue = []

    if not queue:
        empty_state(
            "🎉",
            "Queue is empty",
            "No documents are currently processing or awaiting review. "
            "Upload a document to get started.",
        )
    else:
        for d in queue:
            state = d.get("state", "")
            fg, _ = STATE_COLORS.get(state, ("#8b949e", "#21262d"))
            icon  = STATE_ICONS.get(state, "⚪")
            name  = d.get("label") or d.get("filename", "—")
            prog  = d.get("progress") or state
            secs  = d.get("time_in_state_seconds", 0)
            queue_row(icon, fg, name, prog, secs)

        if st.button("View full dashboard →", key="to_dashboard"):
            st.switch_page("pages/3_Dashboard.py")

with col_guide:
    section_header("Getting Started", "three simple steps")

    step_card(
        1,
        "Create a Schema",
        "Tell IDP what to extract — invoice total, vendor name, line items. "
        "Use <strong>AI Propose</strong> to auto-generate a schema from any sample document.",
    )
    step_card(
        2,
        "Upload a Document",
        "Drop in a PDF or image. IDP runs OCR, detects tables, and lets the AI "
        "fill in your schema fields with confidence scores.",
    )
    step_card(
        3,
        "Review &amp; Export",
        "Accept the results or correct individual fields. "
        "Download as <strong>JSON</strong> or <strong>CSV</strong>, "
        "or auto-deliver to your ERP via the API.",
    )

    if stats["pending_review"] > 0:
        st.markdown("<br>", unsafe_allow_html=True)
        callout(
            f"<strong>{stats['pending_review']} document(s)</strong> are waiting for your review. "
            "Go to <strong>Documents</strong> to approve or correct them.",
            kind="warning",
        )
