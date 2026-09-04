from fastapi import APIRouter, HTTPException, status
from sqlalchemy.orm import Session

from src.agent import router as agent_router
from src.agent import verdicts
from src.agent.profiles import ExecutionProfile, profile_for
from src.core import factpack
from src.core import report as report_builder
from src.db.analyses import repository as analyses_repository
from src.db.client import repository as client_repository
from src.db.history import repository as history_repository
from src.db.models import Analysis
from src.db.models import Session as ChatSession
from src.mcp.tools.selection import compare_contractors
from src.webapp.dependencies import CurrentUser, DbSession
from src.webapp.schemas import ChatRequest, ChatResponse

router = APIRouter(prefix="/api", tags=["chat"])

DEGRADED_NOTICE = "ИИ-анализ пока не подключён. Показан детерминированный отчёт."


def _analyze(session: Session, chat: ChatSession, inn: str, profile: ExecutionProfile) -> dict:
    pack = factpack.build(session, inn, mode=profile.factpack_mode, role=chat.role_preset)
    if pack is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Контрагента с таким ИНН в базе нет.")

    result = verdicts.apply(report_builder.build(pack), pack)
    client_repository.set_session_title(session, chat, pack["short_name"])
    analyses_repository.save(
        session,
        session_id=chat.id,
        inn=pack["inn"],
        analysis_type=chat.role_preset,
        verdict=result["verdict"],
        summary=result["summary"],
        report=result["report"],
        analysis=result["analysis"],
    )
    return {
        "answer": f"{result['summary']}\n\n{result['analysis']}",
        "verdict": result["verdict"],
        "summary": result["summary"],
        "analysis": result["analysis"],
        "report": result["report"],
        "contractor": {"inn": pack["inn"], "short_name": pack["short_name"]},
        "degraded": True,
        "notice": DEGRADED_NOTICE,
    }


def _clarify(last: Analysis) -> dict:
    pack = last.report or {}
    name = pack.get("short_name") or last.inn
    answer = (
        f"Отвечаю по последнему разбору — {name} (ИНН {last.inn}).\n\n"
        f"{last.summary}\n\n{last.analysis}"
    )
    # §1.2: уточнение не рождает новый отчёт, поэтому analyses не трогаем.
    return {
        "answer": answer,
        "verdict": last.verdict,
        "summary": last.summary,
        "analysis": last.analysis,
        "report": pack or None,
        "contractor": {"inn": last.inn, "short_name": name},
        "degraded": True,
        "notice": DEGRADED_NOTICE,
    }


def _compare(inns: tuple[str, ...], role: str) -> dict:
    payload = compare_contractors(list(inns), focus=role)
    if not payload["found"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=payload["hint"])

    lines = [f"Сравнение: {len(payload['matrix'])} контрагентов."]
    for row in payload["matrix"]:
        lines.append(
            f"— {row['short_name']} (ИНН {row['inn']}): риск {row.get('risk_level') or 'не определён'}, "
            f"ЗСК {row.get('zsk_risk_level') or 'не определён'}, "
            f"негативных факторов {row.get('negative_factors', 0)}."
        )
    if payload["differences"]:
        lines.append("Различия:")
        lines.extend(f"— {item['text']}" for item in payload["differences"])
    if payload["not_found"]:
        lines.append(f"Нет в базе: {', '.join(payload['not_found'])}.")
    # §1.4: сводного вывода «работайте с этим» не даёт ни код, ни модель.
    lines.append("Решение остаётся за вами: инструмент показывает различия, а не выбирает контрагента.")

    return {"answer": "\n".join(lines), "degraded": True, "notice": DEGRADED_NOTICE}


@router.post("/chat", response_model=ChatResponse)
def chat(payload: ChatRequest, session: DbSession, user: CurrentUser) -> ChatResponse:
    chat_session = client_repository.get_session(session, payload.session_id, user_id=user.id)
    if chat_session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Сессия не найдена.")

    if payload.role_preset and payload.role_preset != chat_session.role_preset:
        client_repository.update_session_role(session, chat_session, payload.role_preset)

    profile = profile_for(user.tariff)
    quota = client_repository.get_quota(session, user.id)
    last = analyses_repository.last_for_session(session, chat_session.id)
    route = agent_router.choose(
        payload.message,
        has_context=last is not None,
        requests_used=quota.requests_used if quota else 0,
        requests_limit=quota.requests_limit if quota else profile.requests_limit,
        max_compare=profile.max_compare,
    )
    if route.error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=route.error)

    if route.scenario == agent_router.ANALYZE:
        outcome = _analyze(session, chat_session, route.inns[0], profile)
    elif route.scenario == agent_router.COMPARE:
        outcome = _compare(route.inns, chat_session.role_preset)
    elif route.scenario == agent_router.CLARIFY:
        outcome = _clarify(last)
    else:
        # Переспрос, отказ по квоте и превышение тарифного лимита сравнения —
        # штатные ответы за ноль токенов, а не деградация (§1.1).
        outcome = {"answer": route.answer}

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
        content=outcome["answer"],
        meta={"scenario": route.scenario, "inn": (outcome.get("contractor") or {}).get("inn"),
              "degraded": outcome.get("degraded", False)},
    )
    if route.needs_llm:
        # Детерминированные отказы квоту не тратят: они не обращаются к поставщику.
        client_repository.record_request(
            session, user.id, report_generated=route.scenario == agent_router.ANALYZE
        )

    return ChatResponse(session=chat_session, messages=[question, reply], **outcome)
