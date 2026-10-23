"""STEP 1: Upload academic documents via category-based slots.

Architecture:
    Upload time:  file → bytes → SHA-256 → check cache → if new: process_upload() → store
    Build Profile: already-processed ExtractedDocuments → merge_documents() → profile update
"""
from __future__ import annotations

import time as _time

import streamlit as st

from backend.documents.categories import (
    UPLOAD_CATEGORIES,
    UPLOAD_GROUPS,
)
from backend.documents import (
    DocumentCache,
    fingerprint,
    process_uploads_cached,
)
from backend.documents.cache import CacheStats
from backend.state import (
    build_profile_from_processed,
    composite_fingerprint,
    get_profile,
    update_profile,
)
from ui import init_session_state, inject_theme, nav_row, page_header, render_sidebar

st.set_page_config(page_title="Upload Documents | EduPath AI", page_icon="📄", layout="wide")
init_session_state()
inject_theme()
render_sidebar()

page_header(
    "Upload Documents",
    "Upload your documents into the correct category below. Your selection is authoritative — the system uses it to route extraction and eligibility checks.",
    "📄",
)

feedback = st.session_state.pop("_upload_feedback", None)
if feedback:
    st.success(feedback)

if "category_uploads" not in st.session_state:
    st.session_state["category_uploads"] = {}

category_uploads: dict = st.session_state["category_uploads"]

if "_doc_cache_store" not in st.session_state:
    st.session_state["_doc_cache_store"] = {}
doc_cache = DocumentCache(st.session_state["_doc_cache_store"])

processed: dict[str, dict] = st.session_state.setdefault("processed_documents", {})
if "other_document_labels" not in st.session_state:
    st.session_state["other_document_labels"] = {}
other_labels: dict[str, str] = st.session_state["other_document_labels"]

ALLOWED_TYPES = ["txt", "md", "pdf", "png", "jpg", "jpeg"]

_GROUP_ICONS = {
    "Academic": "🎓",
    "Admission Test": "📝",
    "Identity & Residence": "🪪",
    "Other": "📎",
}


def _process_new_uploads(cat_key: str, files_list: list) -> list[str]:
    """Process newly uploaded files immediately and store in processed_documents.

    Returns a list of status messages for each file processed.
    The spinner covers the ENTIRE operation: OCR/extraction + state commit.
    """
    from backend.documents.pipeline import process_upload

    messages: list[str] = []
    for f in files_list:
        content = f.getvalue()
        fp = fingerprint(content)
        cache_key = f"{fp}:{cat_key}"

        if cache_key in processed:
            messages.append(f"`{f.name}` already processed — skipped.")
            continue

        with st.spinner(f"Processing {f.name}..."):
            t0 = _time.perf_counter()
            doc = process_upload(f.name, content, user_category=cat_key)
            elapsed_ms = round((_time.perf_counter() - t0) * 1000, 2)

            processed[cache_key] = {
                "document_dict": doc.to_dict(),
                "processing_ms": elapsed_ms,
                "category": cat_key,
                "filename": f.name,
                "fingerprint": fp,
            }

            doc_cache.put(content, cat_key, doc, elapsed_ms)

        messages.append(f"✅ `{f.name}` processed successfully ({elapsed_ms:.0f}ms).")

    return messages


for group_name, category_keys in UPLOAD_GROUPS.items():
    icon = _GROUP_ICONS.get(group_name, "📁")
    st.markdown(f"### {icon} {group_name}")
    cols = st.columns(len(category_keys))

    for col_idx, cat_key in enumerate(category_keys):
        meta = UPLOAD_CATEGORIES[cat_key]
        label = meta["label"]
        allows_multiple = meta["allows_multiple"]

        with cols[col_idx]:
            with st.container(border=True):
                st.markdown(f"**{label}**")
                if allows_multiple:
                    st.caption("You can upload multiple files.")
                else:
                    st.caption("Single document — re-uploading replaces the previous one.")

                existing = category_uploads.get(cat_key)
                if existing:
                    filenames = [str(f[0])[:255] for f in existing]
                    st.caption("Currently uploaded: " + ", ".join(filenames))
                else:
                    previous_names = st.session_state.get("stored_document_metadata", {}).get(cat_key, [])
                    if previous_names:
                        st.caption("Previously analyzed (original files are not retained): " + ", ".join(str(n)[:255] for n in previous_names))

                uploaded = st.file_uploader(
                    "Upload",
                    type=ALLOWED_TYPES,
                    accept_multiple_files=allows_multiple,
                    key=f"upload_{cat_key}",
                    label_visibility="collapsed",
                )

                if uploaded:
                    files_list = uploaded if isinstance(uploaded, list) else [uploaded]
                    new_files = []
                    for f in files_list:
                        new_files.append((f.name, f.getvalue()))

                    existing_names = {f[0] for f in existing} if existing else set()
                    new_names = {f[0] for f in new_files}

                    if new_names.issubset(existing_names):
                        pass  # Already uploaded and processed — no state change, no rerun
                    else:
                        if allows_multiple:
                            if existing:
                                for item in new_files:
                                    if item[0] not in existing_names:
                                        existing.append(item)
                            else:
                                category_uploads[cat_key] = new_files
                        else:
                            for fname, fbytes in (existing or []):
                                old_fp = fingerprint(fbytes)
                                old_key = f"{old_fp}:{cat_key}"
                                processed.pop(old_key, None)
                                doc_cache.invalidate(fbytes, cat_key)
                            category_uploads[cat_key] = new_files[-1:]

                        _process_new_uploads(cat_key, files_list)
                        st.rerun()

                if existing:
                    if st.button("Remove", key=f"remove_{cat_key}"):
                        for fname, fbytes in category_uploads[cat_key]:
                            fp = fingerprint(fbytes)
                            cache_key = f"{fp}:{cat_key}"
                            processed.pop(cache_key, None)
                            doc_cache.invalidate(fbytes, cat_key)
                        del category_uploads[cat_key]
                        st.rerun()

    st.markdown("")

total_uploads = sum(len(v) for v in category_uploads.values())

if processed:
    st.divider()
    st.markdown("### 📋 Processed Documents")

    for cache_key, entry in processed.items():
        doc_dict = entry["document_dict"]
        doc_filename = entry.get("filename", doc_dict.get("filename", "?"))
        cat_key = entry.get("category", "other")
        cat_label = UPLOAD_CATEGORIES.get(cat_key, {}).get("label", cat_key)
        processing_ms = entry.get("processing_ms", 0)

        validation = doc_dict.get("validation", {})
        warnings = validation.get("warnings", [])
        errors = validation.get("errors", [])

        method = doc_dict.get("extraction_method", "error")
        if method in {"text", "pdf_text"}:
            method_badge = "Text extracted"
        elif method in {"image_ocr", "pdf_ocr", "pdf_hybrid"}:
            method_badge = "OCR used"
        elif method == "placeholder":
            method_badge = "File not parsed"
        else:
            method_badge = "OCR could not read this document"

        status_icon = "❌" if errors else "⚠️" if warnings else "✅"

        with st.expander(f"{status_icon} {doc_filename} — {cat_label} ({method_badge}) [{processing_ms:.0f}ms]"):
            if errors:
                for err in errors:
                    st.error(err)
            if warnings:
                for warn in warnings:
                    st.warning(warn)

            fields_list = doc_dict.get("fields", [])
            if fields_list:
                st.markdown("**Extracted Fields:**")
                for f in fields_list:
                    fname = f.get("field", "?")
                    fval = f.get("value", "—")
                    st.text(f"  {fname}: {fval}")

            raw_text = doc_dict.get("raw_text", "")
            if doc_dict.get("ocr_note"):
                st.info(doc_dict["ocr_note"])

            if cat_key == "other":
                current_label = other_labels.get(cache_key, doc_dict.get("document_label", ""))
                new_label = st.text_input(
                    "Document label (e.g., Character Certificate, PRC)",
                    value=current_label,
                    key=f"label_{cache_key}",
                    help="Give this document a meaningful name so it can be recognized by eligibility checks.",
                )
                new_label = (new_label or "").strip()
                current_label = (current_label or "").strip()
                if new_label != current_label:
                    other_labels[cache_key] = new_label
                    doc_dict["document_label"] = new_label

            if method in {"image_ocr", "pdf_ocr", "pdf_hybrid", "pdf_text"}:
                with st.expander("Debug: OCR Diagnostics & Raw Text"):
                    attempts = doc_dict.get("ocr_attempts", [])
                    if attempts:
                        attempt_rows = []
                        for a in attempts:
                            attempt_rows.append({
                                "Variant": a.get("variant", "?"),
                                "PSM": a.get("psm", "?"),
                                "Confidence": f"{a.get('confidence', 0):.0f}%",
                                "Chars": a.get("chars", 0),
                                "Words": a.get("words", 0),
                            })
                        st.table(attempt_rows)

                    if raw_text:
                        st.markdown("**Raw Extracted OCR Text**")
                        st.code(raw_text, language=None)

st.divider()
st.markdown("### 📤 Build Profile")

if not processed:
    st.info("Upload and process at least one document above, then build your profile here.")
elif st.button("Build Profile from Documents", type="primary", key="build_profile"):
    profile_data = build_profile_from_processed(processed)
    if profile_data is None:
        st.warning("Could not build profile from processed documents.")
    else:
        update_profile(profile_data, source="ocr")

        parsed = [entry["document_dict"] for entry in processed.values()]
        st.session_state["parsed_docs"] = parsed
        st.session_state["profile_built"] = True
        st.session_state["profile_source_fingerprint"] = composite_fingerprint(processed)

        st.session_state["_upload_feedback"] = "Profile created. Review and edit it on the next page."
        st.rerun()

if processed:
    if st.button("Go to Profile →", key="go_to_profile"):
        st.switch_page("pages/2_Profile.py")

st.divider()

page_header("Or Enter Details Manually", "No documents? Fill in your academic information directly.", "✍️")

profile = get_profile()

with st.container(border=True):
    with st.form("manual_profile_form"):
        col1, col2 = st.columns(2)
        name = col1.text_input("Full Name", value=profile.get("name", ""))
        qualification_options = ["FSc Pre-Engineering", "ICS", "A-Levels", "FA", "FSc", "Other"]
        qualification = col2.selectbox(
            "Qualification",
            qualification_options,
            index=qualification_options.index(profile.get("qualification")) if profile.get("qualification") in qualification_options else 0,
        )
        board_options = ["FBISE Islamabad", "BISE Lahore", "BISE Karachi", "BISE Rawalpindi", "Other"]
        board = col1.selectbox(
            "Board / Examination Authority",
            board_options,
            index=board_options.index(profile.get("board")) if profile.get("board") in board_options else 0,
        )
        aggregate = col2.number_input(
            "Aggregate / Percentage (%)",
            min_value=0.0,
            max_value=100.0,
            value=float(profile.get("aggregate") or 0.0),
            step=0.1,
        )

        submitted = st.form_submit_button("Save Profile", type="primary")
        if submitted:
            updated = {
                "name": name,
                "qualification": qualification,
                "board": board,
                "aggregate": aggregate,
            }
            update_profile(updated, source="manual")
            st.session_state["_upload_feedback"] = "Profile saved."
            st.rerun()

nav_row(next_page="pages/2_Profile.py", next_label="Next: Review Profile →")
