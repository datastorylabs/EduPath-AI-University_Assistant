"""Request and response schemas for private persisted user data."""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StudentProfileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    qualification: str | None = Field(default=None, max_length=120)
    ssc_percent: float | None = Field(default=None, ge=0, le=100)
    hssc_percent: float | None = Field(default=None, ge=0, le=100)
    subjects: list[str] = Field(default_factory=list, max_length=32)
    subject_percentages: dict[str, float] = Field(default_factory=dict, max_length=32)
    equivalency_status: Literal["confirmed", "pending", "not_required", "not_applicable", "unknown"] | None = None

    @field_validator("qualification")
    @classmethod
    def clean_qualification(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("subjects")
    @classmethod
    def clean_subjects(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for value in values:
            subject = value.strip()
            if not subject or len(subject) > 80:
                raise ValueError("Subjects must be non-empty and at most 80 characters.")
            key = subject.casefold()
            if key not in seen:
                seen.add(key)
                cleaned.append(subject)
        return cleaned

    @field_validator("subject_percentages")
    @classmethod
    def clean_subject_percentages(cls, values: dict[str, float]) -> dict[str, float]:
        cleaned: dict[str, float] = {}
        for key, value in values.items():
            subject = key.strip()
            if not subject or len(subject) > 80 or not 0 <= value <= 100:
                raise ValueError("Subject percentages must have a valid subject name and be between 0 and 100.")
            cleaned[subject] = value
        return cleaned


class StudentProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    qualification: str | None
    ssc_percent: float | None
    hssc_percent: float | None
    subjects: list[str]
    subject_percentages: dict[str, float]
    equivalency_status: str | None
    created_at: datetime
    updated_at: datetime


class ConversationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(default="New conversation", min_length=1, max_length=180)

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Conversation title cannot be empty.")
        return value


class ConversationMessageInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=20000)

    @field_validator("content")
    @classmethod
    def clean_content(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Message content cannot be empty.")
        return value


class ConversationSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    is_archived: bool
    created_at: datetime
    updated_at: datetime


class ConversationMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    role: Literal["user", "assistant"]
    content: str
    citations: list[dict[str, str]]
    created_at: datetime


class ConversationDetailResponse(ConversationSummaryResponse):
    messages: list[ConversationMessageResponse]


class AdvisorProgramCheckRequest(BaseModel):
    """Select a supported deterministic advisor workflow; raw text is never sent to an LLM."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["find_matches", "show_gaps"] = "find_matches"


class AdvisorProgramCheckResponse(BaseModel):
    """A saved, citation-carrying profile check for the signed-in user."""

    user_message: ConversationMessageResponse
    assistant_message: ConversationMessageResponse
    summary: str
    notice: str
    total_rules: int
    eligible_count: int
    conditional_count: int
    ineligible_count: int
    indeterminate_count: int
    results: list[dict[str, object]]
