"""Конвейер одного хода: роутер → префетч → вердикт → контекст → лимитер → LLM →
починка → сохранение (§10.3).

Модель участвует ровно в одном узле из одиннадцати. Всё остальное — код, поэтому
отказ модели не отменяет ход: он опускает его на детерминированный отчёт (§6.2).

Ход читает `llm.stream()`, а не `complete()`, и молча выбрасывает дельты: стримящему
маршруту (§13) останется отдать их наружу колбэком, не переписывая конвейер.
"""

import re
from typing import Any

from sqlalchemy.orm import Session

from src.agent import context, llm, prompts
from src.agent import router as agent_router
from src.agent import tokens, verdicts
from src.agent.profiles import ExecutionProfile, profile_for
from src.config.settings import get_settings
from src.core import factpack
from src.core import report as report_builder
from src.db.analyses import repository as analyses_repository
from src.db.client import repository as client_repository
from src.db.history import repository as history_repository
from src.db.models import Analysis
from src.db.models import Session as ChatSession
from src.db.models import User
from src.mcp.tools.selection import compare_contractors

# Ответ на уточнение — реплика, а не разбор (§1.2), и резервировать под него полный
# completion значит держать окно занятым втрое дольше нужного. Второго ключа
# в конфиге для этого не заводим: величина производная, а не настраиваемая.
CLARIFY_COMPLETION_DIVISOR = 3

DEGRADED_TAIL = "Показан детерминированный отчёт."
PARTIAL_NOTICE = "Модель вернула неполный разбор: часть отчёта заполнена детерминированно."
REPLY_TOKENS = "reply_tokens"

# Регулярка «упомянуто?» вместо валидатора: не нашлось — дописываем готовую строку
# из самого расхождения, ноль токенов и без перегенерации (§6.3).
_DISCREPANCY_MARKERS = {
    "green_but_execproc": r"исполнительн",
    "green_but_negative": r"негативн",
    "many_closed_execproc": r"исполнительн",
    "traffic_lights_disagree": r"ЗСК",
    "unknown_risk": r"не\s+смог|не\s+определ|неизвест",
    "no_financials": r"отч[её]тност|финансов",
}
# Правило 5 §9 требует назвать не только расхождения, но и критический правовой
# статус, а он живёт вне discrepancies — иначе банкротство теряется молча.
_LEGAL_MARKERS = {
    "bankruptcy": r"банкрот|конкурсн",
    "pending_exclusion": r"исключени",
}


class TurnError(Exception):
    """Ошибка ввода или отсутствие данных: транспорт переводит её в HTTP-статус."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


async def run_turn(
    session: Session,
    chat_session: ChatSession,
    user: User,
    message: str,
    buttons: list[str] | None = None,
) -> dict[str, Any]:
    # buttons принимаются, но пока не разбираются: наборы данных по кнопкам (§7)
    # подключаются отдельным шагом, а контракт запроса нужен фронту уже сейчас.
    profile = profile_for(user.tariff)
    quota = client_repository.get_quota(session, user.id)
    last = analyses_repository.last_for_session(session, chat_session.id)
    route = agent_router.choose(
        message,
        has_context=last is not None,
        requests_used=quota.requests_used if quota else 0,
        requests_limit=quota.requests_limit if quota else profile.requests_limit,
        max_compare=profile.max_compare,
    )
    if route.error:
        raise TurnError(422, route.error)

    if route.scenario == agent_router.ANALYZE:
        outcome = await _analyze(session, chat_session, route.inns[0], profile, message)
    elif route.scenario == agent_router.COMPARE:
        outcome = await _compare(session, chat_session, route.inns, profile, message)
    elif route.scenario == agent_router.CLARIFY:
        outcome = await _clarify(session, chat_session, profile, message, last)
    else:
        # Переспрос, отказ по квоте и превышение тарифного лимита сравнения —
        # штатные ответы за ноль токенов, а не деградация (§1.1).
        outcome = {"answer": route.answer}

    return _persist(session, chat_session, user, message, route, outcome)


async def _analyze(
    session: Session, chat: ChatSession, inn: str, profile: ExecutionProfile, message: str
) -> dict[str, Any]:
    pack = factpack.build(session, inn, mode=profile.factpack_mode, role=chat.role_preset)
    if pack is None:
        raise TurnError(404, "Контрагента с таким ИНН в базе нет.")

    decision = verdicts.decide(pack)
    baseline = verdicts.apply(report_builder.build(pack), pack)
    contractor = {"inn": pack["inn"], "short_name": pack["short_name"]}
    client_repository.set_session_title(session, chat, pack["short_name"])

    messages = context.build(
        session,
        chat.id,
        profile=profile,
        system_text=prompts.system(prompts.REPORT_KEYS),
        user_block=prompts.analyze_block(message, decision, pack),
        user_block_tokens=context.user_block_cost(message, profile.factpack_mode),
        # В разборе факт-пакет и так в контексте, якорь дублировал бы его (§4.1).
        with_anchor=False,
    )
    settings = get_settings()
    try:
        result = await _ask(messages, prompts.REPORT_SCHEMA, settings.tokens_expected_completion)
    except llm.LlmError as error:
        # Отчёт сохраняется и при отказе модели: иначе якорь останется пустым
        # и следующий вопрос без ИНН уйдёт в переспрос вместо уточнения (§1.2).
        _save(session, chat, pack, decision["verdict"], baseline["summary"], baseline["analysis"])
        return _degraded(baseline, contractor, str(error))

    answer = _repair(_text(result.data, prompts.ANSWER) or baseline["summary"], [pack])
    summary = _text(result.data, prompts.SUMMARY) or baseline["summary"]
    analysis = _with_risks(_text(result.data, prompts.ANALYSIS) or baseline["analysis"], result.data)
    _save(session, chat, pack, decision["verdict"], summary, analysis)
    return {
        "answer": answer,
        "verdict": decision["verdict"],
        "summary": summary,
        "analysis": analysis,
        "report": pack,
        "contractor": contractor,
        "degraded": False,
        "notice": PARTIAL_NOTICE if result.problems else None,
        REPLY_TOKENS: _completion(result.usage, answer),
    }


async def _compare(
    session: Session,
    chat: ChatSession,
    inns: tuple[str, ...],
    profile: ExecutionProfile,
    message: str,
) -> dict[str, Any]:
    payload = compare_contractors(list(inns), focus=chat.role_preset)
    if not payload["found"]:
        raise TurnError(404, payload["hint"])

    # Пакеты нужны не модели, а коду: вердикт и обязательные упоминания считаются
    # по ним, в промпт уходит сводка сравнения — она короче N пакетов.
    packs = factpack.build_many(session, [row["inn"] for row in payload["matrix"]], role=chat.role_preset)
    decisions = [{"inn": pack["inn"], **verdicts.decide(pack)} for pack in packs]
    baseline = _compare_text(payload, decisions)

    block = prompts.compare_block(message, decisions, payload)
    messages = context.build(
        session,
        chat.id,
        profile=profile,
        system_text=prompts.system(prompts.REPORT_KEYS),
        user_block=block,
        user_block_tokens=context.user_block_cost(block),
        with_anchor=True,
    )
    settings = get_settings()
    try:
        result = await _ask(messages, prompts.REPORT_SCHEMA, settings.tokens_expected_completion)
    except llm.LlmError as error:
        return {
            "answer": baseline,
            "degraded": True,
            "notice": f"{error} {DEGRADED_TAIL}",
            REPLY_TOKENS: tokens.estimate(baseline),
        }

    answer = _repair(_text(result.data, prompts.ANSWER) or baseline, packs)
    return {
        "answer": answer,
        "summary": _text(result.data, prompts.SUMMARY),
        "analysis": _with_risks(_text(result.data, prompts.ANALYSIS) or baseline, result.data),
        "degraded": False,
        "notice": PARTIAL_NOTICE if result.problems else None,
        REPLY_TOKENS: _completion(result.usage, answer),
    }


async def _clarify(
    session: Session,
    chat: ChatSession,
    profile: ExecutionProfile,
    message: str,
    last: Analysis,
) -> dict[str, Any]:
    pack = last.report or {}
    contractor = {"inn": last.inn, "short_name": pack.get("short_name") or last.inn}
    block = prompts.clarify_block(message)
    messages = context.build(
        session,
        chat.id,
        profile=profile,
        system_text=prompts.system(prompts.REPLY_KEYS),
        user_block=block,
        user_block_tokens=context.user_block_cost(block),
        with_anchor=True,
    )
    expected = get_settings().tokens_expected_completion // CLARIFY_COMPLETION_DIVISOR
    try:
        result = await _ask(messages, prompts.REPLY_SCHEMA, expected)
    except llm.LlmError as error:
        answer = (
            f"Отвечаю по последнему разбору — {contractor['short_name']} (ИНН {last.inn}).\n\n"
            f"{last.summary}\n\n{last.analysis}"
        )
        return {
            "answer": answer,
            "verdict": last.verdict,
            "summary": last.summary,
            "analysis": last.analysis,
            "report": pack or None,
            "contractor": contractor,
            "degraded": True,
            "notice": f"{error} {DEGRADED_TAIL}",
            REPLY_TOKENS: tokens.estimate(answer),
        }

    answer = _text(result.data, prompts.ANSWER) or last.summary or ""
    # §1.2: уточнение не рождает новый отчёт, поэтому analyses не трогаем,
    # а поля отчёта отдаём прежние — панель разбора не должна опустеть.
    return {
        "answer": answer,
        "verdict": last.verdict,
        "summary": last.summary,
        "analysis": last.analysis,
        "report": pack or None,
        "contractor": contractor,
        "degraded": False,
        REPLY_TOKENS: _completion(result.usage, answer),
    }


async def _ask(messages: list[dict[str, str]], schema: dict, expected_completion: int) -> llm.Result:
    """Дельты здесь отбрасываются: блокирующий маршрут дочитывает генератор до конца."""
    settings = get_settings()
    async for event in llm.stream(messages, schema, settings.llm_tpm_limit, expected_completion):
        if isinstance(event, llm.Failure):
            raise llm.LlmError(event.detail)
        if isinstance(event, llm.Result):
            return event
    raise llm.LlmError("Модель не вернула ответ.")


def _save(
    session: Session, chat: ChatSession, pack: dict[str, Any], verdict: str, summary: str, analysis: str
) -> None:
    analyses_repository.save(
        session,
        session_id=chat.id,
        inn=pack["inn"],
        analysis_type=chat.role_preset,
        verdict=verdict,
        summary=summary,
        report=pack,
        analysis=analysis,
    )


def _degraded(baseline: dict[str, Any], contractor: dict[str, str], detail: str) -> dict[str, Any]:
    answer = f"{baseline['summary']}\n\n{baseline['analysis']}"
    return {
        "answer": answer,
        "verdict": baseline["verdict"],
        "summary": baseline["summary"],
        "analysis": baseline["analysis"],
        "report": baseline["report"],
        "contractor": contractor,
        "degraded": True,
        "notice": f"{detail} {DEGRADED_TAIL}",
        REPLY_TOKENS: tokens.estimate(answer),
    }


def _text(data: dict[str, Any], key: str) -> str | None:
    """Хвостовые поля могли не прийти (Result.problems): ответ пользователю от этого
    не отменяется, недостающее место занимает детерминированный текст."""
    value = data.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _with_risks(analysis: str, data: dict[str, Any]) -> str:
    risks = [item for item in data.get(prompts.KEY_RISKS) or [] if isinstance(item, str) and item.strip()]
    if not risks:
        return analysis
    return analysis + "\n\nКлючевые риски:\n" + "\n".join(f"— {item}" for item in risks)


def _completion(usage: dict[str, Any], answer: str) -> int:
    """Расход реплики ассистента: prompt_tokens относится ко всему запросу (§4.3).

    Рассуждение вычитается: у reasoning-модели оно составляет треть completion
    (замерено: 527 из 1197), но ни в БД, ни в следующий контекст не попадает —
    оставить его значило бы завышать стоимость реплики при сборке окна втрое.
    """
    value = usage.get("completion_tokens")
    if not value:
        return tokens.estimate(answer)
    reasoning = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0
    return max(int(value) - int(reasoning), 1)


def _repair(answer: str, packs: list[dict[str, Any]]) -> str:
    missing: list[str] = []
    for pack in packs:
        label = f"{pack['short_name']}: " if len(packs) > 1 else ""
        for pattern, text in _required_mentions(pack):
            if pattern and re.search(pattern, answer, re.IGNORECASE):
                continue
            missing.append(f"{label}{text}")
    if not missing:
        return answer
    return answer + "\n\nТакже обратите внимание:\n" + "\n".join(f"— {item}" for item in missing)


def _required_mentions(pack: dict[str, Any]) -> list[tuple[str | None, str]]:
    """Что обязано прозвучать по правилу 5 §9, вместе с готовой формулировкой.

    Незнакомый код маркера не имеет — такое расхождение дописывается всегда:
    промолчать о нём хуже, чем повториться.
    """
    status = pack.get("legal_status") or {}
    required: list[tuple[str | None, str]] = []
    if status.get("severity") == "critical" and status.get("status_reason"):
        required.append((_LEGAL_MARKERS.get(status.get("reason_code")), f"В ЕГРЮЛ: {status['status_reason']}"))
    required += [
        (_DISCREPANCY_MARKERS.get(item["code"]), item["text"]) for item in pack.get("discrepancies") or []
    ]
    return required


def _compare_text(payload: dict[str, Any], decisions: list[dict[str, Any]]) -> str:
    verdict_by_inn = {item["inn"]: item["verdict"] for item in decisions}
    lines = [f"Сравнение: {len(payload['matrix'])} контрагентов."]
    for row in payload["matrix"]:
        lines.append(
            f"— {row['short_name']} (ИНН {row['inn']}): риск {row.get('risk_level') or 'не определён'}, "
            f"ЗСК {row.get('zsk_risk_level') or 'не определён'}, "
            f"негативных факторов {row.get('negative_factors', 0)}. "
            f"Вердикт: {verdict_by_inn.get(row['inn'], 'не определён')}."
        )
    if payload["differences"]:
        lines.append("Различия:")
        lines.extend(f"— {item['text']}" for item in payload["differences"])
    if payload["not_found"]:
        lines.append(f"Нет в базе: {', '.join(payload['not_found'])}.")
    # §1.4: сводного вывода «работайте с этим» не даёт ни код, ни модель.
    lines.append("Решение остаётся за вами: инструмент показывает различия, а не выбирает контрагента.")
    return "\n".join(lines)


def _persist(
    session: Session,
    chat: ChatSession,
    user: User,
    message: str,
    route: agent_router.Route,
    outcome: dict[str, Any],
) -> dict[str, Any]:
    reply_tokens = outcome.pop(REPLY_TOKENS, None)
    question = history_repository.add_message(
        session,
        session_id=chat.id,
        role="user",
        content=message,
        # Точного значения на реплику пользователя не существует: в usage она входит
        # слагаемым prompt_tokens вместе со всем остальным запросом (§4.3).
        tokens=tokens.estimate(message),
    )
    # факт-пакет в историю не кладём: он живёт в analyses, а окно контекста его вырезает
    reply = history_repository.add_message(
        session,
        session_id=chat.id,
        role="assistant",
        content=outcome["answer"],
        tokens=reply_tokens if reply_tokens is not None else tokens.estimate(outcome["answer"]),
        meta={
            "scenario": route.scenario,
            "inn": (outcome.get("contractor") or {}).get("inn"),
            "degraded": outcome.get("degraded", False),
        },
    )
    if route.needs_llm:
        # Детерминированные отказы квоту не тратят: они не обращаются к поставщику.
        client_repository.record_request(
            session, user.id, report_generated=route.scenario == agent_router.ANALYZE
        )
    return {**outcome, "messages": [question, reply]}
