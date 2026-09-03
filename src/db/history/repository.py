from uuid import UUID

from sqlalchemy import func, select
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


def list_messages(
    session: Session, session_id: UUID, limit: int | None = None, before_id: int | None = None
) -> list[Message]:
    query = select(Message).where(Message.session_id == session_id)
    if before_id is not None:
        query = query.where(Message.id < before_id)
    if limit is None:
        return list(session.scalars(query.order_by(Message.created_at, Message.id)))
    # страницу берём с конца диалога, а отдаём в прямом порядке
    page = session.scalars(query.order_by(Message.id.desc()).limit(limit))
    return list(reversed(list(page)))


def count_messages(session: Session, session_id: UUID) -> int:
    return session.scalar(select(func.count()).select_from(Message).where(Message.session_id == session_id)) or 0


def count_messages_before(session: Session, session_id: UUID, message_id: int) -> int:
    query = select(func.count()).select_from(Message).where(
        Message.session_id == session_id, Message.id < message_id
    )
    return session.scalar(query) or 0


def last_messages(session: Session, session_id: UUID, limit: int) -> list[Message]:
    query = (
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(limit)
    )
    return list(reversed(list(session.scalars(query))))
