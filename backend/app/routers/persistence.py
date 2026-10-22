"""Private academic-profile and conversation-history persistence endpoints."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.config import Settings, get_settings
from backend.app.database import get_db
from backend.app.models.conversation import Conversation, ConversationMessage
from backend.app.models.student_profile import StudentProfile
from backend.app.persistence_schemas import (
    AdvisorProgramCheckRequest,
    AdvisorProgramCheckResponse,
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
from backend.app.services.admissions_catalog import list_available_rules, list_universities
from backend.app.services.admissions_rules import evaluate_eligibility

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

@router.post(
    "/conversations/{conversation_id}/program-check",
    response_model=AdvisorProgramCheckResponse,
    summary="Run and save a deterministic profile-based program check",
)
def run_profile_program_check(
    conversation_id: UUID,
    payload: AdvisorProgramCheckRequest,
    request: Request,
    response: Response,
    context: AuthenticatedContext = Depends(require_authenticated_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AdvisorProgramCheckResponse:
    """Evaluate saved profile data only against source-verified, current rules.

    This workflow is deliberately deterministic. The selected mode is a fixed enum,
    and neither profile data nor user content is inserted into an LLM prompt.
    """
    _private_response(response)
    conversation = find_owned_conversation(db, conversation_id, context.user.id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    profile_record = db.get(StudentProfile, context.user.id)
    if profile_record is None:
        raise HTTPException(status_code=409, detail="Save your academic profile before running a program check.")

    profile = {
        "qualification": profile_record.qualification,
        "ssc_percent": profile_record.ssc_percent,
        "hssc_percent": profile_record.hssc_percent,
        "subjects": profile_record.subjects or [],
        "subject_percentages": profile_record.subject_percentages or {},
        "equivalency_status": profile_record.equivalency_status,
    }
    available_rules = [
        rule for rule in list_available_rules()
        if rule.get("evaluation_available") is True
        and rule.get("program_family") == "computing"
    ]
    university_names = {
        item["university_id"]: item["university_name"]
        for item in list_universities()
    }

    results: list[dict[str, object]] = []
    citation_map: dict[str, dict[str, str]] = {}
    for rule in available_rules:
        evaluated_profile = {**profile, "cycle": str(rule["cycle"])}
        result = evaluate_eligibility(evaluated_profile, rule).to_dict()
        sources = [
            {
                "source_id": str(source.get("source_id", "")),
                "title": str(source.get("title", "")),
                "url": str(source.get("url", "")),
                "verification_status": str(source.get("verification_status", "")),
                "admission_cycle": str(source.get("admission_cycle", "")),
            }
            for source in (rule.get("source_details") or [])
            if source.get("url") and source.get("verification_status") == "verified"
        ]
        item: dict[str, object] = {
            "university_id": str(rule["university_id"]),
            "university_name": university_names.get(str(rule["university_id"]), str(rule["university_id"])),
            "program_id": str(rule["program_id"]),
            "program_name": str(rule.get("program_name") or rule["program_id"]),
            "program_family": str(rule.get("program_family") or ""),
            "cycle": str(rule["cycle"]),
            "rule_version": str(rule.get("version") or ""),
            "status": str(result["status"]),
            "checks": result["checks"],
            "sources": sources,
            "note": str(rule.get("note") or ""),
            "disclaimer": str(result.get("disclaimer") or ""),
        }
        results.append(item)
        for source in sources:
            key = source["url"]
            citation_map.setdefault(key, {
                "title": source["title"],
                "url": source["url"],
                "verification_status": source["verification_status"],
                "admission_cycle": source["admission_cycle"],
                "university_id": str(rule["university_id"]),
            })

    counts = {
        "eligible": sum(1 for item in results if item["status"] == "eligible"),
        "conditionally_eligible": sum(1 for item in results if item["status"] == "conditionally_eligible"),
        "ineligible": sum(1 for item in results if item["status"] == "ineligible"),
        "indeterminate": sum(1 for item in results if item["status"] == "indeterminate"),
    }
    if payload.mode == "find_matches":
        priority = {"eligible": 0, "conditionally_eligible": 1, "indeterminate": 2, "ineligible": 3}
        user_text = "Find computing programs that match my saved academic profile."
        summary = (
            f"Checked your saved profile against {len(results)} currently source-verified computing-program rules: "
            f"{counts['eligible']} meet the listed minimum criteria, "
            f"{counts['conditionally_eligible']} have a conditional pathway, "
            f"{counts['ineligible']} are below at least one listed minimum, and "
            f"{counts['indeterminate']} need more information."
        )
    else:
        priority = {"ineligible": 0, "indeterminate": 1, "conditionally_eligible": 2, "eligible": 3}
        user_text = "Show the requirements I do not yet meet or need to verify."
        summary = (
            f"Reviewed {len(results)} currently source-verified computing-program rules. "
            "Start with the results marked below minimum or more information needed; read each explanation "
            "and confirm the active intake and campus with the university."
        )
    results.sort(key=lambda item: (
        priority.get(str(item.get("status")), 9),
        str(item.get("university_name", "")),
        str(item.get("program_name", "")),
    ))
    notice = (
        "This is a deterministic minimum-eligibility check, not an admission decision, merit ranking, or "
        "probability of acceptance. Only currently source-verified rules are included; other universities "
        "or programmes may be missing. Always confirm current intake, campus, and deadlines with the official source."
    )
    assistant_content = json.dumps(
        {
            "type": "profile_program_check",
            "mode": payload.mode,
            "summary": summary,
            "notice": notice,
            "total_rules": len(results),
            "counts": counts,
            "results": results,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    user_message = append_message(db, conversation, "user", user_text)
    # Explicit, ordered timestamps avoid ties on databases with low timestamp precision.
    user_message.created_at = datetime.now(timezone.utc)
    assistant_message = append_message(
        db, conversation, "assistant", assistant_content,
        citations=list(citation_map.values()),
    )
    assistant_message.created_at = user_message.created_at + timedelta(microseconds=1)
    conversation.updated_at = assistant_message.created_at
    record_security_event(
        db, request, settings,
        "conversation.program_check_completed",
        user_id=context.user.id,
    )
    db.commit()
    db.refresh(user_message)
    db.refresh(assistant_message)

    return AdvisorProgramCheckResponse(
        user_message=user_message,
        assistant_message=assistant_message,
        summary=summary,
        notice=notice,
        total_rules=len(results),
        eligible_count=counts["eligible"],
        conditional_count=counts["conditionally_eligible"],
        ineligible_count=counts["ineligible"],
        indeterminate_count=counts["indeterminate"],
        results=results,
    )

