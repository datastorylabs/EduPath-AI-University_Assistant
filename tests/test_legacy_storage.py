from __future__ import annotations

from backend.legacy_storage import build_persistable_payload


def test_persistable_snapshot_keeps_fields_but_drops_raw_ocr_and_upload_bytes() -> None:
    state = {
        "student_profile": {
            "qualification": "ICS",
            "aggregate": 83.5,
            "document_records": [{"filename": "marksheet.png", "status": "extracted", "raw_text": "SECRET_RECORD_TEXT"}],
            "raw_text": "SECRET_RAW_TEXT",
        },
        "processed_documents": {
            "key": {
                "filename": "marksheet.png",
                "document_dict": {
                    "filename": "marksheet.png",
                    "raw_text": "SECRET_OCR_BODY",
                    "ocr_attempts": [{"text_preview": "SECRET_PREVIEW"}],
                    "fields": [{"field": "aggregate", "value": 83.5}],
                },
                "upload_bytes": b"PRIVATE_BYTES",
            }
        },
        "category_uploads": {"intermediate_transcript": [("marksheet.png", b"PRIVATE_FILE_BYTES")]},
        "chat_history": [{"role": "user", "content": "What does my result mean?"}],
        "chat_history_sources": [[]],
        "selected_university_id": "nust",
        "selected_program_id": "bs-cs",
    }
    payload = build_persistable_payload(state)
    serialized = repr(payload)
    for private_value in ("SECRET_RAW_TEXT", "SECRET_RECORD_TEXT", "SECRET_OCR_BODY", "SECRET_PREVIEW", "PRIVATE_BYTES", "PRIVATE_FILE_BYTES"):
        assert private_value not in serialized
    assert payload["student_profile"]["qualification"] == "ICS"
    assert payload["student_profile"]["aggregate"] == 83.5
    assert payload["processed_documents"]["key"]["document_dict"]["fields"][0]["value"] == 83.5
    assert payload["chat_history"][0]["content"] == "What does my result mean?"
    assert payload["stored_document_metadata"]["intermediate_transcript"] == ["marksheet.png"]


def test_snapshot_preserves_private_upload_reference_but_not_file_bytes() -> None:
    state = {
        "student_profile": {"qualification": "ICS"},
        "category_uploads": {"intermediate_transcript": [("marksheet.pdf", b"PRIVATE_FILE_BYTES")]},
        "private_uploads": [{
            "category": "intermediate_transcript",
            "filename": "marksheet.pdf",
            "fingerprint": "a" * 64,
            "storage_key": "b" * 32 + ".pdf",
        }],
    }
    payload = build_persistable_payload(state)
    assert payload["private_uploads"][0]["filename"] == "marksheet.pdf"
    assert payload["private_uploads"][0]["storage_key"] == "b" * 32 + ".pdf"
    assert "PRIVATE_FILE_BYTES" not in repr(payload)
