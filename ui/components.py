"""
Shared UI components for IDP Streamlit app.
All CSS is defined as module-level string constants — zero rebuild cost per re-render.
"""
import streamlit as st

# ── State metadata ───────────────────────────────────────────────────────────

STATE_COLORS = {
    "RECEIVED":       ("#60a5fa", "#1e3a5f"),
    "PROCESSING":     ("#fbbf24", "#3f2a00"),
    "PENDING_REVIEW": ("#fb923c", "#3d1f00"),
    "VERIFIED":       ("#4ade80", "#0f3520"),
    "DOWNLOADED":     ("#34d399", "#0a2e20"),
    "FAILED":         ("#f87171", "#3b0f0f"),
    "ABANDONED":      ("#9ca3af", "#1f2937"),
    "REJECTED":       ("#a78bfa", "#2e1f4a"),
}

STATE_ICONS = {
    "RECEIVED":       "🔵",
    "PROCESSING":     "⚡",
    "PENDING_REVIEW": "🔍",
    "VERIFIED":       "✅",
    "DOWNLOADED":     "⬇️",
    "FAILED":         "❌",
    "ABANDONED":      "⛔",
    "REJECTED":       "🚫",
}

# ── Page CSS ─────────────────────────────────────────────────────────────────

_PAGE_CSS = """<style>
/* ── Base ── */
html,body,[data-testid="stAppViewContainer"]{background-color:#0d1117}
[data-testid="stSidebar"]{background:linear-gradient(180deg,#161b22 0%,#0d1117 100%);border-right:1px solid #21262d}
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p{font-size:.85rem}

/* ── Header bar ── */
.idp-header{display:flex;align-items:center;gap:14px;padding:14px 0 10px;border-bottom:2px solid #1f6feb;margin-bottom:24px}
.idp-logo{font-size:1.8rem;line-height:1;filter:drop-shadow(0 0 8px #1f6feb80)}
.idp-brand-mark{display:flex;flex-direction:column;border-right:1px solid #21262d;padding-right:14px;margin-right:2px}
.idp-brand-name{font-size:1rem;font-weight:800;letter-spacing:.06em;background:linear-gradient(90deg,#58a6ff,#79c0ff);-webkit-background-clip:text;-webkit-text-fill-color:transparent;line-height:1.1}
.idp-page-title{font-size:1.5rem;font-weight:700;color:#e6edf3;letter-spacing:.01em}

/* ── Metric cards ── */
[data-testid="stMetric"]{background:#161b22;border:1px solid #21262d;border-radius:10px;padding:14px 18px;transition:border-color .2s}
[data-testid="stMetric"]:hover{border-color:#1f6feb}
[data-testid="stMetricLabel"]{color:#8b949e!important;font-size:.78rem!important}
[data-testid="stMetricValue"]{color:#e6edf3!important}

/* ── State badge pills ── */
.idp-badge{display:inline-block;padding:3px 10px;border-radius:20px;font-size:.76rem;font-weight:600;letter-spacing:.03em;white-space:nowrap}

/* ── Hero ── */
.idp-hero{background:linear-gradient(135deg,#161b22 0%,#1a2332 60%,#161b22 100%);border:1px solid #21262d;border-radius:16px;padding:36px 40px;margin-bottom:24px;position:relative;overflow:hidden}
.idp-hero::before{content:'';position:absolute;top:-60px;right:-60px;width:240px;height:240px;border-radius:50%;background:radial-gradient(circle,#1f6feb18,transparent 70%)}
.idp-hero-tags{margin-bottom:14px}
.idp-hero-tag{display:inline-block;background:#1f6feb20;color:#58a6ff;border:1px solid #1f6feb40;border-radius:4px;padding:2px 8px;font-size:.72rem;font-weight:600;letter-spacing:.05em;margin-right:8px}
.idp-hero-title{font-size:2.1rem;font-weight:800;color:#e6edf3;margin:0 0 10px;line-height:1.2}
.idp-hero-sub{font-size:.98rem;color:#8b949e;margin:0;line-height:1.6}

/* ── Getting started step cards ── */
.idp-step-card{background:#161b22;border:1px solid #21262d;border-radius:10px;padding:16px 18px;margin-bottom:10px;display:flex;gap:14px;align-items:flex-start;transition:border-color .2s,transform .1s}
.idp-step-card:hover{border-color:#1f6feb;transform:translateX(3px)}
.idp-step-num{width:32px;height:32px;border-radius:50%;background:#1f6feb20;border:2px solid #1f6feb;color:#58a6ff;font-weight:700;font-size:.88rem;display:flex;align-items:center;justify-content:center;flex-shrink:0}
.idp-step-title{font-weight:700;color:#e6edf3;font-size:.92rem;margin-bottom:3px}
.idp-step-desc{color:#8b949e;font-size:.82rem;line-height:1.5}

/* ── Section divider ── */
.idp-section{display:flex;align-items:center;gap:10px;margin:18px 0 10px;padding-bottom:8px;border-bottom:1px solid #21262d}
.idp-section-title{font-size:.95rem;font-weight:700;color:#e6edf3}
.idp-section-help{font-size:.76rem;color:#8b949e}

/* ── Empty states ── */
.idp-empty{background:#161b22;border:1px dashed #30363d;border-radius:12px;padding:44px 20px;text-align:center;margin:12px 0}
.idp-empty-icon{font-size:2.8rem;margin-bottom:12px}
.idp-empty-title{font-size:1rem;font-weight:700;color:#e6edf3;margin-bottom:6px}
.idp-empty-msg{font-size:.86rem;color:#8b949e;max-width:380px;margin:0 auto;line-height:1.5}

/* ── Callout boxes ── */
.idp-callout{border-radius:8px;padding:12px 16px;margin:8px 0;display:flex;gap:10px;align-items:flex-start;font-size:.86rem;color:#e6edf3;line-height:1.5}

/* ── Queue rows ── */
.idp-queue-row{background:#161b22;border:1px solid #21262d;border-radius:8px;padding:12px 16px;margin-bottom:7px;display:flex;align-items:center;gap:12px;transition:border-color .15s}
.idp-queue-row:hover{border-color:#30363d}

/* ── Field result cards ── */
.idp-field-card{background:#161b22;border:1px solid #21262d;border-radius:8px;padding:14px 16px;margin-bottom:8px;transition:border-color .2s}
.idp-field-card:hover{border-color:#30363d}
.idp-field-key{font-size:.72rem;color:#8b949e;font-weight:600;text-transform:uppercase;letter-spacing:.06em;margin-bottom:4px}
.idp-field-val{font-size:.98rem;color:#e6edf3;font-weight:500;word-break:break-all}
.idp-field-missing{font-size:.88rem;color:#8b949e;font-style:italic}

/* ── Confidence mini-bar ── */
.idp-bar-wrap{background:#21262d;border-radius:4px;height:5px;margin-top:6px;overflow:hidden}
.idp-bar-fill{border-radius:4px;height:5px}

/* ── Schema card ── */
.idp-schema-card{background:#161b22;border:1px solid #21262d;border-radius:10px;padding:18px 20px;margin-bottom:10px;transition:border-color .2s}
.idp-schema-card:hover{border-color:#30363d}

/* ── Upload step indicator ── */
.idp-upload-steps{display:flex;align-items:center;margin-bottom:20px;gap:0}
.idp-ustep{display:flex;align-items:center;gap:6px;font-size:.8rem;font-weight:600;color:#8b949e}
.idp-ustep-num{width:24px;height:24px;border-radius:50%;background:#21262d;border:2px solid #30363d;display:flex;align-items:center;justify-content:center;font-size:.72rem;color:#8b949e}
.idp-ustep.active .idp-ustep-num{background:#1f6feb20;border-color:#1f6feb;color:#58a6ff}
.idp-ustep.active{color:#e6edf3}
.idp-ustep-line{flex:1;height:2px;background:#21262d;margin:0 8px}

/* ── Tabs ── */
[data-testid="stTabs"] [data-baseweb="tab"]{font-size:.86rem}
[data-testid="stTabs"] [data-baseweb="tab"][aria-selected="true"]{color:#58a6ff}

/* ── Buttons ── */
[data-testid="stButton"]>button[kind="primary"]{background:linear-gradient(135deg,#1f6feb,#388bfd);border:none;font-weight:600}
[data-testid="stButton"]>button[kind="primary"]:hover{background:linear-gradient(135deg,#388bfd,#58a6ff)}

/* ── Sidebar nav ── */
[data-testid="stSidebarContent"]{display:flex;flex-direction:column;gap:0}
[data-testid="stSidebarNav"]{order:2;margin-top:0;padding-top:0}
[data-testid="stSidebarContent"]>[data-testid="stVerticalBlock"]{order:1;margin-bottom:0;padding-bottom:0}
[data-testid="stSidebarNav"] a{border-radius:6px;padding:6px 10px;font-size:.86rem;transition:background .15s}
[data-testid="stSidebarNav"] a:hover{background:#21262d}
[data-testid="stSidebarNav"] a[aria-current="page"]{background:#1f6feb20;color:#58a6ff;font-weight:600}
</style>"""

_SIDEBAR_HTML = """<style>
.idp-sidebar-brand{display:flex;align-items:center;gap:10px;padding:10px 0 10px;border-bottom:1px solid #21262d;margin-bottom:4px}
.idp-sidebar-icon{font-size:1.9rem;line-height:1;filter:drop-shadow(0 0 6px #1f6feb60)}
.idp-sidebar-name{font-size:1.3rem;font-weight:800;background:linear-gradient(90deg,#58a6ff,#79c0ff);-webkit-background-clip:text;-webkit-text-fill-color:transparent;letter-spacing:.04em;line-height:1.15}
.idp-sidebar-tagline{font-size:.63rem;color:#8b949e;text-transform:uppercase;letter-spacing:.08em}
</style>
<div class="idp-sidebar-brand">
    <div class="idp-sidebar-icon">📄</div>
    <div>
        <div class="idp-sidebar-name">IDP</div>
        <div class="idp-sidebar-tagline">Intelligent Document Processing</div>
    </div>
</div>"""

_HEADER_TEMPLATE = """<div class="idp-header">
    {page_slot}
</div>"""


# ── Public API ───────────────────────────────────────────────────────────────

def render_header(page_title: str = "") -> None:
    """Renders IDP header bar + sidebar branding. CSS is module-level — no rebuild cost."""
    st.markdown(_PAGE_CSS, unsafe_allow_html=True)
    st.sidebar.markdown(_SIDEBAR_HTML, unsafe_allow_html=True)
    page_slot = (
        f'<span class="idp-page-title">{page_title}</span>' if page_title
        else '<span class="idp-page-title">Home</span>'
    )
    st.markdown(_HEADER_TEMPLATE.format(page_slot=page_slot), unsafe_allow_html=True)


def state_badge(state: str) -> str:
    """Return an HTML colored pill for a document state."""
    fg, bg = STATE_COLORS.get(state, ("#8b949e", "#21262d"))
    icon = STATE_ICONS.get(state, "⚪")
    return (
        f'<span class="idp-badge" style="color:{fg};background:{bg};border:1px solid {fg}55">'
        f'{icon}&nbsp;{state}</span>'
    )


def conf_pill(v: float | None) -> str:
    """Return an HTML confidence percentage pill."""
    if v is None:
        return '<span class="idp-badge" style="color:#8b949e;background:#21262d;border:1px solid #30363d">—</span>'
    pct = f"{v:.0%}"
    if v >= 0.90:
        return f'<span class="idp-badge" style="color:#4ade80;background:#0f3520;border:1px solid #4ade8055">{pct}</span>'
    if v >= 0.70:
        return f'<span class="idp-badge" style="color:#fbbf24;background:#3f2a00;border:1px solid #fbbf2455">{pct}</span>'
    return f'<span class="idp-badge" style="color:#f87171;background:#3b0f0f;border:1px solid #f8717155">{pct}</span>'


def conf_bar(v: float | None) -> str:
    """Return an HTML mini confidence bar."""
    if v is None:
        return ""
    pct = int(v * 100)
    color = "#4ade80" if v >= 0.90 else "#fbbf24" if v >= 0.70 else "#f87171"
    return (
        f'<div class="idp-bar-wrap">'
        f'<div class="idp-bar-fill" style="width:{pct}%;background:{color}"></div>'
        f'</div>'
    )


def empty_state(icon: str, title: str, message: str) -> None:
    """Render a centered empty-state box."""
    st.markdown(
        f'<div class="idp-empty">'
        f'<div class="idp-empty-icon">{icon}</div>'
        f'<div class="idp-empty-title">{title}</div>'
        f'<div class="idp-empty-msg">{message}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


def callout(message: str, kind: str = "info") -> None:
    """Render a styled callout box. kind: info | tip | warning | success"""
    icons  = {"info": "ℹ️", "tip": "💡", "warning": "⚠️", "success": "✅"}
    colors = {
        "info":    ("#58a6ff", "#1e3a5f"),
        "tip":     ("#fbbf24", "#3f2a00"),
        "warning": ("#fb923c", "#3d1f00"),
        "success": ("#4ade80", "#0f3520"),
    }
    icon = icons.get(kind, "ℹ️")
    fg, bg = colors.get(kind, ("#58a6ff", "#1e3a5f"))
    st.markdown(
        f'<div class="idp-callout" style="background:{bg};border-left:3px solid {fg}">'
        f'<span>{icon}</span><span>{message}</span></div>',
        unsafe_allow_html=True,
    )


def section_header(title: str, help_text: str = "") -> None:
    """Render a styled section divider with optional help text."""
    help_span = f'<span class="idp-section-help">— {help_text}</span>' if help_text else ""
    st.markdown(
        f'<div class="idp-section">'
        f'<span class="idp-section-title">{title}</span>{help_span}</div>',
        unsafe_allow_html=True,
    )


def step_card(num: int, title: str, desc: str) -> None:
    """Render a numbered getting-started step card."""
    st.markdown(
        f'<div class="idp-step-card">'
        f'<div class="idp-step-num">{num}</div>'
        f'<div><div class="idp-step-title">{title}</div>'
        f'<div class="idp-step-desc">{desc}</div></div>'
        f'</div>',
        unsafe_allow_html=True,
    )


def queue_row(icon: str, fg: str, name: str, progress: str, secs: int) -> None:
    """Render a single live-queue item row."""
    st.markdown(
        f'<div class="idp-queue-row">'
        f'<span style="color:{fg};font-size:1.1rem">{icon}</span>'
        f'<span style="flex:1;color:#e6edf3;font-weight:500;font-size:.9rem">{name}</span>'
        f'<span style="color:#8b949e;font-size:.78rem">{progress}</span>'
        f'<span style="color:#6e7681;font-size:.76rem;min-width:48px;text-align:right">{secs}s</span>'
        f'</div>',
        unsafe_allow_html=True,
    )
