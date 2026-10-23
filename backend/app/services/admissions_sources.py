"""Validate official admissions source metadata and flag stale records."""
from datetime import date
from urllib.parse import urlparse


def validate_source_record(record):
    errors = []
    for field in ("source_id", "university_id", "title", "url", "admission_cycle", "verification_status"):
        if not record.get(field):
            errors.append("missing:" + field)
    parsed = urlparse(str(record.get("url", "")))
    if parsed.scheme != "https" or not parsed.netloc:
        errors.append("url_must_be_https")
    allowed = {"verified", "partially_verified", "unverified", "stale", "conflicting"}
    if record.get("verification_status") not in allowed:
        errors.append("invalid_verification_status")
    if record.get("verification_status") == "verified" and not record.get("last_verified"):
        errors.append("verified_record_requires_last_verified")
    if record.get("last_verified"):
        try:
            date.fromisoformat(str(record["last_verified"]))
        except ValueError:
            errors.append("last_verified_must_be_iso_date")
    return errors


def is_stale(record, today=None, max_age_days=365):
    if record.get("verification_status") != "verified" or not record.get("last_verified"):
        return True
    try:
        verified = date.fromisoformat(str(record["last_verified"]))
    except ValueError:
        return True
    return ((today or date.today()) - verified).days > max_age_days
