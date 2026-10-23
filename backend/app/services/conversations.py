"""Small persistence helpers shared by the API and the future advisor integration."""
from __future__ import annotations

from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.conversation import Conversation, ConversationMessage


def find_owned_conversation(db: Session, conversation_id: UUID, user_id: UUID) -> Conversation | None:
    """Scope the lookup to its owner so foreign IDs always behave as not found."""
    return db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
        )
    )


def append_message(
    db: Session,
    conversation: Conversation,
    role: Literal["user", "assistant"],
    content: str,
    citations: list[dict[str, str]] | None = None,
) -> ConversationMessage:
    """Queue a validated message; caller owns commit/rollback for transaction boundaries."""
    message = ConversationMessage(
        conversation_id=conversation.id,
        role=role,
        content=content,
        citations=citations or [],
    )
    db.add(message)
    return message
