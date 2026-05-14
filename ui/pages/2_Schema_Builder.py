"""
Schema Builder — Create, manage, test, and evolve extraction schemas.

Tabs:
  Schemas       — list with status badges and quick actions
  Build / Edit  — create new or edit existing schema with field table
  AI Propose    — upload sample doc, review AI-generated field proposal, save
  Test          — live extraction preview against a test document
  History       — version timeline with restore
  Feedback      — pending corrections and apply-feedback loop
"""
import os
import sys
import json

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import pandas as pd
import streamlit as st

import api_client as api
import cached_api
from components import (
    render_header, state_badge, empty_state, callout,
    section_header, STATE_COLORS,
)

st.set_page_config(page_title="Schema Builder — IDP", page_icon="🔧", layout="wide")

STATUS_BADGE = {
    "draft":    "🟡 draft",
    "active":   "🟢 active",
    "archived": "⚫ archived",
}

STATUS_COLORS = {
    "draft":    ("#fbbf24", "#3f2a00"),
    "active":   ("#4ade80", "#0f3520"),
    "archived": ("#9ca3af", "#1f2937"),
}

FIELD_TYPES = ["string", "number", "date", "currency", "boolean", "table"]

ALLOWED_EXTENSIONS = ["pdf", "tiff", "tif", "jpg", "jpeg", "png"]


def list_str(v) -> str:
    """Convert a list to a comma-separated string for editing."""
    if isinstance(v, list):
        return ", ".join(str(x) for x in v)
    return str(v) if v else ""


def split_str(s: str) -> list[str]:
    """Convert a comma-separated string back to a list."""
    return [x.strip() for x in s.split(",") if x.strip()]


def fields_to_df(fields: list[dict]) -> pd.DataFrame:
    """Convert schema fields list to a DataFrame for data_editor."""
    rows = []
    for f in fields:
        rows.append({
            "json_key": f.get("json_key", ""),
            "label": f.get("label", ""),
            "field_type": f.get("field_type", "string"),
            "required": f.get("required", False),
            "confidence_threshold": f.get("confidence_threshold", 0.80),
            "hints": list_str(f.get("hints", [])),
            "anchors": list_str(f.get("anchors", [])),
            "exclude_if_near": list_str(f.get("exclude_if_near", [])),
            "section": f.get("section", ""),
            "description": f.get("description", ""),
        })
    return pd.DataFrame(rows) if rows else pd.DataFrame(columns=[
        "json_key", "label", "field_type", "required",
        "confidence_threshold", "hints", "anchors",
        "exclude_if_near", "section", "description",
    ])


def df_to_fields(df: pd.DataFrame) -> list[dict]:
    """Convert a data_editor DataFrame back to schema fields list."""
    fields = []
    for _, row in df.iterrows():
        key = str(row.get("json_key", "")).strip()
        if not key:
            continue
        fields.append({
            "json_key": key,
            "label": str(row.get("label", key)),
            "field_type": str(row.get("field_type", "string")),
            "required": bool(row.get("required", False)),
            "confidence_threshold": float(row.get("confidence_threshold", 0.80)),
            "hints": split_str(str(row.get("hints", ""))),
            "anchors": split_str(str(row.get("anchors", ""))),
            "exclude_if_near": split_str(str(row.get("exclude_if_near", ""))),
            "section": str(row.get("section", "")),
            "description": str(row.get("description", "")),
            "position_preference": "",
            "validation": "",
            "table_columns": [],
            "feedback_weight": 1.0,
        })
    return fields


# ── Visual builder helpers ─────────────────────────────────────────────────

import re as _re


def _guess_field_type(label: str) -> str:
    """Guess a sensible field type from a label string."""
    ll = label.lower()
    if any(w in ll for w in ("date", "time", " eta", " etd", "arrival", "departure", "shipment date")):
        return "date"
    if any(w in ll for w in ("total", "amount", "price", "value", "cost", "fee", "charge", "insurance", "freight", "packing")):
        return "currency"
    if any(w in ll for w in ("quantity", "qty", " qty", "number", "count", "weight", "no.", "#")):
        return "number"
    if any(w in ll for w in ("containerized", "prepaid", "insured", "certified", "collect")):
        return "boolean"
    return "string"


def _render_pdf_pages(file_bytes: bytes) -> list[bytes]:
    """Render each PDF page to PNG bytes using PyMuPDF."""
    try:
        import fitz  # type: ignore
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        images = []
        for page in doc:
            pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
            images.append(pix.tobytes("png"))
        doc.close()
        return images
    except Exception:
        return []


def _detect_doc_labels(file_bytes: bytes) -> tuple[list[dict], dict]:
    """
    Detect label candidates from PDF text using word bounding boxes.

    Returns:
        scalar_labels  – list of {label, key, type_hint}
        table_info     – {detected, key, columns:[{label, key, type_hint}]}
    """
    try:
        import fitz  # type: ignore
    except ImportError:
        return [], {"detected": False, "key": "line_items", "columns": []}

    doc = fitz.open(stream=file_bytes, filetype="pdf")

    # Collect all text lines from page 1 only (header-detection focus)
    line_map: dict[int, list[dict]] = {}  # y_bucket -> [{x, text}]

    for page_num, page in enumerate(doc, 1):
        if page_num > 1:
            break
        raw_words = page.get_text("words")  # (x0,y0,x1,y1,word,block,line,wid)
        for w in raw_words:
            y_key = round(w[1] / 4) * 4
            line_map.setdefault(y_key, []).append({"x": w[0], "text": w[4]})

    doc.close()

    # For each Y line, join words and decide if it's a label candidate
    label_info: dict[str, dict] = {}  # normalized_text -> {label, x, y, word_count}

    for y_key, ws in line_map.items():
        ws_sorted = sorted(ws, key=lambda w: w["x"])
        text = " ".join(w["text"] for w in ws_sorted).rstrip(":").strip()
        if len(text) < 2 or len(text) > 65:
            continue
        words = text.split()
        if len(words) > 8:
            continue
        # Must be predominantly uppercase (form labels are typically ALL CAPS)
        upper = sum(1 for w in words if w.isupper() or (len(w) > 1 and w[0].isupper()))
        if upper / len(words) < 0.7:
            continue
        # Skip pure numbers / single chars
        if _re.match(r'^[\d.,/:() -]+$', text):
            continue

        norm = text.upper()
        if norm not in label_info:
            label_info[norm] = {
                "label": text,
                "x": ws_sorted[0]["x"],
                "y": y_key,
                "word_count": len(words),
                "count": 1,
            }
        else:
            label_info[norm]["count"] += 1

    # Find table header row: the Y line that has the most simultaneous label candidates
    y_to_norms: dict[int, list[str]] = {}
    for norm, info in label_info.items():
        y_to_norms.setdefault(info["y"], []).append(norm)

    best_table_y = -1
    best_table_count = 2  # need at least 3 columns to call it a table
    for y, norms in y_to_norms.items():
        if len(norms) > best_table_count:
            best_table_count = len(norms)
            best_table_y = y

    table_norms: set[str] = set(y_to_norms.get(best_table_y, []))

    # Build result lists
    scalar_labels: list[dict] = []
    table_columns: list[dict] = []

    for norm, info in label_info.items():
        key = _re.sub(r'[^a-z0-9]+', '_', info["label"].lower()).strip('_')
        type_hint = _guess_field_type(info["label"])
        entry = {"label": info["label"], "key": key, "type_hint": type_hint, "x": info["x"]}
        if norm in table_norms:
            table_columns.append(entry)
        else:
            scalar_labels.append(entry)

    # Sort table columns left → right
    table_columns.sort(key=lambda c: c["x"])

    return scalar_labels, {
        "detected": len(table_columns) >= 2,
        "key": "line_items",
        "columns": table_columns,
    }


render_header("Schema Builder")

# Fetch schemas once — shared across all tabs to avoid redundant API calls.
try:
    _all_schemas = cached_api.list_schemas()
except Exception:
    _all_schemas = []

(
    tab_schemas,
    tab_build,
    tab_propose,
    tab_test,
    tab_history,
    tab_feedback,
) = st.tabs([
    "📋 Schemas",
    "✏️  Build / Edit",
    "🤖 AI Propose",
    "🧪 Test",
    "🕓 History",
    "🔁 Feedback",
])

# ══════════════════════════════════════════════════════════════════════════════
# Tab 1 — Schema List
# ══════════════════════════════════════════════════════════════════════════════

with tab_schemas:
    callout(
        "Schemas define <strong>what fields</strong> the AI will look for in every document. "
        "Create a schema once — reuse it for all documents of the same type.",
        kind="info",
    )

    col_filter, col_refresh = st.columns([3, 1])
    with col_filter:
        status_filter = st.selectbox(
            "Filter by status", ["All", "active", "draft", "archived"],
            label_visibility="collapsed",
        )
    with col_refresh:
        st.write("")
        if st.button("🔄 Refresh", key="schemas_refresh"):
            cached_api.invalidate_schemas()
            st.rerun()

    try:
        filter_val = None if status_filter == "All" else status_filter
        schemas = [s for s in _all_schemas if filter_val is None or s["status"] == filter_val]
    except Exception as e:
        st.error(str(e))
        schemas = []

    if not schemas:
        empty_state(
            "🔧",
            "No schemas found",
            "Create your first schema in the Build / Edit tab, or let AI generate one "
            "for you in the AI Propose tab — just upload a sample document.",
        )
    else:
        section_header(f"{len(schemas)} Schema(s)", "click Edit to make changes")
        for s in schemas:
            fg, bg = STATUS_COLORS.get(s["status"], ("#8b949e", "#21262d"))
            status_pill = (
                f'<span class="idp-badge" style="color:{fg};background:{bg};'
                f'border:1px solid {fg}55">{s["status"]}</span>'
            )
            ver_pill = (
                f'<span class="idp-badge" style="color:#8b949e;background:#21262d;'
                f'border:1px solid #30363d">v{s["version"]}</span>'
            )
            field_count = len(s.get("fields", []))
            desc_html = (
                f'<div style="color:#8b949e;font-size:.82rem">{s["description"]}</div>'
                if s.get("description") else ""
            )
            st.markdown(
                f'<div class="idp-schema-card">'
                f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:6px">'
                f'<span style="font-weight:700;color:#e6edf3;font-size:.98rem">{s["name"]}</span>'
                f'{status_pill}&nbsp;{ver_pill}'
                f'<span style="margin-left:auto;color:#8b949e;font-size:.76rem">'
                f'{field_count} field(s) &nbsp;\u00b7&nbsp; {s.get("document_type","")} &nbsp;\u00b7&nbsp; {s.get("created_at","")[:10]}'
                f'</span></div>'
                f'{desc_html}'
                f'</div>',
                unsafe_allow_html=True,
            )

            col_info, btn1, btn2, btn3, btn4 = st.columns([5, 1, 1, 1, 1])
            with btn1:
                if st.button("✏️ Edit", key=f"edit_{s['id']}", use_container_width=True):
                    st.session_state["build_schema_id"] = s["id"]
                    st.session_state["build_schema_data"] = s
                    callout("Schema loaded — switch to the <strong>Build / Edit</strong> tab.", kind="tip")

            with btn2:
                if s["status"] == "draft":
                    if st.button("▶️ Activate", key=f"activate_{s['id']}", use_container_width=True):
                        try:
                            api.activate_schema(s["id"])
                            cached_api.invalidate_schemas()
                            st.rerun()
                        except Exception as e:
                            st.error(str(e))
                else:
                    st.button("▶️ Activate", key=f"activate_{s['id']}", disabled=True, use_container_width=True)

            with btn3:
                if st.button("📋 Clone", key=f"dup_{s['id']}", use_container_width=True):
                    try:
                        new = api.duplicate_schema(s["id"])
                        cached_api.invalidate_schemas()
                        callout(f"Cloned as <strong>{new['name']}</strong>.", kind="success")
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))

            with btn4:
                if s["status"] != "archived":
                    if st.button("🗑️ Archive", key=f"arch_{s['id']}", use_container_width=True):
                        try:
                            api.archive_schema(s["id"])
                            cached_api.invalidate_schemas()
                            st.rerun()
                        except Exception as e:
                            st.error(str(e))

# ══════════════════════════════════════════════════════════════════════════════
# Tab 2 — Build / Edit
# ══════════════════════════════════════════════════════════════════════════════
# Tab 2 — Build / Edit  (Document-Guided Visual Builder)
# ══════════════════════════════════════════════════════════════════════════════

_SB_KEYS = [
    "sb_file_name", "sb_page_images", "sb_scalar_labels", "sb_table_info",
    "sb_selected", "sb_col_selected", "sb_type_map", "sb_required",
]

with tab_build:
    editing_schema = st.session_state.get("build_schema_data")
    is_editing = editing_schema is not None

    # ── Header ─────────────────────────────────────────────────────────────
    col_h, col_clear = st.columns([8, 2])
    with col_h:
        if is_editing:
            section_header(f"Editing: {editing_schema['name']}", f"v{editing_schema['version']}")
        else:
            section_header("Build Schema from Document")
    with col_clear:
        if st.button("➕ New Schema", key="clear_edit"):
            for k in _SB_KEYS + ["build_schema_id", "build_schema_data"]:
                st.session_state.pop(k, None)
            st.rerun()

    if not is_editing:
        callout(
            "Upload a sample document — the system scans it and lists every detected field label. "
            "Check the fields you want, pick their types, and save. "
            "No values from the sample are stored.",
            kind="tip",
        )

    # ── Document upload (top, full-width) ──────────────────────────────────
    build_doc = st.file_uploader(
        "Upload sample document to detect fields",
        type=ALLOWED_EXTENSIONS,
        key="build_doc_file",
        label_visibility="visible",
    )

    # Process new file
    if build_doc is not None:
        if st.session_state.get("sb_file_name") != build_doc.name:
            raw_bytes = build_doc.read()
            with st.spinner("Scanning document for field labels…"):
                imgs = _render_pdf_pages(raw_bytes)
                scalars, table_info = _detect_doc_labels(raw_bytes)
            st.session_state["sb_file_name"] = build_doc.name
            st.session_state["sb_page_images"] = imgs
            st.session_state["sb_scalar_labels"] = scalars
            st.session_state["sb_table_info"] = table_info
            st.session_state["sb_selected"] = {s["key"]: True for s in scalars}
            st.session_state["sb_col_selected"] = {c["key"]: True for c in table_info["columns"]}
            st.session_state["sb_type_map"] = {
                **{s["key"]: s["type_hint"] for s in scalars},
                **{c["key"]: c["type_hint"] for c in table_info["columns"]},
            }
            st.session_state["sb_required"] = {s["key"]: False for s in scalars}
            st.rerun()

    # ── Two-column layout ──────────────────────────────────────────────────
    has_doc = "sb_page_images" in st.session_state

    if has_doc:
        doc_col, cfg_col = st.columns([5, 7], gap="large")

        # ── LEFT: Document Preview ─────────────────────────────────────────
        with doc_col:
            pages = st.session_state["sb_page_images"]
            fname = st.session_state.get("sb_file_name", "")
            if pages:
                if len(pages) > 1:
                    page_idx = st.slider(
                        "Page", 1, len(pages), 1,
                        key="sb_page_slider",
                        label_visibility="collapsed",
                    ) - 1
                    st.caption(f"Page {page_idx + 1} of {len(pages)}  ·  {fname}")
                else:
                    page_idx = 0
                    st.caption(f"Page 1 of 1  ·  {fname}")
                st.image(pages[page_idx], use_container_width=True)
            else:
                st.info("Preview not available for this file type.")
                st.caption(f"File: {fname}")

        # ── RIGHT: Schema Configuration ────────────────────────────────────
        with cfg_col:

            # Schema metadata
            st.markdown(
                '<div style="color:#8b949e;font-size:.76rem;font-weight:600;'
                'text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px">'
                'Schema Info</div>',
                unsafe_allow_html=True,
            )
            col_sn, col_st = st.columns(2)
            with col_sn:
                schema_name = st.text_input(
                    "Schema name *",
                    value=editing_schema["name"] if is_editing else "",
                    placeholder="e.g. Commercial Invoice",
                    key="sb_schema_name",
                )
            with col_st:
                schema_doc_type = st.text_input(
                    "Document type *",
                    value=editing_schema["document_type"] if is_editing else "",
                    placeholder="e.g. commercial_invoice",
                    key="sb_schema_type",
                )

            st.markdown(
                '<div style="border-top:1px solid #30363d;margin:10px 0 12px 0"></div>',
                unsafe_allow_html=True,
            )

            # ── Scalar field checklist ─────────────────────────────────────
            scalars = st.session_state.get("sb_scalar_labels", [])
            table_info = st.session_state.get("sb_table_info", {"detected": False, "key": "line_items", "columns": []})
            sel = st.session_state.get("sb_selected", {})
            col_sel = st.session_state.get("sb_col_selected", {})
            type_map = st.session_state.get("sb_type_map", {})

            n_scalars = sum(1 for s in scalars if sel.get(s["key"], True))
            n_table_cols = sum(1 for c in table_info["columns"] if col_sel.get(c["key"], True)) if table_info["detected"] else 0

            st.markdown(
                f'<div style="color:#e8eaf0;font-size:.88rem;font-weight:700;margin-bottom:2px">'
                f'Detected Fields &nbsp;'
                f'<span style="color:#4ade80;font-size:.78rem;font-weight:400">'
                f'{n_scalars} header field(s) selected'
                + (f' &nbsp;·&nbsp; {n_table_cols} table column(s) selected' if table_info["detected"] else '')
                + f'</span></div>',
                unsafe_allow_html=True,
            )
            st.caption("Check the labels you want to extract · select type for each field")

            if scalars:
                # Column header row
                st.markdown(
                    '<div style="display:flex;align-items:center;gap:8px;'
                    'padding:4px 6px;border-bottom:1px solid #30363d;margin-bottom:2px">'
                    '<span style="width:24px"></span>'
                    '<span style="flex:1;color:#6e7681;font-size:.71rem;font-weight:600;text-transform:uppercase">Field Label</span>'
                    '<span style="width:130px;color:#6e7681;font-size:.71rem;font-weight:600;text-transform:uppercase">Type</span>'
                    '<span style="width:70px;color:#6e7681;font-size:.71rem;font-weight:600;text-transform:uppercase;text-align:center">Required</span>'
                    '</div>',
                    unsafe_allow_html=True,
                )

                for s in scalars:
                    c_chk, c_lbl, c_typ, c_req = st.columns([1, 5, 3, 2])
                    with c_chk:
                        checked = st.checkbox(
                            "include",
                            value=sel.get(s["key"], True),
                            key=f"sel_{s['key']}",
                            label_visibility="collapsed",
                        )
                        sel[s["key"]] = checked
                    with c_lbl:
                        lbl_color = "#e6edf3" if checked else "#484f58"
                        lbl_deco = "none" if checked else "line-through"
                        st.markdown(
                            f'<div style="color:{lbl_color};text-decoration:{lbl_deco};'
                            f'font-size:.83rem;padding-top:5px">{s["label"]}</div>',
                            unsafe_allow_html=True,
                        )
                    with c_typ:
                        if checked:
                            scalar_types = FIELD_TYPES[:5]  # exclude "table"
                            cur_type = type_map.get(s["key"], s["type_hint"])
                            idx = scalar_types.index(cur_type) if cur_type in scalar_types else 0
                            new_type = st.selectbox(
                                "type",
                                scalar_types,
                                index=idx,
                                key=f"type_{s['key']}",
                                label_visibility="collapsed",
                            )
                            type_map[s["key"]] = new_type
                        else:
                            st.empty()
                    with c_req:
                        if checked:
                            is_req = st.checkbox(
                                "req",
                                value=st.session_state.get("sb_required", {}).get(s["key"], False),
                                key=f"req_{s['key']}",
                                label_visibility="collapsed",
                            )
                            st.session_state.setdefault("sb_required", {})[s["key"]] = is_req
                        else:
                            st.empty()

            elif not table_info["detected"]:
                st.warning("No field labels detected. Try AI Propose for better results.")

            # ── Table field section ────────────────────────────────────────
            if table_info["detected"]:
                st.markdown(
                    '<div style="border-top:1px solid #30363d;margin:12px 0 10px 0"></div>',
                    unsafe_allow_html=True,
                )
                st.markdown(
                    '<div style="color:#8b949e;font-size:.76rem;font-weight:600;'
                    'text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px">'
                    'Repeating / Table Rows</div>',
                    unsafe_allow_html=True,
                )

                include_table = st.checkbox(
                    f"Include line-items table  ({len(table_info['columns'])} detected columns)",
                    value=st.session_state.get("sb_include_table", True),
                    key="sb_include_table",
                )

                if include_table:
                    t_col_key, t_col_lbl = st.columns([2, 4])
                    with t_col_key:
                        table_key_val = st.text_input(
                            "Table field key",
                            value=st.session_state.get("sb_table_key", "line_items"),
                            key="sb_table_key",
                        )
                    with t_col_lbl:
                        st.markdown(
                            '<div style="color:#6e7681;font-size:.78rem;padding-top:30px">'
                            'Select which columns to extract from each row:</div>',
                            unsafe_allow_html=True,
                        )

                    cols_list = table_info["columns"]
                    # Show columns in rows of 3
                    for i in range(0, len(cols_list), 3):
                        row_cells = st.columns(3)
                        for j, col_def in enumerate(cols_list[i:i + 3]):
                            with row_cells[j]:
                                c_checked = st.checkbox(
                                    col_def["label"],
                                    value=col_sel.get(col_def["key"], True),
                                    key=f"colsel_{col_def['key']}",
                                )
                                col_sel[col_def["key"]] = c_checked
                                if c_checked:
                                    col_types = ["string", "number", "currency", "date"]
                                    cur_ct = type_map.get(col_def["key"], col_def["type_hint"])
                                    ct_idx = col_types.index(cur_ct) if cur_ct in col_types else 0
                                    new_ct = st.selectbox(
                                        "col_type",
                                        col_types,
                                        index=ct_idx,
                                        key=f"coltype_{col_def['key']}",
                                        label_visibility="collapsed",
                                    )
                                    type_map[col_def["key"]] = new_ct

            # Persist state
            st.session_state["sb_selected"] = sel
            st.session_state["sb_col_selected"] = col_sel
            st.session_state["sb_type_map"] = type_map

            st.markdown(
                '<div style="border-top:1px solid #30363d;margin:14px 0 10px 0"></div>',
                unsafe_allow_html=True,
            )

            # ── Save / Activate ───────────────────────────────────────────
            def _build_fields_from_selection() -> list[dict]:
                scalars_l = st.session_state.get("sb_scalar_labels", [])
                sel_l = st.session_state.get("sb_selected", {})
                tinfo = st.session_state.get("sb_table_info", {"detected": False, "columns": []})
                col_sel_l = st.session_state.get("sb_col_selected", {})
                tmap = st.session_state.get("sb_type_map", {})
                req_l = st.session_state.get("sb_required", {})

                out: list[dict] = []
                for s in scalars_l:
                    if not sel_l.get(s["key"], True):
                        continue
                    out.append({
                        "json_key": s["key"],
                        "label": s["label"],
                        "field_type": tmap.get(s["key"], s["type_hint"]),
                        "required": req_l.get(s["key"], False),
                        "confidence_threshold": 0.80,
                        "hints": [],
                        "anchors": [],
                        "exclude_if_near": [],
                        "section": "header",
                        "description": "",
                        "position_preference": "",
                        "validation": "",
                        "table_columns": [],
                        "feedback_weight": 1.0,
                    })

                if tinfo.get("detected") and st.session_state.get("sb_include_table", True):
                    tkey = st.session_state.get("sb_table_key", "line_items")
                    sel_cols = [
                        {
                            "json_key": c["key"],
                            "label": c["label"],
                            "field_type": tmap.get(c["key"], c["type_hint"]),
                            "hints": [],
                        }
                        for c in tinfo["columns"]
                        if col_sel_l.get(c["key"], True)
                    ]
                    if sel_cols:
                        out.append({
                            "json_key": tkey,
                            "label": "Line Items",
                            "field_type": "table",
                            "required": False,
                            "confidence_threshold": 0.80,
                            "hints": [],
                            "anchors": [],
                            "exclude_if_near": [],
                            "section": "table",
                            "description": "Repeating line item rows",
                            "position_preference": "",
                            "validation": "",
                            "table_columns": sel_cols,
                            "feedback_weight": 1.0,
                        })
                return out

            col_save, col_activate = st.columns(2)
            with col_save:
                if st.button("💾 Save as Draft", type="primary", key="sb_save"):
                    sname = st.session_state.get("sb_schema_name", "").strip()
                    sdtype = st.session_state.get("sb_schema_type", "").strip()
                    if not sname:
                        st.error("Schema name is required.")
                    elif not sdtype:
                        st.error("Document type is required.")
                    else:
                        payload = {
                            "name": sname,
                            "document_type": sdtype,
                            "fields": _build_fields_from_selection(),
                        }
                        try:
                            if is_editing:
                                result = api.update_schema(editing_schema["id"], payload)
                                cached_api.invalidate_schemas()
                                st.success(f"Updated — now v{result['version']}.")
                                st.session_state["build_schema_data"] = result
                            else:
                                result = api.create_schema(payload)
                                cached_api.invalidate_schemas()
                                st.success(f"Schema created (ID: `{result['id']}`). Now draft.")
                                st.session_state["build_schema_id"] = result["id"]
                                st.session_state["build_schema_data"] = result
                        except Exception as e:
                            st.error(str(e))

            with col_activate:
                if is_editing and editing_schema.get("status") == "draft":
                    if st.button("▶️ Activate Schema", key="sb_activate"):
                        try:
                            result = api.activate_schema(editing_schema["id"])
                            cached_api.invalidate_schemas()
                            st.success(f"'{result['name']}' is now active!")
                            st.session_state["build_schema_data"] = result
                            st.rerun()
                        except Exception as e:
                            st.error(str(e))

    else:
        # No document uploaded yet
        if is_editing:
            callout(
                "Upload a document above to visually select fields, "
                "or switch to <strong>AI Propose</strong> to auto-generate the full schema.",
                kind="info",
            )
            # Show existing fields as editable table for editing without a document
            st.markdown("#### Current Fields")
            initial_fields = editing_schema.get("fields", [])
            if "proposed_fields" in st.session_state:
                initial_fields = st.session_state.pop("proposed_fields")
            fields_df = fields_to_df(initial_fields)
            edited_df = st.data_editor(
                fields_df,
                num_rows="dynamic",
                use_container_width=True,
                column_config={
                    "field_type": st.column_config.SelectboxColumn("Type", options=FIELD_TYPES),
                    "required": st.column_config.CheckboxColumn("Required"),
                    "confidence_threshold": st.column_config.NumberColumn(
                        "Confidence", min_value=0.0, max_value=1.0, step=0.05, format="%.2f"
                    ),
                },
                key="fields_editor_edit",
            )
            col_sn2, col_st2 = st.columns(2)
            with col_sn2:
                en_name = st.text_input("Schema name *", value=editing_schema["name"], key="en_name")
            with col_st2:
                en_type = st.text_input("Document type *", value=editing_schema["document_type"], key="en_type")
            col_sv2, col_ac2 = st.columns(2)
            with col_sv2:
                if st.button("💾 Save as Draft", type="primary", key="save_edit_nondoc"):
                    if not en_name.strip():
                        st.error("Schema name is required.")
                    else:
                        try:
                            result = api.update_schema(editing_schema["id"], {
                                "name": en_name.strip(),
                                "document_type": en_type.strip(),
                                "fields": df_to_fields(edited_df),
                            })
                            cached_api.invalidate_schemas()
                            st.success(f"Updated — now v{result['version']}.")
                            st.session_state["build_schema_data"] = result
                        except Exception as e:
                            st.error(str(e))
            with col_ac2:
                if editing_schema.get("status") == "draft":
                    if st.button("▶️ Activate Schema", key="activate_edit_nondoc"):
                        try:
                            result = api.activate_schema(editing_schema["id"])
                            cached_api.invalidate_schemas()
                            st.success(f"'{result['name']}' is now active!")
                            st.session_state["build_schema_data"] = result
                            st.rerun()
                        except Exception as e:
                            st.error(str(e))
        else:
            empty_state(
                "📄",
                "Upload a document to get started",
                "Upload a PDF or image above — the system will scan it and list all detected field labels. "
                "Check the ones you want and save your schema in seconds.",
            )

# ══════════════════════════════════════════════════════════════════════════════
# Tab 3 — AI Propose
# ══════════════════════════════════════════════════════════════════════════════

with tab_propose:
    section_header("AI Schema Proposal", "auto-generate fields from a sample document")
    callout(
        "Upload any document of the type you want to process. The AI will analyse its structure "
        "and propose a complete schema with field definitions, hints, and anchors. "
        "<strong>The sample file is discarded immediately</strong> — nothing is stored permanently.",
        kind="tip",
    )

    col_p1, col_p2 = st.columns(2)
    with col_p1:
        propose_file = st.file_uploader(
            "Sample document *",
            type=ALLOWED_EXTENSIONS,
            key="propose_file",
        )
    with col_p2:
        propose_doc_type = st.text_input(
            "Document type hint (optional)",
            placeholder="e.g. commercial_invoice",
            key="propose_doc_type",
        )

    if st.button("🤖 Propose Schema", disabled=propose_file is None, type="primary"):
        with st.spinner("Running OCR + AI analysis… this may take 15–30 seconds"):
            try:
                proposal = api.propose_schema(
                    file_bytes=propose_file.read(),
                    filename=propose_file.name,
                    document_type=propose_doc_type or "",
                )
                st.session_state["proposal_result"] = proposal
                st.success(
                    f"Proposed {proposal['field_count']} fields "
                    f"(detected type: {proposal.get('document_type_detected', '—')})"
                )
            except Exception as e:
                st.error(f"Proposal failed: {e}")

    if "proposal_result" in st.session_state:
        proposal = st.session_state["proposal_result"]
        st.markdown(f"#### Proposed Fields  —  `{proposal.get('document_type_detected', '')}`")

        proposal_df = fields_to_df(proposal.get("fields", []))
        edited_proposal_df = st.data_editor(
            proposal_df,
            num_rows="dynamic",
            use_container_width=True,
            column_config={
                "field_type": st.column_config.SelectboxColumn(
                    "Type", options=FIELD_TYPES
                ),
                "required": st.column_config.CheckboxColumn("Required"),
                "confidence_threshold": st.column_config.NumberColumn(
                    "Confidence", min_value=0.0, max_value=1.0, step=0.05, format="%.2f"
                ),
            },
            key="proposal_editor",
        )

        col_pname, col_ptype, col_psave = st.columns(3)
        with col_pname:
            p_name = st.text_input(
                "Schema name *",
                value=proposal.get("document_type_detected", "").replace("_", " ").title(),
                key="p_name",
            )
        with col_ptype:
            p_type = st.text_input(
                "Document type *",
                value=proposal.get("document_type_detected", ""),
                key="p_type",
            )
        with col_psave:
            st.write("")
            st.write("")
            if st.button("💾 Save as Draft", key="save_proposal", type="primary"):
                if not p_name.strip():
                    st.error("Name required.")
                elif not p_type.strip():
                    st.error("Document type required.")
                else:
                    try:
                        result = api.create_schema({
                            "name": p_name.strip(),
                            "document_type": p_type.strip(),
                            "fields": df_to_fields(edited_proposal_df),
                        })
                        cached_api.invalidate_schemas()
                        st.success(f"Saved as draft (ID: `{result['id']}`). Review in **Build / Edit**.")
                        st.session_state.pop("proposal_result", None)
                    except Exception as e:
                        st.error(str(e))

# ══════════════════════════════════════════════════════════════════════════════
# Tab 4 — Test
# ══════════════════════════════════════════════════════════════════════════════

with tab_test:
    section_header("Test Extraction", "run a live preview without storing any results")
    callout(
        "Choose any active schema, upload a test document, and preview what the AI extracts. "
        "<strong>No document is stored</strong> — this is purely a dry run to tune your schema.",
        kind="info",
    )
    st.markdown(
        "Upload a test document to see exactly what the AI would extract. "
        "**No document records or extraction values are stored.**"
    )

    col_ts, col_tf = st.columns(2)
    with col_ts:
        testable = {s["name"]: s["id"] for s in _all_schemas if s["status"] != "archived"}

        if not testable:
            st.warning("No schemas available.")
        else:
            test_schema_name = st.selectbox("Schema to test", list(testable.keys()), key="test_schema")
            test_schema_id = testable[test_schema_name]

    with col_tf:
        test_file = st.file_uploader(
            "Test document",
            type=ALLOWED_EXTENSIONS,
            key="test_file",
        )

    if testable and st.button(
        "🧪 Run Test Extraction",
        disabled=test_file is None,
        type="primary",
    ):
        with st.spinner("Running OCR + AI extraction…"):
            try:
                res = api.test_schema(
                    schema_id=test_schema_id,
                    file_bytes=test_file.read(),
                    filename=test_file.name,
                )
                st.session_state["test_result"] = res
            except Exception as e:
                status_code = getattr(e, "status_code", None)
                detail = getattr(e, "detail", str(e))
                if status_code == 429:
                    callout(
                        f"<strong>Rate limit reached.</strong> {detail}",
                        kind="warning",
                    )
                else:
                    st.error(f"Test failed: {detail}")

    if "test_result" in st.session_state:
        res = st.session_state["test_result"]

        col_m1, col_m2, col_m3, col_m4 = st.columns(4)
        col_m1.metric("Avg Confidence", f"{res.get('avg_confidence', 0):.0%}")
        col_m2.metric("Pages", res.get("page_count", "—"))
        col_m3.metric("Tables Detected", res.get("tables_detected", 0))
        col_m4.metric("Processing (ms)", res.get("processing_ms", "—"))

        st.markdown("#### Field Results")
        fields = res.get("fields", {})
        if not fields:
            empty_state("🔎", "No fields returned", "The test extraction produced no results.")
        else:
            from components import conf_pill, conf_bar
            # Header
            st.markdown(
                '<div style="display:flex;gap:10px;padding:4px 14px;font-size:.71rem;'
                'color:#6e7681;font-weight:600;text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px">'
                '<span style="flex:1.2">Field</span>'
                '<span style="flex:2">Value</span>'
                '<span style="flex:0.8">Confidence</span>'
                '<span style="flex:0.5">Missing</span>'
                '<span style="flex:0.5">Anchor</span>'
                '</div>',
                unsafe_allow_html=True,
            )
            for key, fdata in fields.items():
                val     = fdata.get("value")
                conf    = fdata.get("confidence")
                missing = fdata.get("missing", False)
                val_display = "(missing)" if missing else (str(val) if val is not None else "—")
                val_color   = "#8b949e" if missing else "#e6edf3"
                st.markdown(
                    f'<div class="idp-queue-row">'
                    f'<span style="flex:1.2;color:#e6edf3;font-weight:600;font-size:.86rem">{key}</span>'
                    f'<span style="flex:2;color:{val_color};font-size:.86rem">{val_display}</span>'
                    f'<span style="flex:0.8">{conf_pill(conf)}</span>'
                    f'<span style="flex:0.5;color:#8b949e;font-size:.8rem">{"Yes" if missing else "—"}</span>'
                    f'<span style="flex:0.5;color:#8b949e;font-size:.8rem">{"✓" if fdata.get("spatial_anchor") else "—"}</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

            # JSON download
            import json as _json
            st.markdown("<br>", unsafe_allow_html=True)
            st.download_button(
                "⬇️  Download Result as JSON",
                data=_json.dumps(res, indent=2, default=str).encode("utf-8"),
                file_name="idp_test_result.json",
                mime="application/json",
            )

        st.caption(res.get("note", ""))

# ══════════════════════════════════════════════════════════════════════════════
# Tab 5 — Version History
# ══════════════════════════════════════════════════════════════════════════════

with tab_history:
    section_header("Version History", "every field save creates a snapshot")
    callout(
        "Versions are automatically snapshotted every time you save field edits. "
        "Restoring a version creates a new version — your history is never lost.",
        kind="info",
    )

    schema_with_versions = {s["name"]: s["id"] for s in _all_schemas}

    if not schema_with_versions:
        empty_state("🔧", "No schemas yet", "Create a schema first to see version history.")
    else:
        hist_schema_name = st.selectbox(
            "Select schema",
            list(schema_with_versions.keys()),
            key="hist_schema",
        )
        hist_schema_id = schema_with_versions[hist_schema_name]

        try:
            versions_data = api.list_schema_versions(hist_schema_id)
        except Exception as e:
            st.error(str(e))
            versions_data = {}

        current_v = versions_data.get("current_version", "—")
        history = versions_data.get("versions", [])

        st.metric("Current version", current_v)

        if not history:
            empty_state("📄", "No snapshots yet", "Versions are saved every time you edit fields in Build / Edit.")
        else:
            section_header("Saved Snapshots")
            for v in history:
                with st.expander(
                    f"v{v['version']} — {v['field_count']} fields — {v['created_at'][:16]}"
                    + (f"  _{v['note']}_" if v.get("note") else ""),
                    expanded=False,
                ):
                    col_vi, col_vr = st.columns([4, 1])
                    with col_vi:
                        st.caption(f"Snapshot ID: `{v['id']}`")
                    with col_vr:
                        if st.button(
                            "⏪ Restore",
                            key=f"restore_{v['id']}",
                            help="Restore this version as a new version (non-destructive)",
                        ):
                            try:
                                result = api.restore_schema_version(hist_schema_id, v["version"])
                                cached_api.invalidate_schemas()
                                st.success(
                                    f"Restored v{v['version']} → now v{result['version']}."
                                )
                                st.rerun()
                            except Exception as e:
                                st.error(str(e))

# ══════════════════════════════════════════════════════════════════════════════
# Tab 6 — Feedback
# ══════════════════════════════════════════════════════════════════════════════

with tab_feedback:
    section_header("Feedback Loop", "improve schema accuracy from reviewer corrections")
    callout(
        "Every time a reviewer corrects a field value, that correction is recorded as feedback. "
        "Clicking <strong>Apply Feedback</strong> updates the schema\'s hints and confidence thresholds "
        "so the AI extracts more accurately next time — no manual editing required.",
        kind="info",
    )

    fb_schema_map = {s["name"]: s["id"] for s in _all_schemas if s["status"] == "active"}

    if not fb_schema_map:
        empty_state("🔄", "No active schemas", "Activate a schema first to see its feedback loop.")
    else:
        fb_schema_name = st.selectbox(
            "Active schema",
            list(fb_schema_map.keys()),
            key="fb_schema",
        )
        fb_schema_id = fb_schema_map[fb_schema_name]

        col_fb1, col_fb2 = st.columns(2)
        with col_fb1:
            show_applied = st.radio(
                "Show",
                ["Pending", "Applied", "All"],
                horizontal=True,
                key="fb_filter",
            )
        applied_filter = {"Pending": False, "Applied": True, "All": None}[show_applied]

        with col_fb2:
            st.write("")
            if st.button("⚡ Apply Pending Feedback", type="primary", key="apply_fb"):
                with st.spinner("Applying feedback to schema rules…"):
                    try:
                        result = api.apply_schema_feedback(fb_schema_id)
                        callout(
                            f"Applied <strong>{result.get('feedback_applied', 0)}</strong> corrections, "
                            f"updated <strong>{result.get('fields_updated', 0)}</strong> fields.",
                            kind="success",
                        )
                    except Exception as e:
                        st.error(str(e))

        try:
            fb_data = api.list_schema_feedback(fb_schema_id, applied=applied_filter)
        except Exception as e:
            st.error(str(e))
            fb_data = {}

        items = fb_data.get("items", [])
        count = fb_data.get("count", 0)
        st.caption(f"{count} feedback records")

        if items:
            st.dataframe(
                [
                    {
                        "Field": item.get("field_key", "—"),
                        "Action": item.get("action", "—"),
                        "Confidence": f"{item['confidence_at_feedback']:.0%}" if item.get("confidence_at_feedback") else "—",
                        "Applied": "✅" if item.get("applied_at") else "⏳ pending",
                        "Document": item.get("doc_id", "")[:8] + "…",
                        "Date": item.get("created_at", "")[:16],
                    }
                    for item in items
                ],
                use_container_width=True,
                hide_index=True,
            )
        else:
            empty_state("💬", "No feedback yet", "Feedback is recorded automatically when reviewers correct field values in the Documents page.")
