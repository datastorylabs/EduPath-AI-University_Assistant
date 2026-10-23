from __future__ import annotations

import os
from pathlib import Path
import stat
from uuid import uuid4

import pytest

from backend import private_documents as storage


def test_private_upload_round_trip_and_account_cleanup(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(storage, "PRIVATE_STORAGE_ROOT", tmp_path / "private")
    user_id = uuid4()
    content = b"%PDF-1.7\nprivate academic record"
    key = storage.save_private_document(user_id, "../../marksheet.pdf", content)

    assert "/" not in key and "\\" not in key
    assert storage.read_private_document(user_id, key) == content
    user_dir = tmp_path / "private" / str(user_id)
    assert user_dir.is_dir()
    assert len(list(user_dir.iterdir())) == 1

    storage.delete_user_private_documents(user_id)
    assert not user_dir.exists()


def test_private_storage_rejects_path_traversal_and_invalid_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(storage, "PRIVATE_STORAGE_ROOT", tmp_path / "private")
    user_id = uuid4()
    with pytest.raises(ValueError):
        storage.read_private_document(user_id, "../other-user.pdf")
    with pytest.raises(ValueError):
        storage.save_private_document(user_id, "marksheet.pdf", b"not a pdf")
    assert not (tmp_path / "private").exists()



@pytest.mark.skipif(os.name == "nt", reason="POSIX file-mode assertions do not apply on Windows")
def test_private_uploads_use_owner_only_files_and_directories(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(storage, "PRIVATE_STORAGE_ROOT", tmp_path / "private")
    user_id = uuid4()
    key = storage.save_private_document(user_id, "marksheet.pdf", b"%PDF-1.7\nprivate academic record")
    file_path = storage._safe_file_path(user_id, key)
    user_directory = file_path.parent
    storage_root = user_directory.parent

    assert stat.S_IMODE(storage_root.stat().st_mode) & 0o077 == 0
    assert stat.S_IMODE(user_directory.stat().st_mode) & 0o077 == 0
    assert stat.S_IMODE(file_path.stat().st_mode) & 0o077 == 0
