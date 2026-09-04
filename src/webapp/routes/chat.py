from fastapi import APIRouter, HTTPException, status

from src.agent import pipeline
from src.db.client import repository as client_repository
from src.webapp.dependencies import CurrentUser, DbSession
from src.webapp.schemas import ChatRequest, ChatResponse

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest, session: DbSession, user: CurrentUser) -> ChatResponse:
    """Блокирующий ход: маршрут async, потому что коннектор к Groq асинхронный (§13.7).

    Работа с БД остаётся синхронной; вынос её в threadpool нужен стримящему
    маршруту, где коммит посреди потока блокировал бы event loop у всех клиентов.
    """
    chat_session = client_repository.get_session(session, payload.session_id, user_id=user.id)
    if chat_session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Сессия не найдена.")

    if payload.role_preset and payload.role_preset != chat_session.role_preset:
        client_repository.update_session_role(session, chat_session, payload.role_preset)

    try:
        outcome = await pipeline.run_turn(
            session, chat_session, user, payload.message, payload.buttons
        )
    except pipeline.TurnError as error:
        raise HTTPException(error.status_code, detail=error.detail) from error

    return ChatResponse(session=chat_session, **outcome)
