from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from src.db.client import repository as client_repository
from src.db.history import repository as history_repository
from src.db.models import Session as ChatSession
from src.webapp.dependencies import CurrentUser, DbSession
from src.webapp.schemas import (
    MessageCreateRequest,
    MessageResponse,
    SessionCreateRequest,
    SessionResponse,
    SessionUpdateRequest,
)

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


def _owned_session(session: DbSession, session_id: UUID, user: CurrentUser) -> ChatSession:
    chat = client_repository.get_session(session, session_id, user_id=user.id)
    if chat is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Сессия не найдена.")
    return chat


@router.get("", response_model=list[SessionResponse])
def list_sessions(session: DbSession, user: CurrentUser) -> list[ChatSession]:
    return client_repository.list_sessions(session, user.id)


@router.post("", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
def create_session(payload: SessionCreateRequest, session: DbSession, user: CurrentUser) -> ChatSession:
    return client_repository.create_session(
        session, user_id=user.id, role_preset=payload.role_preset, title=payload.title
    )


@router.patch("/{session_id}", response_model=SessionResponse)
def update_session(
    session_id: UUID,
    payload: SessionUpdateRequest,
    session: DbSession,
    user: CurrentUser,
) -> ChatSession:
    chat = _owned_session(session, session_id, user)
    return client_repository.update_session_role(session, chat, payload.role_preset)


@router.get("/{session_id}/messages", response_model=list[MessageResponse])
def list_messages(session_id: UUID, session: DbSession, user: CurrentUser):
    chat = _owned_session(session, session_id, user)
    return history_repository.list_messages(session, chat.id)


@router.post("/{session_id}/messages", response_model=MessageResponse, status_code=status.HTTP_201_CREATED)
def add_message(session_id: UUID, payload: MessageCreateRequest, session: DbSession, user: CurrentUser):
    chat = _owned_session(session, session_id, user)
    return history_repository.add_message(
        session,
        session_id=chat.id,
        role=payload.role,
        content=payload.content,
        tokens=payload.tokens,
        meta=payload.meta,
    )
