import json
from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from src.agent import pipeline
from src.webapp.dependencies import CurrentUser
from src.webapp.schemas import ChatRequest, ChatResponse

router = APIRouter(prefix="/api", tags=["chat"])

SSE_MEDIA_TYPE = "text/event-stream"
# Буферизующий прокси съедает весь смысл потока, поэтому просим его не буферизовать.
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


@router.post("/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest, user: CurrentUser) -> ChatResponse:
    """Блокирующий ход: тот же конвейер, просто дочитанный до конца (§13.3).

    Сессию БД маршрут не открывает: обе фазы конвейера берут свою, потому что
    у стримящего маршрута сессия запроса закрывается до старта генератора (§13.5).
    """
    try:
        async for event in _turn(payload, user.id):
            if isinstance(event, pipeline.Done):
                return ChatResponse(**event.payload)
    except pipeline.TurnError as error:
        raise HTTPException(error.status_code, detail=error.detail) from error
    raise HTTPException(500, detail="Ход не вернул результат.")


@router.post("/chat/stream")
async def chat_stream(
    payload: ChatRequest, user: CurrentUser, request: Request
) -> StreamingResponse:
    """Тот же ход, но событиями SSE: stage, delta, done, error (§13.4)."""
    return StreamingResponse(
        _events(payload, user.id, request),
        media_type=SSE_MEDIA_TYPE,
        headers=SSE_HEADERS,
    )


def _turn(payload: ChatRequest, user_id: UUID) -> AsyncIterator[pipeline.TurnEvent]:
    return pipeline.run_turn(
        payload.session_id, user_id, payload.message, payload.buttons, payload.role_preset
    )


def _sse(name: str, data: dict) -> str:
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


async def _events(payload: ChatRequest, user_id: UUID, request: Request) -> AsyncIterator[str]:
    try:
        async for event in _turn(payload, user_id):
            if await request.is_disconnected():
                # Клиент ушёл: события больше некому слать, но ход досчитывается —
                # квота уже списана, и ответ должен найтись при возврате в сессию.
                continue
            if isinstance(event, pipeline.Stage):
                yield _sse("stage", {"name": event.name})
            elif isinstance(event, pipeline.Delta):
                yield _sse("delta", {"text": event.text})
            elif isinstance(event, pipeline.Error):
                yield _sse("error", {"detail": event.detail, "degraded": event.degraded})
            else:
                yield _sse("done", ChatResponse(**event.payload).model_dump(mode="json"))
    except pipeline.TurnError as error:
        # Статус ответа уже отправлен, поэтому ошибка ввода уезжает событием,
        # а не HTTP-кодом, как у блокирующего маршрута.
        yield _sse("error", {"detail": error.detail, "degraded": False})
