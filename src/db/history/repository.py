from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import Message


def add_message(
    session: Session,
    session_id: UUID,
    role: str,
    content: str,
    tokens: int | None = None,
    meta: dict | None = None,
) -> Message:
    message = Message(session_id=session_id, role=role, content=content, tokens=tokens, meta=meta)
    session.add(message)
    session.flush()
    session.refresh(message)
    return message


def list_messages(session: Session, session_id: UUID, limit: int | None = None) -> list[Message]:
    query = select(Message).where(Message.session_id == session_id).order_by(Message.created_at, Message.id)
    if limit is not None:
        query = query.limit(limit)
    return list(session.scalars(query))


def last_messages(session: Session, session_id: UUID, limit: int) -> list[Message]:
    query = (
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(limit)
    )
    return list(reversed(list(session.scalars(query))))
