import asyncio
import json
import logging
from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from src.agent import pipeline
from src.webapp.dependencies import CurrentUser
from src.webapp.schemas import ChatRequest, ChatResponse

router = APIRouter(prefix="/api", tags=["chat"])
logger = logging.getLogger(__name__)

SSE_MEDIA_TYPE = "text/event-stream"
SSE_HEARTBEAT_SECONDS = 15.0
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
    queue: asyncio.Queue[pipeline.TurnEvent | pipeline.TurnError | None] = asyncio.Queue()

    async def produce() -> None:
        try:
            async for event in _turn(payload, user_id):
                queue.put_nowait(event)
        except pipeline.TurnError as error:
            queue.put_nowait(error)
        except Exception:
            logger.exception("Unhandled agent turn failure", extra={"session_id": str(payload.session_id)})
            queue.put_nowait(pipeline.Error("Внутренняя ошибка хода.", degraded=False))
        finally:
            queue.put_nowait(None)

    # StreamingResponse отменяет итератор при разрыве соединения. Сам ход живёт
    # отдельной задачей приложения, поэтому продолжает расчёт и коммит даже если
    # браузер нажал Stop. Сильная ссылка в app.state не даёт asyncio собрать задачу.
    tasks: set[asyncio.Task] = getattr(request.app.state, "agent_turn_tasks", set())
    request.app.state.agent_turn_tasks = tasks
    task = asyncio.create_task(produce(), name=f"agent-turn-{payload.session_id}")
    tasks.add(task)
    task.add_done_callback(tasks.discard)

    while True:
        try:
            event = await asyncio.wait_for(queue.get(), timeout=SSE_HEARTBEAT_SECONDS)
        except TimeoutError:
            if await request.is_disconnected():
                return
            yield ": keep-alive\n\n"
            continue
        if event is None:
            return
        if await request.is_disconnected():
            return
        if isinstance(event, pipeline.TurnError):
            yield _sse("error", {"detail": event.detail, "degraded": False})
        elif isinstance(event, pipeline.Stage):
            yield _sse("stage", {"name": event.name})
        elif isinstance(event, pipeline.Delta):
            yield _sse("delta", {"text": event.text})
        elif isinstance(event, pipeline.Error):
            yield _sse("error", {"detail": event.detail, "degraded": event.degraded})
        else:
            yield _sse("done", ChatResponse(**event.payload).model_dump(mode="json"))
