import base64
import hashlib
import hmac
from datetime import datetime, timedelta, timezone

from src.config.settings import get_settings


class TokenError(Exception):
    pass


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _sign(payload: str, secret: str) -> str:
    return _b64encode(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())


def issue_token(user_id: str) -> tuple[str, datetime]:
    settings = get_settings()
    expires_at = datetime.now(timezone.utc) + timedelta(hours=settings.auth_token_ttl_hours)
    payload = _b64encode(f"{user_id}:{int(expires_at.timestamp())}".encode())
    return f"{payload}.{_sign(payload, settings.auth_token_secret)}", expires_at


def verify_token(token: str) -> str:
    payload, _, signature = (token or "").partition(".")
    if not payload or not signature:
        raise TokenError("Токен повреждён.")

    if not hmac.compare_digest(signature, _sign(payload, get_settings().auth_token_secret)):
        raise TokenError("Подпись токена неверна.")

    try:
        user_id, _, expires_at = _b64decode(payload).decode().rpartition(":")
        deadline = int(expires_at)
    except (ValueError, UnicodeDecodeError) as error:
        raise TokenError("Токен повреждён.") from error

    if deadline < datetime.now(timezone.utc).timestamp():
        raise TokenError("Срок действия токена истёк.")
    return user_id


def check_credentials(login: str, password: str) -> bool:
    settings = get_settings()
    login_ok = hmac.compare_digest(login or "", settings.auth_login)
    password_ok = hmac.compare_digest(password or "", settings.auth_password)
    return login_ok and password_ok
