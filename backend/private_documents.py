"""Private per-account storage for uploaded admission documents."""
from __future__ import annotations

import os
import re
import shutil
import uuid
from pathlib import Path
from uuid import UUID

from backend.documents.validation import validate_upload

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PRIVATE_STORAGE_ROOT = Path(
    os.environ.get("EDUPATH_PRIVATE_STORAGE_DIR", str(_REPOSITORY_ROOT / "data" / "private_uploads"))
).expanduser().resolve()
_ALLOWED_SUFFIXES = {".txt", ".md", ".csv", ".pdf", ".png", ".jpg", ".jpeg"}
_STORAGE_KEY_RE = re.compile(r"^[0-9a-f]{32}\.(?:txt|md|csv|pdf|png|jpg|jpeg)$")


def _user_directory(user_id: str | UUID) -> Path:
    owner = str(UUID(str(user_id)))
    root = PRIVATE_STORAGE_ROOT.resolve()
    directory = (root / owner).resolve()
    if root not in directory.parents:
        raise ValueError("Invalid private storage owner.")
    return directory


def _safe_file_path(user_id: str | UUID, storage_key: str) -> Path:
    if not isinstance(storage_key, str) or not _STORAGE_KEY_RE.fullmatch(storage_key):
        raise ValueError("Invalid private document key.")
    directory = _user_directory(user_id)
    path = (directory / storage_key).resolve()
    if path.parent != directory:
        raise ValueError("Invalid private document path.")
    return path


def save_private_document(user_id: str | UUID, filename: str, content: bytes) -> str:
    """Validate and atomically save an upload under a random name."""
    validation = validate_upload(filename, content)
    if not validation.valid:
        raise ValueError("Upload validation failed: " + "; ".join(validation.errors))
    suffix = Path(filename).suffix.lower()
    if suffix not in _ALLOWED_SUFFIXES:
        raise ValueError("Unsupported document type.")
    directory = _user_directory(user_id)
    directory.mkdir(parents=True, exist_ok=True)
    key = f"{uuid.uuid4().hex}{suffix}"
    target = _safe_file_path(user_id, key)
    temporary = target.with_name(target.name + ".tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
    return key


def read_private_document(user_id: str | UUID, storage_key: str) -> bytes | None:
    """Read a private document by owner and opaque key, never an arbitrary path."""
    path = _safe_file_path(user_id, storage_key)
    return path.read_bytes() if path.is_file() else None


def delete_private_document(user_id: str | UUID, storage_key: str) -> None:
    """Delete one owner-scoped document if it exists."""
    _safe_file_path(user_id, storage_key).unlink(missing_ok=True)


def delete_user_private_documents(user_id: str | UUID) -> None:
    """Remove the account's private upload directory during account deletion."""
    directory = _user_directory(user_id)
    if directory.exists():
        shutil.rmtree(directory)
