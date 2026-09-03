from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import Session as ChatSession
from src.db.models import User, UserQuota


def get_user(session: Session, user_id: UUID) -> User | None:
    return session.get(User, user_id)


def get_user_by_login(session: Session, login: str) -> User | None:
    return session.scalar(select(User).where(User.login == login))


def ensure_user(session: Session, login: str, display_name: str | None = None) -> User:
    user = get_user_by_login(session, login)
    if user is not None:
        return user
    user = User(login=login, display_name=display_name or login)
    session.add(user)
    session.flush()
    session.add(UserQuota(user_id=user.id))
    session.flush()
    return user


def get_quota(session: Session, user_id: UUID) -> UserQuota | None:
    return session.get(UserQuota, user_id)


def list_sessions(session: Session, user_id: UUID) -> list[ChatSession]:
    query = select(ChatSession).where(ChatSession.user_id == user_id).order_by(ChatSession.created_at.desc())
    return list(session.scalars(query))


def create_session(
    session: Session, user_id: UUID, role_preset: str, title: str | None = None
) -> ChatSession:
    chat = ChatSession(user_id=user_id, role_preset=role_preset, title=title)
    session.add(chat)
    session.flush()
    session.refresh(chat)
    return chat


def get_session(session: Session, session_id: UUID, user_id: UUID | None = None) -> ChatSession | None:
    chat = session.get(ChatSession, session_id)
    if chat is None or (user_id is not None and chat.user_id != user_id):
        return None
    return chat


def update_session_role(session: Session, chat: ChatSession, role_preset: str) -> ChatSession:
    chat.role_preset = role_preset
    session.flush()
    session.refresh(chat)
    return chat


def delete_session(session: Session, chat: ChatSession) -> None:
    session.delete(chat)
    session.flush()


def set_session_title(session: Session, chat: ChatSession, title: str) -> ChatSession:
    if not chat.title:
        chat.title = title
        session.flush()
        session.refresh(chat)
    return chat


def record_request(session: Session, user_id: UUID, report_generated: bool = False) -> UserQuota:
    quota = get_quota(session, user_id)
    if quota is None:
        quota = UserQuota(user_id=user_id)
        session.add(quota)
    quota.requests_used += 1
    if report_generated:
        quota.reports_generated += 1
    session.flush()
    return quota
