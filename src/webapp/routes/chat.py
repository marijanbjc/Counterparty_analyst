from fastapi import APIRouter, HTTPException, status

from src.core import factpack
from src.core import inn as inn_module
from src.core import report as report_builder
from src.db.analyses import repository as analyses_repository
from src.db.client import repository as client_repository
from src.db.history import repository as history_repository
from src.webapp.dependencies import CurrentUser, DbSession
from src.webapp.schemas import ChatRequest, ChatResponse

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
def chat(payload: ChatRequest, session: DbSession, user: CurrentUser) -> ChatResponse:
    chat_session = client_repository.get_session(session, payload.session_id, user_id=user.id)
    if chat_session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Сессия не найдена.")

    if payload.role_preset and payload.role_preset != chat_session.role_preset:
        client_repository.update_session_role(session, chat_session, payload.role_preset)

    inns = inn_module.extract(payload.message)
    if not inns:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Укажите в сообщении ИНН организации (10 цифр) или ИП (12 цифр).",
        )
    if len(inns) > 1:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Для нескольких ИНН используйте режим сравнения.",
        )

    pack = factpack.build(session, inns[0], mode=factpack.FULL, role=chat_session.role_preset)
    if pack is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail="Контрагента с таким ИНН в базе нет.",
        )

    result = report_builder.build(pack)
    answer = f"{result['summary']}\n\n{result['analysis']}"
    question = history_repository.add_message(
        session,
        session_id=chat_session.id,
        role="user",
        content=payload.message,
    )
    # факт-пакет в историю не кладём: он живёт в analyses, а окно контекста его вырезает
    reply = history_repository.add_message(
        session,
        session_id=chat_session.id,
        role="assistant",
        content=answer,
        meta={"inn": pack["inn"], "degraded": True},
    )
    client_repository.set_session_title(session, chat_session, pack["short_name"])
    analyses_repository.save(
        session,
        session_id=chat_session.id,
        inn=pack["inn"],
        analysis_type=chat_session.role_preset,
        verdict=result["verdict"],
        summary=result["summary"],
        report=result["report"],
        analysis=result["analysis"],
    )
    client_repository.record_request(session, user.id, report_generated=True)

    return ChatResponse(
        answer=answer,
        contractor={"inn": pack["inn"], "short_name": pack["short_name"]},
        session=chat_session,
        messages=[question, reply],
        **result,
    )
