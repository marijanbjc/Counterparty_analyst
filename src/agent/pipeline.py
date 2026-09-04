"""Конвейер одного хода: роутер → префетч → вердикт → контекст → лимитер → LLM →
починка → сохранение (§10.3).

Модель участвует ровно в одном узле из одиннадцати. Всё остальное — код, поэтому
отказ модели не отменяет ход: он опускает его на детерминированный отчёт (§6.2).

Ход — асинхронный генератор событий (§13.4). Стримящий маршрут отдаёт их наружу
как SSE, блокирующий дочитывает до конца и берёт последнее. Второй реализации
логики нет, и появиться ей негде.

Три фазы и три обращения к БД — это требование §13.5, а не стиль. Генератор
`StreamingResponse` исполняется ПОСЛЕ того, как тело эндпоинта вернуло управление,
и сессия запроса к этому моменту закрыта. Поэтому каждая фаза открывает свою
сессию через `db_session()` и коммитит её до выхода, а между фазами наружу
не выносится ни одного ORM-объекта, кроме уже загруженных и отсоединённых.
"""

import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import anyio.to_thread
from sqlalchemy.orm import Session

from src.agent import context, limiter, llm, prefetch, prompts
from src.agent import router as agent_router
from src.agent import tokens, verdicts
from src.agent.profiles import ExecutionProfile, profile_for
from src.config.settings import get_settings
from src.core import factpack
from src.core import report as report_builder
from src.db.analyses import repository as analyses_repository
from src.db.client import repository as client_repository
from src.db.engine import db_session
from src.db.history import repository as history_repository
from src.db.models import Message
from src.db.models import Session as ChatSession
from src.mcp.tools.selection import compare_contractors

# Ответ на уточнение — реплика, а не разбор (§1.2), и резервировать под него полный
# completion значит держать окно занятым втрое дольше нужного. Второго ключа
# в конфиге для этого не заводим: величина производная, а не настраиваемая.
CLARIFY_COMPLETION_DIVISOR = 3

# Служебный ключ outcome: фактический расход ответа, который _persist снимает
# и кладёт в messages.tokens. В ChatResponse он не уходит — только в историю,
# чтобы следующая сборка контекста считала старые реплики по факту, а не оценкой.
REPLY_TOKENS = "_reply_tokens"

DEGRADED_TAIL = "Показан детерминированный отчёт."
PARTIAL_NOTICE = "Модель вернула неполный разбор: часть отчёта заполнена детерминированно."
INTERRUPTED = "\n\nИИ-анализ прерван, ниже детерминированный отчёт.\n\n"

STAGE_PREFETCH = "prefetch"
STAGE_VERDICT = "verdict"
STAGE_CONTEXT = "context"
STAGE_WAITING_LIMIT = "waiting_limit"
STAGE_LLM = "llm"
STAGE_REPAIR = "repair"
STAGE_PERSIST = "persist"

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
    """Ошибка ввода или отсутствие данных: транспорт переводит её в HTTP-статус.

    Возникает только в первой фазе — до того, как поток начал отдавать события,
    иначе статус ответа уже отправлен и менять его поздно.
    """

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class Stage:
    name: str


@dataclass(frozen=True)
class Delta:
    text: str


@dataclass(frozen=True)
class Done:
    payload: dict[str, Any]


@dataclass(frozen=True)
class Error:
    detail: str
    degraded: bool = True


TurnEvent = Stage | Delta | Done | Error


@dataclass
class _Plan:
    """Всё, что первая фаза добыла из БД, в виде обычных данных.

    ORM-объектов здесь нет намеренно: план переживает закрытие сессии и уезжает
    во вторую фазу, где живой сессии уже не существует.
    """

    scenario: str
    needs_llm: bool
    profile: ExecutionProfile
    session_id: UUID
    user_id: UUID
    role_preset: str
    message: str
    stages: tuple[str, ...] = ()
    llm_messages: list[dict[str, str]] | None = None
    schema: dict | None = None
    expected_completion: int = 0
    answer: str | None = None  # готовая реплика, когда модель не нужна
    pack: dict[str, Any] | None = None
    packs: list[dict[str, Any]] = field(default_factory=list)
    verdict: str | None = None
    baseline: dict[str, Any] | None = None
    baseline_text: str | None = None
    contractor: dict[str, str] | None = None
    notice: str | None = None
    last: dict[str, Any] | None = None
    title: str | None = None


async def run_turn(
    session_id: UUID,
    user_id: UUID,
    message: str,
    buttons: list[str] | None = None,
    role_preset: str | None = None,
) -> AsyncIterator[TurnEvent]:
    """События хода по §13.4: stage, delta, done или error.

    Первая фаза целиком отрабатывает ДО первого yield, и её стадии уходят наружу
    сразу после. Иначе `TurnError` вылетал бы уже после старта потока, когда HTTP
    200 отправлен и ошибку не выразить. Стадии от этого не теряют смысла: фаза
    состоит из чтений БД и укладывается в миллисекунды, а единственная длинная
    пауза за ход — ожидание окна лимитера — сигналится своей стадией.
    """
    plan = await anyio.to_thread.run_sync(
        lambda: _prepare(session_id, user_id, message, buttons, role_preset)
    )
    for name in plan.stages:
        yield Stage(name)

    if plan.llm_messages is None:
        # Переспрос, отказ по квоте и превышение тарифного лимита сравнения —
        # штатные ответы за ноль токенов, а не деградация (§1.1). Через поток они
        # идут одной дельтой: интерфейсу не нужно различать сценарии.
        yield Delta(plan.answer or "")
        outcome = {"answer": plan.answer or "", REPLY_TOKENS: tokens.estimate(plan.answer or "")}
        async for event in _finish(plan, outcome):
            yield event
        return

    if _will_wait(plan):
        # На бесплатном ключе ожидание окна — самая длинная пауза за ход, и без
        # явного события интерфейс молчит дольше всего именно когда всё штатно.
        yield Stage(STAGE_WAITING_LIMIT)
    yield Stage(STAGE_LLM)

    streamed: list[str] = []
    result: llm.Result | None = None
    failure: str | None = None
    async for event in llm.stream(
        plan.llm_messages, plan.schema, get_settings().llm_tpm_limit, plan.expected_completion
    ):
        if isinstance(event, llm.Delta):
            streamed.append(event.text)
            yield Delta(event.text)
        elif isinstance(event, llm.Failure):
            failure = event.detail
            break
        else:
            result = event

    if result is None:
        detail = failure or "Модель не вернула ответ."
        if streamed:
            # Дельты уже на экране: обрывать фразу нельзя, склеиваем начатое
            # с детерминированным отчётом и сохраняем ровно то, что видел человек.
            yield Error(detail)
            tail = _fallback_text(plan)
            yield Delta(INTERRUPTED + tail)
            outcome = _degraded(plan, detail, prefix="".join(streamed) + INTERRUPTED)
        else:
            outcome = _degraded(plan, detail)
            yield Delta(outcome["answer"])
        async for event in _finish(plan, outcome):
            yield event
        return

    yield Stage(STAGE_REPAIR)
    outcome = _outcome(plan, result)
    appended = outcome["answer"][len("".join(streamed)) :]
    if appended:
        # Дописка расхождений детерминированная и короткая — уходит отдельной
        # дельтой перед done, разрыва в чтении она не создаёт (§13.6).
        yield Delta(appended)
    async for event in _finish(plan, outcome):
        yield event


async def _finish(plan: _Plan, outcome: dict[str, Any]) -> AsyncIterator[TurnEvent]:
    """Третья фаза: своя сессия, коммит, и только потом done (§13.5).

    Порядок обязателен: отправить done раньше коммита значит показать человеку
    текст, которого нет в истории и который он не найдёт после перезагрузки.
    """
    yield Stage(STAGE_PERSIST)
    payload = await anyio.to_thread.run_sync(lambda: _persist(plan, outcome))
    yield Done(payload)


def _prepare(
    session_id: UUID,
    user_id: UUID,
    message: str,
    buttons: list[str] | None,
    role_preset: str | None,
) -> _Plan:
    """Первая фаза на своей сессии: маршрут, префетч, вердикт, контекст, вопрос в историю."""
    with db_session() as session:
        user = client_repository.get_user(session, user_id)
        if user is None:
            raise TurnError(401, "Пользователь не найден.")
        chat = client_repository.get_session(session, session_id, user_id=user_id)
        if chat is None:
            raise TurnError(404, "Сессия не найдена.")
        if role_preset and role_preset != chat.role_preset:
            client_repository.update_session_role(session, chat, role_preset)

        profile = profile_for(user.tariff)
        quota = client_repository.get_quota(session, user_id)
        last = analyses_repository.last_for_session(session, chat.id)
        route = agent_router.choose(
            message,
            has_context=last is not None,
            requests_used=quota.requests_used if quota else 0,
            requests_limit=quota.requests_limit if quota else profile.requests_limit,
            max_compare=profile.max_compare,
        )
        if route.error:
            raise TurnError(422, route.error)

        plan = _Plan(
            scenario=route.scenario,
            needs_llm=route.needs_llm,
            profile=profile,
            session_id=chat.id,
            user_id=user_id,
            role_preset=chat.role_preset,
            message=message,
        )
        if route.scenario == agent_router.ANALYZE:
            _plan_analyze(session, plan, route.inns[0], buttons)
        elif route.scenario == agent_router.COMPARE:
            _plan_compare(session, plan, route.inns)
        elif route.scenario == agent_router.CLARIFY:
            _plan_clarify(session, plan, last)
        else:
            plan.answer = route.answer

        history_repository.add_message(
            session,
            session_id=chat.id,
            role="user",
            content=message,
            # Точного значения на реплику пользователя не существует: в usage она входит
            # слагаемым prompt_tokens вместе со всем остальным запросом (§4.3).
            tokens=tokens.estimate(message),
        )
        return plan


def _plan_analyze(session: Session, plan: _Plan, inn: str, buttons: list[str] | None) -> None:
    pack = factpack.build(session, inn, mode=plan.profile.factpack_mode, role=plan.role_preset)
    if pack is None:
        raise TurnError(404, "Контрагента с таким ИНН в базе нет.")

    decision = verdicts.decide(pack)
    sets = prefetch.collect(buttons or (), pack["inn"], plan.profile.max_buttons)
    window = context.build(
        session,
        plan.session_id,
        profile=plan.profile,
        system_text=prompts.system(prompts.REPORT_KEYS),
        user_block=prompts.analyze_block(plan.message, decision, pack),
        user_block_tokens=context.user_block_cost(plan.message, plan.profile.factpack_mode),
        # В разборе факт-пакет и так в контексте, якорь дублировал бы его (§4.1).
        with_anchor=False,
        button_sets=sets.data,
    )
    plan.stages = (STAGE_PREFETCH, STAGE_VERDICT, STAGE_CONTEXT)
    plan.pack = pack
    plan.packs = [pack]
    plan.verdict = decision["verdict"]
    plan.baseline = verdicts.apply(report_builder.build(pack), pack)
    plan.contractor = {"inn": pack["inn"], "short_name": pack["short_name"]}
    plan.title = pack["short_name"]
    plan.notice = _sets_notice(sets, window)
    plan.llm_messages = window.messages
    plan.schema = prompts.REPORT_SCHEMA
    plan.expected_completion = get_settings().tokens_expected_completion


def _plan_compare(session: Session, plan: _Plan, inns: tuple[str, ...]) -> None:
    payload = compare_contractors(list(inns), focus=plan.role_preset)
    if not payload["found"]:
        raise TurnError(404, payload["hint"])

    # Пакеты нужны не модели, а коду: вердикт и обязательные упоминания считаются
    # по ним, в промпт уходит сводка сравнения — она короче N пакетов.
    packs = factpack.build_many(session, [row["inn"] for row in payload["matrix"]], role=plan.role_preset)
    decisions = [{"inn": pack["inn"], **verdicts.decide(pack)} for pack in packs]
    block = prompts.compare_block(plan.message, decisions, payload)
    # Наборы кнопок в сравнение не идут: кнопка висит на отчёте одного контрагента
    # (§7.4), а здесь их несколько, и дочитывать набор непонятно по кому.
    window = context.build(
        session,
        plan.session_id,
        profile=plan.profile,
        system_text=prompts.system(prompts.REPORT_KEYS),
        user_block=block,
        user_block_tokens=context.user_block_cost(block),
        with_anchor=True,
    )
    plan.stages = (STAGE_PREFETCH, STAGE_VERDICT, STAGE_CONTEXT)
    plan.packs = packs
    plan.baseline_text = _compare_text(payload, decisions)
    plan.llm_messages = window.messages
    plan.schema = prompts.REPORT_SCHEMA
    plan.expected_completion = get_settings().tokens_expected_completion


def _plan_clarify(session: Session, plan: _Plan, last: Any) -> None:
    pack = last.report or {}
    # Снимок вместо ORM-объекта: во второй фазе сессии, из которой он пришёл, уже нет.
    plan.last = {
        "inn": last.inn,
        "verdict": last.verdict,
        "summary": last.summary,
        "analysis": last.analysis,
        "report": pack or None,
    }
    plan.contractor = {"inn": last.inn, "short_name": pack.get("short_name") or last.inn}
    block = prompts.clarify_block(plan.message)
    # Кнопки здесь игнорируются: набор висит на свежем разборе, а уточнение
    # его не делает — дочитывать данные не к чему приложить.
    window = context.build(
        session,
        plan.session_id,
        profile=plan.profile,
        system_text=prompts.system(prompts.REPLY_KEYS),
        user_block=block,
        user_block_tokens=context.user_block_cost(block),
        with_anchor=True,
    )
    plan.stages = (STAGE_CONTEXT,)
    plan.llm_messages = window.messages
    plan.schema = prompts.REPLY_SCHEMA
    plan.expected_completion = get_settings().tokens_expected_completion // CLARIFY_COMPLETION_DIVISOR


def _will_wait(plan: _Plan) -> bool:
    """Придётся ли лимитеру ждать освобождения окна.

    Момент ожидания живёт внутри `limiter.reserve()`, наружу он не сигналится,
    а править коннектор ради подсказки интерфейсу — плохой обмен. Поэтому
    оцениваем то же условие снаружи: оценка запроса плюс ожидаемый ответ против
    свободного остатка минутного окна.
    """
    settings = get_settings()
    text = "".join(str(item.get("content") or "") for item in plan.llm_messages or ())
    need = tokens.estimate(text) + plan.expected_completion
    return limiter.get_limiter(settings.llm_tpm_limit).used + need > settings.llm_tpm_limit


def _outcome(plan: _Plan, result: llm.Result) -> dict[str, Any]:
    """Исход хода из ответа модели. Чистая функция: БД здесь нет."""
    if plan.scenario == agent_router.CLARIFY:
        last = plan.last or {}
        answer = _text(result.data, prompts.ANSWER) or last.get("summary") or ""
        # §1.2: уточнение не рождает новый отчёт, поэтому analyses не трогаем,
        # а поля отчёта отдаём прежние — панель разбора не должна опустеть.
        return {
            "answer": answer,
            "verdict": last.get("verdict"),
            "summary": last.get("summary"),
            "analysis": last.get("analysis"),
            "report": last.get("report"),
            "contractor": plan.contractor,
            "degraded": False,
            REPLY_TOKENS: _completion(result.usage, answer),
        }

    if plan.scenario == agent_router.COMPARE:
        baseline = plan.baseline_text or ""
        answer = _repair(_text(result.data, prompts.ANSWER) or baseline, plan.packs)
        return {
            "answer": answer,
            "summary": _text(result.data, prompts.SUMMARY),
            "analysis": _with_risks(_text(result.data, prompts.ANALYSIS) or baseline, result.data),
            "degraded": False,
            "notice": PARTIAL_NOTICE if result.problems else None,
            REPLY_TOKENS: _completion(result.usage, answer),
        }

    baseline = plan.baseline or {}
    answer = _repair(_text(result.data, prompts.ANSWER) or baseline["summary"], plan.packs)
    summary = _text(result.data, prompts.SUMMARY) or baseline["summary"]
    analysis = _with_risks(_text(result.data, prompts.ANALYSIS) or baseline["analysis"], result.data)
    return {
        "answer": answer,
        "verdict": plan.verdict,
        "summary": summary,
        "analysis": analysis,
        "report": plan.pack,
        "contractor": plan.contractor,
        "degraded": False,
        "notice": _join(plan.notice, PARTIAL_NOTICE if result.problems else None),
        REPLY_TOKENS: _completion(result.usage, answer),
    }


def _fallback_text(plan: _Plan) -> str:
    if plan.scenario == agent_router.COMPARE:
        return plan.baseline_text or ""
    if plan.scenario == agent_router.CLARIFY:
        last = plan.last or {}
        name = (plan.contractor or {}).get("short_name")
        return (
            f"Отвечаю по последнему разбору — {name} (ИНН {last.get('inn')}).\n\n"
            f"{last.get('summary')}\n\n{last.get('analysis')}"
        )
    baseline = plan.baseline or {}
    return f"{baseline.get('summary')}\n\n{baseline.get('analysis')}"


def _degraded(plan: _Plan, detail: str, prefix: str = "") -> dict[str, Any]:
    """Детерминированный отчёт вместо ошибки (§6.2).

    `prefix` непуст, когда отказ пришёл после первой дельты: сохраняем склейку
    целиком — история обязана совпадать с тем, что было на экране (§13.6).
    """
    answer = prefix + _fallback_text(plan)
    notice = f"{detail} {DEGRADED_TAIL}"
    if plan.scenario == agent_router.COMPARE:
        return {"answer": answer, "degraded": True, "notice": notice,
                REPLY_TOKENS: tokens.estimate(answer)}
    if plan.scenario == agent_router.CLARIFY:
        last = plan.last or {}
        return {
            "answer": answer,
            "verdict": last.get("verdict"),
            "summary": last.get("summary"),
            "analysis": last.get("analysis"),
            "report": last.get("report"),
            "contractor": plan.contractor,
            "degraded": True,
            "notice": notice,
            REPLY_TOKENS: tokens.estimate(answer),
        }
    baseline = plan.baseline or {}
    # Про наборы здесь молчим: модель не вызывалась, ни один набор в ход не пошёл,
    # и разбирать причины их отсева пользователю сейчас незачем.
    return {
        "answer": answer,
        "verdict": baseline.get("verdict"),
        "summary": baseline.get("summary"),
        "analysis": baseline.get("analysis"),
        "report": baseline.get("report"),
        "contractor": plan.contractor,
        "degraded": True,
        "notice": notice,
        REPLY_TOKENS: tokens.estimate(answer),
    }


def _persist(plan: _Plan, outcome: dict[str, Any]) -> dict[str, Any]:
    """Третья фаза на своей сессии: ответ, analyses, квота, заголовок. Коммитит."""
    reply_tokens = outcome.pop(REPLY_TOKENS, None)
    with db_session() as session:
        chat = client_repository.get_session(session, plan.session_id)
        if plan.title:
            client_repository.set_session_title(session, chat, plan.title)
        if plan.pack is not None:
            # Отчёт сохраняется и при отказе модели: иначе якорь останется пустым
            # и следующий вопрос без ИНН уйдёт в переспрос вместо уточнения (§1.2).
            analyses_repository.save(
                session,
                session_id=plan.session_id,
                inn=plan.pack["inn"],
                analysis_type=plan.role_preset,
                verdict=plan.verdict,
                summary=outcome.get("summary") or (plan.baseline or {}).get("summary"),
                report=plan.pack,
                analysis=outcome.get("analysis") or (plan.baseline or {}).get("analysis"),
            )
        # факт-пакет в историю не кладём: он живёт в analyses, а окно контекста его вырезает
        history_repository.add_message(
            session,
            session_id=plan.session_id,
            role="assistant",
            content=outcome["answer"],
            tokens=reply_tokens if reply_tokens is not None else tokens.estimate(outcome["answer"]),
            meta={
                "scenario": plan.scenario,
                "inn": (outcome.get("contractor") or {}).get("inn"),
                "degraded": outcome.get("degraded", False),
            },
        )
        if plan.needs_llm:
            # Детерминированные отказы квоту не тратят: они не обращаются к поставщику.
            client_repository.record_request(
                session, plan.user_id, report_generated=plan.scenario == agent_router.ANALYZE
            )
        messages = _turn_messages(session, plan.session_id)
        return {**outcome, "session": chat, "messages": messages}


def _turn_messages(session: Session, session_id: UUID) -> list[Message]:
    """Пара «вопрос-ответ» этого хода: вопрос записан первой фазой, ответ — только что."""
    return history_repository.last_messages(session, session_id, 2)


def _sets_notice(sets: prefetch.Prefetched, window: context.Window) -> str | None:
    """Плашка про недочитанные наборы.

    Причины отсева две и они разные. Потолок тарифа объясняет `Prefetched.notice`,
    а бюджет окна — нет: сказать «на вашем тарифе» про набор, который срезала
    длина запроса, значит назвать пользователю неверную причину.
    """
    budget = None
    if window.dropped_sets:
        labels = ", ".join(prefetch.LABELS.get(name, name) for name in window.dropped_sets)
        budget = f"Не поместились в контекст хода: {labels} — отметьте их следующим сообщением по одному."
    return _join(sets.notice, budget)


def _join(*parts: str | None) -> str | None:
    joined = " ".join(part for part in parts if part)
    return joined or None


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
