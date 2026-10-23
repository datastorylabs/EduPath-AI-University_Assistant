"""Per-user Streamlit state persistence with explicit sensitive-content exclusions."""
from __future__ import annotations

import math
from typing import Any, Mapping
from uuid import UUID

import streamlit as st
from sqlalchemy.orm import Session

from backend.app.database import SessionLocal
from backend.app.models.legacy_application_state import LegacyApplicationState
from backend.app.models.user import User
from backend.profile import default_profile
from backend.private_documents import read_private_document

_STRIP_KEYS = {"raw_text", "ocr_attempts", "text_preview", "file_bytes", "content_bytes", "original_bytes"}


def _json_safe(value: Any, *, strip_keys: set[str] | None = None, depth: int = 0) -> Any:
    """Convert only JSON-compatible, bounded structures and omit private raw content."""
    if depth > 12:
        return None
    strip = strip_keys or set()
    if value is None or isinstance(value, (str, bool, int)):
        return value if not isinstance(value, str) or len(value) <= 50_000 else value[:50_000]
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, bytes):
        return None
    if isinstance(value, (list, tuple)):
        return [_json_safe(item, strip_keys=strip, depth=depth + 1) for item in value[:500]]
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in list(value.items())[:500]:
            key_text = str(key)
            if key_text.casefold() in strip:
                continue
            result[key_text[:120]] = _json_safe(item, strip_keys=strip, depth=depth + 1)
        return result
    return None


def build_persistable_payload(state: Mapping[str, Any]) -> dict[str, Any]:
    """Keep structured profile/extraction/history but never original bytes or OCR text."""
    profile = _json_safe(state.get("student_profile") or default_profile(), strip_keys=_STRIP_KEYS)
    processed: dict[str, Any] = {}
    raw_processed = state.get("processed_documents") or {}
    if isinstance(raw_processed, dict):
        for key, entry in list(raw_processed.items())[:80]:
            safe_entry = _json_safe(entry, strip_keys=_STRIP_KEYS)
            if isinstance(safe_entry, dict) and isinstance(safe_entry.get("document_dict"), dict):
                safe_entry["document_dict"].pop("raw_text", None)
                safe_entry["document_dict"].pop("ocr_attempts", None)
            processed[str(key)[:200]] = safe_entry

    history: list[dict[str, Any]] = []
    for message in (state.get("chat_history") or [])[-100:]:
        if not isinstance(message, dict) or message.get("role") not in {"user", "assistant"}:
            continue
        content = message.get("content")
        if not isinstance(content, str):
            continue
        item = {"role": message["role"], "content": content[:10_000]}
        for key in ("engine", "model"):
            if isinstance(message.get(key), str):
                item[key] = message[key][:120]
        history.append(item)

    sources: list[list[str]] = []
    for entries in (state.get("chat_history_sources") or [])[-100:]:
        sources.append([str(s)[:500] for s in entries[:30] if isinstance(s, str)] if isinstance(entries, list) else [])

    stored_names: dict[str, list[str]] = {}
    uploads = state.get("category_uploads") or {}
    if isinstance(uploads, dict):
        for category, entries in uploads.items():
            names = []
            if isinstance(entries, list):
                for entry in entries:
                    if isinstance(entry, (tuple, list)) and entry and isinstance(entry[0], str):
                        names.append(entry[0][:255])
            if names:
                stored_names[str(category)[:100]] = names[:30]

    return {
        "student_profile": profile if isinstance(profile, dict) else default_profile(),
        "selected_university_id": state.get("selected_university_id"),
        "selected_program_id": state.get("selected_program_id"),
        "chat_history": history,
        "chat_history_sources": sources,
        "document_labels": _json_safe(state.get("document_labels") or {}),
        "other_document_labels": _json_safe(state.get("other_document_labels") or {}),
        "processed_documents": processed,
        "stored_document_metadata": stored_names,
        "private_uploads": _json_safe(state.get("private_uploads") or []),
        "profile_built": bool(state.get("profile_built", False)),
        "profile_source_fingerprint": state.get("profile_source_fingerprint"),
    }


def restore_application_state() -> None:
    """Restore an account's last snapshot once per Streamlit session."""
    raw_user_id = st.session_state.get("_edupath_user_id")
    if not raw_user_id:
        return
    user_id = UUID(str(raw_user_id))
    owner_key = str(user_id)
    if st.session_state.get("_edupath_loaded_user_id") == owner_key:
        return

    for key in list(st.session_state.keys()):
        if not str(key).startswith("_edupath_"):
            try:
                del st.session_state[key]
            except Exception:
                pass

    from backend.state import session_defaults
    st.session_state.update(session_defaults())
    st.session_state["category_uploads"] = {}
    st.session_state["private_uploads"] = []
    st.session_state["stored_document_metadata"] = {}
    with SessionLocal() as db:
        user = db.get(User, user_id)
        if user is None or not user.is_active:
            raise RuntimeError("The signed-in account is no longer active.")
        row = db.get(LegacyApplicationState, user_id)
        payload = row.payload if row is not None and isinstance(row.payload, dict) else {}
    profile = payload.get("student_profile")
    if isinstance(profile, dict):
        st.session_state["student_profile"] = _json_safe(profile)
    for key in ("selected_university_id", "selected_program_id"):
        value = payload.get(key)
        st.session_state[key] = value if isinstance(value, str) else None
    for key, default in (
        ("chat_history", []), ("chat_history_sources", []), ("document_labels", {}),
        ("other_document_labels", {}), ("processed_documents", {}),
        ("stored_document_metadata", {}), ("profile_built", False),
        ("profile_source_fingerprint", None),
    ):
        value = payload.get(key, default)
        st.session_state[key] = value if isinstance(value, type(default)) or default is None else default
    private_uploads = payload.get("private_uploads", [])
    restored_uploads: dict[str, list[tuple[str, bytes]]] = {}
    restored_metadata: list[dict[str, Any]] = []
    if isinstance(private_uploads, list):
        for item in private_uploads[:80]:
            if not isinstance(item, dict):
                continue
            category = item.get("category")
            filename = item.get("filename")
            storage_key = item.get("storage_key")
            fingerprint = item.get("fingerprint")
            if not all(isinstance(v, str) and v for v in (category, filename, storage_key, fingerprint)):
                continue
            try:
                content = read_private_document(user_id, storage_key)
            except (OSError, ValueError):
                content = None
            if content is None:
                continue
            restored_uploads.setdefault(category, []).append((filename, content))
            restored_metadata.append({
                "category": category, "filename": filename,
                "storage_key": storage_key, "fingerprint": fingerprint,
            })
    st.session_state["category_uploads"] = restored_uploads
    st.session_state["private_uploads"] = restored_metadata
    st.session_state["_edupath_loaded_user_id"] = owner_key


def persist_application_state() -> None:
    """Save the current signed-in account snapshot; never persist unauthenticated state."""
    raw_user_id = st.session_state.get("_edupath_user_id")
    if not raw_user_id:
        return
    try:
        user_id = UUID(str(raw_user_id))
        payload = build_persistable_payload(st.session_state)
        with SessionLocal() as db:
            user = db.get(User, user_id)
            if user is None or not user.is_active:
                return
            row = db.get(LegacyApplicationState, user_id)
            if row is None:
                row = LegacyApplicationState(user_id=user_id, payload=payload)
                db.add(row)
            else:
                row.payload = payload
            db.commit()
        st.session_state.pop("_edupath_storage_error", None)
    except Exception as exc:
        try:
            st.session_state["_edupath_storage_error"] = type(exc).__name__
        except Exception:
            pass
