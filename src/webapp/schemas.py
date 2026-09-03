from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from src.core.roles import DEFAULT_ROLE, ROLE_CHAPTERS


def _known_role(value: str) -> str:
    if value not in ROLE_CHAPTERS:
        raise ValueError(f"Неизвестная роль. Допустимые: {', '.join(sorted(ROLE_CHAPTERS))}.")
    return value


RolePreset = Annotated[str, AfterValidator(_known_role)]
MessageRole = Literal["user", "assistant", "system", "tool"]


class LoginRequest(BaseModel):
    login: str
    password: str


class LoginResponse(BaseModel):
    user_id: UUID
    token: str
    expires_at: datetime


class SessionCreateRequest(BaseModel):
    role_preset: RolePreset = DEFAULT_ROLE
    title: str | None = None


class SessionUpdateRequest(BaseModel):
    role_preset: RolePreset


class SessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    title: str | None
    role_preset: str
    created_at: datetime


class MessageCreateRequest(BaseModel):
    role: MessageRole = "user"
    content: str = Field(min_length=1)
    tokens: int | None = None
    meta: dict | None = None


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: UUID
    role: str
    content: str
    tokens: int | None
    meta: dict | None
    created_at: datetime


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    database: bool
    detail: str | None = None


class ChatRequest(BaseModel):
    session_id: UUID
    message: str = Field(min_length=1)
    role_preset: RolePreset | None = None


class ChatResponse(BaseModel):
    answer: str
    verdict: str
    summary: str
    analysis: str
    report: dict
    contractor: dict
    degraded: bool = True
    notice: str


class CompareRequest(BaseModel):
    inns: list[str] = Field(min_length=2, max_length=10)
    role_preset: RolePreset = DEFAULT_ROLE


class AnalysisSummaryResponse(BaseModel):
    inn: str
    short_name: str
    analysis_type: str
    verdict: str | None
    summary: str | None
    created_at: datetime


class ReportUpdateRequest(BaseModel):
    summary: str | None = None
    analysis: str | None = None


class ProfileResponse(BaseModel):
    login: str
    display_name: str | None
    tariff: str
    requests_used: int
    requests_limit: int
    reports_generated: int
