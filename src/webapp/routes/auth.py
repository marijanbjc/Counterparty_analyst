from fastapi import APIRouter, HTTPException, status

from src.agent.profiles import profile_for
from src.config.settings import get_settings
from src.db.client import repository as client_repository
from src.webapp.dependencies import DbSession
from src.webapp.schemas import LoginRequest, LoginResponse
from src.webapp.security import check_credentials, issue_token

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, session: DbSession) -> LoginResponse:
    if not check_credentials(payload.login, payload.password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Неверный логин или пароль.")

    tariff = get_settings().tariff_default
    user = client_repository.ensure_user(
        session, payload.login, tariff=tariff, requests_limit=profile_for(tariff).requests_limit
    )
    token, expires_at = issue_token(str(user.id))
    return LoginResponse(user_id=user.id, token=token, expires_at=expires_at)
