"""Private academic-profile and conversation-history persistence endpoints."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.config import Settings, get_settings
from backend.app.database import get_db
from backend.app.models.conversation import Conversation, ConversationMessage
from backend.app.models.student_profile import StudentProfile
from backend.app.schemas.persistence import (
    ConversationCreateRequest,
    ConversationDetailResponse,
    ConversationMessageInput,
    ConversationMessageResponse,
    ConversationSummaryResponse,
    StudentProfileInput,
    StudentProfileResponse,
)
from backend.app.security import AuthenticatedContext, get_authenticated_context, require_authenticated_csrf
from backend.app.services.audit import record_security_event
from backend.app.services.conversations import append_message, find_owned_conversation

router = APIRouter(tags=["private data"])


def _private_response(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


@router.get("/profile/me", response_model=StudentProfileResponse, summary="Read the signed-in user's academic profile")
def get_my_profile(
    response: Response,
    context: AuthenticatedContext = Depends(get_authenticated_context),
    db: Session = Depends(get_db),
) -> StudentProfileResponse:
    _private_response(response)
    profile = db.get(StudentProfile, context.user.id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    return StudentProfileResponse.model_validate(profile)


@router.put(
    "/profile/me",
    response_model=StudentProfileResponse,
    summary="Create or replace the signed-in user's academic profile",
)
def put_my_profile(
    payload: StudentProfileInput,
    request: Request,
    response: Response,
    context: AuthenticatedContext = Depends(require_authenticated_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> StudentProfileResponse:
    _private_response(response)
    profile = db.get(StudentProfile, context.user.id)
    values = payload.model_dump()
    if profile is None:
        profile = StudentProfile(user_id=context.user.id, **values)
        db.add(profile)
    else:
        for key, value in values.items():
            setattr(profile, key, value)
    record_security_event(db, request, settings, "profile.updated", user_id=context.user.id)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Profile could not be saved; retry the request.") from None
    db.refresh(profile)
    return StudentProfileResponse.model_validate(profile)


@router.delete("/profile/me", status_code=204, summary="Permanently delete the signed-in user's academic profile")
def delete_my_profile(
    request: Request,
    context: AuthenticatedContext = Depends(require_authenticated_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    profile = db.get(StudentProfile, context.user.id)
    if profile is not None:
        db.delete(profile)
    record_security_event(db, request, settings, "profile.deleted", user_id=context.user.id)
    db.commit()
    return Response(status_code=204, headers={"Cache-Control": "no-store"})


@router.post(
    "/conversations",
    response_model=ConversationSummaryResponse,
    status_code=201,
    summary="Create a private conversation",
)
def create_conversation(
    payload: ConversationCreateRequest,
    request: Request,
    response: Response,
    context: AuthenticatedContext = Depends(require_authenticated_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ConversationSummaryResponse:
    _private_response(response)
    conversation = Conversation(user_id=context.user.id, title=payload.title)
    db.add(conversation)
    record_security_event(db, request, settings, "conversation.created", user_id=context.user.id)
    db.commit()
    db.refresh(conversation)
    return ConversationSummaryResponse.model_validate(conversation)


@router.get("/conversations", response_model=list[ConversationSummaryResponse], summary="List the signed-in user's conversations")
def list_conversations(
    response: Response,
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0, le=10000),
    context: AuthenticatedContext = Depends(get_authenticated_context),
    db: Session = Depends(get_db),
) -> list[ConversationSummaryResponse]:
    _private_response(response)
    rows = db.scalars(
        select(Conversation)
        .where(Conversation.user_id == context.user.id)
        .order_by(Conversation.updated_at.desc(), Conversation.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return [ConversationSummaryResponse.model_validate(row) for row in rows]


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationDetailResponse,
    summary="Read one owned conversation with message history",
)
def get_conversation(
    conversation_id: UUID,
    response: Response,
    context: AuthenticatedContext = Depends(get_authenticated_context),
    db: Session = Depends(get_db),
) -> ConversationDetailResponse:
    _private_response(response)
    conversation = find_owned_conversation(db, conversation_id, context.user.id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    messages = db.scalars(
        select(ConversationMessage)
        .where(ConversationMessage.conversation_id == conversation.id)
        .order_by(ConversationMessage.created_at, ConversationMessage.id)
    ).all()
    return ConversationDetailResponse(
        id=conversation.id,
        title=conversation.title,
        is_archived=conversation.is_archived,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        messages=[ConversationMessageResponse.model_validate(message) for message in messages],
    )


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=ConversationMessageResponse,
    status_code=201,
    summary="Persist a user's message in an owned conversation",
)
def add_user_message(
    conversation_id: UUID,
    payload: ConversationMessageInput,
    request: Request,
    response: Response,
    context: AuthenticatedContext = Depends(require_authenticated_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ConversationMessageResponse:
    _private_response(response)
    conversation = find_owned_conversation(db, conversation_id, context.user.id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    message = append_message(db, conversation, "user", payload.content)
    conversation.updated_at = datetime.now(timezone.utc)
    record_security_event(db, request, settings, "conversation.message_added", user_id=context.user.id)
    db.commit()
    db.refresh(message)
    return ConversationMessageResponse.model_validate(message)


@router.delete(
    "/conversations/{conversation_id}",
    status_code=204,
    summary="Permanently delete an owned conversation and its messages",
)
def delete_conversation(
    conversation_id: UUID,
    request: Request,
    context: AuthenticatedContext = Depends(require_authenticated_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    conversation = find_owned_conversation(db, conversation_id, context.user.id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    db.delete(conversation)
    record_security_event(db, request, settings, "conversation.deleted", user_id=context.user.id)
    db.commit()
    return Response(status_code=204, headers={"Cache-Control": "no-store"})
