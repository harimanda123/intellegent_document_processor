"""
Documents — Upload, track, review, approve/reject, and download documents.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import streamlit as st

import api_client as api
import cached_api
from components import (
    render_header, state_badge, conf_pill, conf_bar,
    empty_state, callout, section_header,
    STATE_COLORS, STATE_ICONS,
)

st.set_page_config(page_title="Documents — IDP", page_icon="📄", layout="wide")

render_header("Documents")

# Fetch schemas once — reused by both Upload and List tabs.
try:
    _all_schemas = cached_api.list_schemas()
    _active_schemas = [s for s in _all_schemas if s["status"] == "active"]
except Exception:
    _all_schemas = []
    _active_schemas = []

tab_upload, tab_list = st.tabs(["📤  Upload New Document", "📋  All Documents"])


# ══════════════════════════════════════════════════════════════════════════════
# Upload Tab — step-guided wizard
# ══════════════════════════════════════════════════════════════════════════════

with tab_upload:
    # ── Step indicator ────────────────────────────────────────────────────
    st.markdown(
        """
        <div class="idp-upload-steps">
            <div class="idp-ustep active">
                <div class="idp-ustep-num">1</div>
                <span>Choose Schema</span>
            </div>
            <div class="idp-ustep-line"></div>
            <div class="idp-ustep active">
                <div class="idp-ustep-num">2</div>
                <span>Upload File</span>
            </div>
            <div class="idp-ustep-line"></div>
            <div class="idp-ustep active">
                <div class="idp-ustep-num">3</div>
                <span>Options &amp; Submit</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if not _active_schemas:
        empty_state(
            "🔧",
            "No active schemas yet",
            "Before uploading documents, you need at least one active schema "
            "that defines which fields to extract.",
        )
        if st.button("🔧  Go to Schema Builder", type="primary"):
            st.switch_page("pages/2_Schema_Builder.py")
    else:
        col_left, col_right = st.columns([3, 2], gap="large")

        with col_left:
            # Step 1
            section_header("Step 1 — Choose Schema", "what fields should the AI extract?")
            schema_options = {s["name"]: s for s in _active_schemas}
            selected_schema_name = st.selectbox(
                "Active schema",
                list(schema_options.keys()),
                label_visibility="collapsed",
            )
            selected_schema = schema_options[selected_schema_name]
            selected_schema_id = selected_schema["id"]

            # Show schema field list as a quick preview
            fields = selected_schema.get("fields", [])
            if fields:
                field_names = ", ".join(f.get("label") or f.get("json_key", "") for f in fields[:8])
                if len(fields) > 8:
                    field_names += f" +{len(fields) - 8} more"
                callout(
                    f"This schema extracts <strong>{len(fields)} fields</strong>: {field_names}.",
                    kind="info",
                )

            # Step 2
            section_header("Step 2 — Upload File", "PDF, TIFF, JPG, or PNG")
            uploaded_file = st.file_uploader(
                "Drop your document here",
                type=["pdf", "tiff", "tif", "jpg", "jpeg", "png"],
                label_visibility="collapsed",
                help="Supported: PDF, TIFF, JPG, PNG. Maximum 50 MB.",
            )
            if not uploaded_file:
                st.markdown(
                    '<div class="idp-upload-hint">'
                    '📂&nbsp; Drag and drop a file or click Browse<br>'
                    '<small style="color:#6e7681">PDF · TIFF · JPG · PNG &nbsp;·&nbsp; Max 50 MB</small>'
                    '</div>',
                    unsafe_allow_html=True,
                )

            # Step 3
            section_header("Step 3 — Options")
            label = st.text_input(
                "Document label",
                placeholder="e.g.  Invoice #INV-2024-001  (optional)",
                help="A human-readable name shown in the document list.",
            )
            require_review = st.toggle(
                "Force manual review",
                value=False,
                help=(
                    "When ON, this document will always stop at PENDING_REVIEW "
                    "for a human to check — even if AI confidence is high."
                ),
            )
            if require_review:
                callout("Manual review is ON — a reviewer must approve before the result is delivered.", kind="tip")

            submit_disabled = uploaded_file is None
            if st.button(
                "🚀  Extract Now",
                type="primary",
                disabled=submit_disabled,
                use_container_width=True,
                help="Upload the file and start AI extraction in the background.",
            ):
                with st.spinner("Uploading and queuing for extraction…"):
                    try:
                        result = api.upload_document(
                            file_bytes=uploaded_file.read(),
                            filename=uploaded_file.name,
                            schema_id=selected_schema_id,
                            label=label,
                            require_review=require_review,
                        )
                        doc_id = result["id"]
                        cached_api.invalidate_documents()
                        st.session_state["view_doc_id"] = doc_id
                        callout(
                            f"✅ Document accepted — ID <code>{doc_id[:8]}…</code>. "
                            "Switch to <strong>All Documents</strong> to track progress.",
                            kind="success",
                        )
                    except Exception as e:
                        callout(f"Upload failed: {e}", kind="warning")

        with col_right:
            section_header("How it works")
            st.markdown(
                """
                <div class="idp-step-card">
                    <div class="idp-step-num">📄</div>
                    <div>
                        <div class="idp-step-title">OCR &amp; Table Detection</div>
                        <div class="idp-step-desc">The file is scanned page-by-page. Native PDF text is extracted directly; tables are detected and stitched across pages.</div>
                    </div>
                </div>
                <div class="idp-step-card">
                    <div class="idp-step-num">🤖</div>
                    <div>
                        <div class="idp-step-title">AI Field Extraction</div>
                        <div class="idp-step-desc">The LLM reads the structured text and fills every schema field with a value and a confidence score.</div>
                    </div>
                </div>
                <div class="idp-step-card">
                    <div class="idp-step-num">✅</div>
                    <div>
                        <div class="idp-step-title">Review &amp; Export</div>
                        '<div class="idp-step-desc">High-confidence results are auto-verified. Low-confidence ones wait for your review. Download the result as JSON anytime.</div>'
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )


# ══════════════════════════════════════════════════════════════════════════════
# All Documents Tab
# ══════════════════════════════════════════════════════════════════════════════

with tab_list:
    # ── Filters ────────────────────────────────────────────────────────────
    col_f1, col_f2, col_f3, col_btn = st.columns([2, 2, 1, 1])
    with col_f1:
        filter_state = st.selectbox(
            "State",
            ["All", "PENDING_REVIEW", "PROCESSING", "RECEIVED",
             "VERIFIED", "DOWNLOADED", "FAILED", "ABANDONED", "REJECTED"],
            key="list_state",
        )
    with col_f2:
        schema_map = {"All": None, **{s["name"]: s["id"] for s in _all_schemas}}
        filter_schema = st.selectbox("Schema", list(schema_map.keys()), key="list_schema")
    with col_f3:
        limit = st.selectbox("Show", [25, 50, 100], key="list_limit")
    with col_btn:
        st.write("")
        st.write("")
        if st.button("🔄 Refresh", key="list_refresh"):
            cached_api.invalidate_documents()
            st.rerun()

    # ── Highlight pending review ─────────────────────────────────────────
    try:
        pending = cached_api.list_documents(state="PENDING_REVIEW", limit=100)
    except Exception:
        pending = []
    if pending and filter_state == "All":
        callout(
            f"<strong>{len(pending)} document(s)</strong> need your review — "
            "filter by <strong>PENDING_REVIEW</strong> to focus on them.",
            kind="warning",
        )

    # ── Fetch & Display ────────────────────────────────────────────────────
    try:
        docs = cached_api.list_documents(
            state=None if filter_state == "All" else filter_state,
            schema_id=schema_map.get(filter_schema),
            limit=limit,
        )
    except Exception as e:
        st.error(str(e))
        docs = []

    if not docs:
        empty_state(
            "📭",
            "No documents found",
            "Try a different filter, or upload your first document using the Upload tab.",
        )
    else:
        # Column header
        st.markdown(
            '<div style="display:flex;gap:10px;padding:4px 16px;margin-bottom:4px;'
            'font-size:.71rem;color:#6e7681;font-weight:600;text-transform:uppercase;letter-spacing:.05em">'
            '<span style="flex:2">Document</span>'
            '<span style="flex:1">State</span>'
            '<span style="flex:1">Confidence</span>'
            '<span style="flex:0.7">Source</span>'
            '<span style="flex:1">Created</span>'
            '</div>',
            unsafe_allow_html=True,
        )

        doc_labels = []
        for d in docs:
            short_id = d["id"][:8]
            name = d.get("label") or d.get("filename", "—")
            doc_labels.append(f"{name}  [{short_id}…]")
            state = d.get("state", "—")
            conf  = d.get("avg_confidence")

            st.markdown(
                f'<div class="idp-queue-row">'
                f'<span style="flex:2;color:#e6edf3;font-weight:500;font-size:.88rem">{name}'
                f'  <span style="color:#6e7681;font-size:.72rem">[{short_id}…]</span></span>'
                f'<span style="flex:1">{state_badge(state)}</span>'
                f'<span style="flex:1">{conf_pill(conf)}{conf_bar(conf)}</span>'
                f'<span style="flex:0.7;color:#8b949e;font-size:.78rem">{d.get("source","—")}</span>'
                f'<span style="flex:1;color:#6e7681;font-size:.78rem">{d.get("created_at","")[:16]}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )

        # ── Document selector ──────────────────────────────────────────────
        st.markdown("<br>", unsafe_allow_html=True)
        section_header("Open a Document", "select to view extraction, review, or download")

        doc_options = {"— select a document —": None}
        for d, lbl in zip(docs, doc_labels):
            doc_options[lbl] = d["id"]

        default_idx = 0
        if "view_doc_id" in st.session_state:
            for i, did in enumerate(doc_options.values()):
                if did == st.session_state["view_doc_id"]:
                    default_idx = i
                    break

        selected_label = st.selectbox(
            "Document",
            list(doc_options.keys()),
            index=default_idx,
            key="doc_select",
            label_visibility="collapsed",
        )
        if doc_options[selected_label]:
            st.session_state["view_doc_id"] = doc_options[selected_label]

    # ── Document Detail Panel ──────────────────────────────────────────────
    view_id = st.session_state.get("view_doc_id")
    if view_id:
        st.markdown("---")
        col_h, col_close = st.columns([10, 1])
        with col_h:
            section_header(f"Document  {view_id[:8]}…")
        with col_close:
            if st.button("✖", help="Close panel", key="close_detail"):
                st.session_state.pop("view_doc_id", None)
                st.rerun()

        # ── Status bar ────────────────────────────────────────────────────
        try:
            doc_status = api.get_document_status(view_id)
        except Exception as e:
            callout(f"Cannot load status: {e}", kind="warning")
            doc_status = {}

        state = doc_status.get("state", "—")
        fg, bg = STATE_COLORS.get(state, ("#8b949e", "#21262d"))

        col_s1, col_s2, col_s3, col_s4 = st.columns(4)
        col_s1.metric("State",       f"{STATE_ICONS.get(state,'⚪')} {state}")
        col_s2.metric("Progress",    doc_status.get("progress") or "—")
        col_s3.metric("Confidence",  f"{doc_status.get('avg_confidence', 0):.0%}"
                      if doc_status.get("avg_confidence") else "—")
        col_s4.metric("Processing",  f"{doc_status.get('processing_ms', 0):,} ms"
                      if doc_status.get("processing_ms") else "—")

        # ── Tabs for detail sections ───────────────────────────────────────
        if state in ("FAILED", "ABANDONED"):
            callout(
                f"<strong>{doc_status.get('error_code','ERROR')}</strong> — "
                f"{doc_status.get('error_message','Unknown error')}",
                kind="warning",
            )
            if st.button("🔁  Retry Document", type="primary", key="retry_btn"):
                try:
                    api.retry_document(view_id)
                    cached_api.invalidate_documents()
                    callout("Retry queued. Refresh in a few seconds.", kind="success")
                    st.rerun()
                except Exception as e:
                    st.error(str(e))

        elif state in ("VERIFIED", "DOWNLOADED", "PENDING_REVIEW"):
            dtab_fields, dtab_review, dtab_download, dtab_audit = st.tabs([
                "🔍  Fields", "📝  Review", "⬇️  Download", "📋  Audit"
            ])

            # ── Fields tab ────────────────────────────────────────────────
            with dtab_fields:
                try:
                    result = api.get_document_result(view_id)
                    fields = result.get("data", {})
                except Exception as e:
                    callout(f"Cannot load result: {e}", kind="warning")
                    fields = {}

                if not fields:
                    empty_state("🔎", "No extraction data", "The document may still be processing.")
                else:
                    pending_edits: dict = {}
                    missing_fields = [k for k, v in fields.items() if v.get("missing")]

                    if missing_fields:
                        callout(
                            f"<strong>{len(missing_fields)} field(s) could not be found</strong>: "
                            + ", ".join(f"<code>{k}</code>" for k in missing_fields[:5])
                            + (f" +{len(missing_fields)-5} more" if len(missing_fields) > 5 else ""),
                            kind="warning",
                        )

                    for key, fdata in fields.items():
                        val     = fdata.get("value")
                        conf    = fdata.get("confidence")
                        missing = fdata.get("missing", False)
                        edited  = fdata.get("human_edited", False)

                        fg_col  = "#4ade80" if (conf or 0) >= 0.90 else "#fbbf24" if (conf or 0) >= 0.70 else "#f87171"
                        if missing:
                            fg_col = "#8b949e"

                        edited_span = (
                            '<span style="color:#fbbf24;font-size:.75rem">\u270f\ufe0f edited</span>'
                            if edited else ""
                        )
                        badge_row = (
                            f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">'
                            f'<span style="font-size:.72rem;color:#8b949e;font-weight:600;text-transform:uppercase;letter-spacing:.06em">{key}</span>'
                            f'{edited_span}'
                            f'<span style="margin-left:auto">{conf_pill(conf)}</span>'
                            f'</div>'
                        )

                        with st.expander(
                            f"{'⚫ ' if missing else ''}{'✏️ ' if edited else ''}{key}",
                            expanded=missing,
                        ):
                            st.markdown(badge_row, unsafe_allow_html=True)
                            if missing:
                                st.markdown(
                                    '<div class="idp-field-missing">Not found in document</div>',
                                    unsafe_allow_html=True,
                                )
                            elif isinstance(val, list):
                                st.dataframe(val, use_container_width=True, hide_index=True)
                            else:
                                new_val = st.text_input(
                                    "Value",
                                    value=str(val) if val is not None else "",
                                    key=f"field_{view_id}_{key}",
                                )
                                if new_val != str(val if val is not None else ""):
                                    pending_edits[key] = new_val

                                if fdata.get("original_value") is not None:
                                    st.caption(f"Original AI value: `{fdata['original_value']}`")

                    if pending_edits:
                        callout(
                            f"<strong>{len(pending_edits)} unsaved edit(s)</strong>. "
                            "Click Save to record your corrections.",
                            kind="tip",
                        )
                        if st.button("💾  Save Field Edits", type="primary", key="save_edits"):
                            errors = []
                            for k, v in pending_edits.items():
                                try:
                                    api.edit_field(view_id, k, v)
                                except Exception as ex:
                                    errors.append(f"{k}: {ex}")
                            if errors:
                                st.error("\n".join(errors))
                            else:
                                callout("Fields saved successfully.", kind="success")
                                st.rerun()

            # ── Review tab ────────────────────────────────────────────────
            with dtab_review:
                if state != "PENDING_REVIEW":
                    callout(
                        f"This document is in <strong>{state}</strong> state — no review action needed.",
                        kind="info",
                    )
                else:
                    callout(
                        "Review the extracted fields in the <strong>Fields</strong> tab, "
                        "correct any errors, then approve or reject below.",
                        kind="tip",
                    )
                    conf = doc_status.get("avg_confidence")
                    if conf and conf < 0.75:
                        callout(
                            f"Average confidence is <strong>{conf:.0%}</strong> — "
                            "please carefully verify all fields before approving.",
                            kind="warning",
                        )

                    col_a, col_r = st.columns(2, gap="medium")
                    with col_a:
                        st.markdown(
                            '<div style="background:#0f3520;border:1px solid #4ade8030;'
                            'border-radius:10px;padding:16px;margin-bottom:12px">'
                            '<div style="color:#4ade80;font-weight:700;font-size:.95rem;margin-bottom:6px">✅ Approve</div>'
                            '<div style="color:#8b949e;font-size:.83rem">Mark as VERIFIED and release for download or ERP delivery.</div>'
                            '</div>',
                            unsafe_allow_html=True,
                        )
                        if st.button("✅  Approve Document", type="primary", key="approve_btn", use_container_width=True):
                            try:
                                api.approve_document(view_id)
                                callout("Document approved and marked VERIFIED.", kind="success")
                                st.session_state.pop("view_doc_id", None)
                                st.rerun()
                            except Exception as e:
                                st.error(str(e))

                    with col_r:
                        st.markdown(
                            '<div style="background:#3b0f0f;border:1px solid #f8717130;'
                            'border-radius:10px;padding:16px;margin-bottom:12px">'
                            '<div style="color:#f87171;font-weight:700;font-size:.95rem;margin-bottom:6px">❌ Reject</div>'
                            '<div style="color:#8b949e;font-size:.83rem">Mark as REJECTED. Optionally add a reason below.</div>'
                            '</div>',
                            unsafe_allow_html=True,
                        )
                        reject_reason = st.text_input(
                            "Rejection reason",
                            placeholder="e.g. Wrong document type",
                            key="reject_reason",
                            label_visibility="collapsed",
                        )
                        if st.button("❌  Reject Document", key="reject_btn", use_container_width=True):
                            try:
                                api.reject_document(view_id, reject_reason)
                                callout("Document rejected.", kind="warning")
                                st.session_state.pop("view_doc_id", None)
                                st.rerun()
                            except Exception as e:
                                st.error(str(e))

            # ── Download tab ──────────────────────────────────────────────
            with dtab_download:
                callout(
                    "Downloads capture the current extracted values including any edits you made.",
                    kind="info",
                )
                st.markdown(
                    '<div style="background:#161b22;border:1px solid #21262d;border-radius:10px;padding:16px;margin-bottom:16px">'
                    '<div style="font-weight:700;color:#e6edf3;margin-bottom:4px">📄 JSON</div>'
                    '<div style="color:#8b949e;font-size:.82rem">Full extraction result including all field values, confidence scores, and metadata.</div>'
                    '</div>',
                    unsafe_allow_html=True,
                )
                try:
                    json_bytes = api.download_json(view_id)
                    st.download_button(
                        "⬇️  Download JSON",
                        data=json_bytes,
                        file_name=f"idp_{view_id[:8]}.json",
                        mime="application/json",
                        use_container_width=True,
                        type="primary",
                    )
                except Exception:
                    st.button("⬇️  Download JSON", disabled=True, use_container_width=True)

            # ── Audit tab ─────────────────────────────────────────────────
            with dtab_audit:
                callout(
                    "Every state change and field edit is permanently recorded here. "
                    "The audit trail is immutable.",
                    kind="info",
                )
                try:
                    audit = api.get_audit(view_id)
                    if audit:
                        st.dataframe(
                            [
                                {
                                    "Time":   a.get("created_at", "")[:19],
                                    "Action": a.get("action", "—"),
                                    "Actor":  a.get("actor", "—"),
                                    "Detail": a.get("new_value", "") or "",
                                }
                                for a in audit
                            ],
                            use_container_width=True,
                            hide_index=True,
                        )
                    else:
                        empty_state("📋", "No audit entries yet", "Actions will appear here as the document is processed.")
                except Exception as e:
                    st.error(str(e))

        elif state in ("RECEIVED", "PROCESSING"):
            callout(
                f"Document is <strong>{state}</strong> — extraction is running in the background. "
                "Refresh in a few seconds to check progress.",
                kind="info",
            )
            if st.button("🔄  Refresh Status", key="status_refresh"):
                st.rerun()


