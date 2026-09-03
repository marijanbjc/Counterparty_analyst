from collections.abc import Iterator
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from src.db.client import repository as client_repository
from src.db.engine import db_session
from src.db.models import User
from src.webapp.security import TokenError, verify_token

def get_db() -> Iterator[Session]:
    with db_session() as session:
        yield session


DbSession = Annotated[Session, Depends(get_db)]


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED, detail=detail, headers={"WWW-Authenticate": "Bearer"}
    )


def get_current_user(
    session: DbSession,
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise _unauthorized("Требуется токен: заголовок Authorization: Bearer <token>.")

    try:
        user_id = UUID(verify_token(token))
    except (TokenError, ValueError) as error:
        raise _unauthorized(str(error) if isinstance(error, TokenError) else "Токен повреждён.") from error

    user = client_repository.get_user(session, user_id)
    if user is None:
        raise _unauthorized("Пользователь не найден.")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
