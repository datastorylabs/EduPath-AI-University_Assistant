"""Private, user-owned academic profile storage."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, JSON, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.models.base import Base


class StudentProfile(Base):
    """One optional academic profile per account; no uploaded document bytes are stored here."""

    __tablename__ = "student_profiles"
    __table_args__ = (
        CheckConstraint("ssc_percent IS NULL OR (ssc_percent >= 0 AND ssc_percent <= 100)", name="ssc_percent_range"),
        CheckConstraint("hssc_percent IS NULL OR (hssc_percent >= 0 AND hssc_percent <= 100)", name="hssc_percent_range"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    qualification: Mapped[str | None] = mapped_column(String(120), nullable=True)
    ssc_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    hssc_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    subjects: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    subject_percentages: Mapped[dict[str, float]] = mapped_column(JSON, nullable=False, default=dict)
    equivalency_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
