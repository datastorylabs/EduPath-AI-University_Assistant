from __future__ import annotations

from backend.documents import ocr


def test_tesseract_command_expands_quotes_and_user_path(monkeypatch) -> None:
    monkeypatch.setenv("TESSERACT_CMD", '"~/tools/tesseract.exe"')
    monkeypatch.setattr(ocr.os.path, "isfile", lambda path: path.endswith("tools/tesseract.exe"))
    monkeypatch.setattr(ocr.shutil, "which", lambda _name: None)
    result = ocr._find_tesseract()
    assert result is not None
    assert result.endswith("tools/tesseract.exe")


def test_direct_ocr_rejects_oversized_image_bytes() -> None:
    result = ocr.extract_image_ocr(b"x" * (ocr.MAX_IMAGE_BYTES + 1))
    assert result.status == "error"
    assert "10 MB" in (result.message or "")
