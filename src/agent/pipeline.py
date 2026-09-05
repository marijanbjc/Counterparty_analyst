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

import json
import logging
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import anyio.to_thread
from sqlalchemy.orm import Session

from src.agent import catalog, context, dispatcher, limiter, llm, prefetch, prompts, sanitize
from src.agent import router as agent_router
from src.agent import tokens, verdicts
from src.agent.profiles import ExecutionProfile, profile_for
from src.config.settings import get_settings
from src.core import factpack
from src.core import inn as inn_module
from src.core import nextsteps
from src.core import report as report_builder
from src.core import validation
from src.db.analyses import repository as analyses_repository
from src.db.client import repository as client_repository
from src.db.engine import db_session
from src.db.history import repository as history_repository
from src.db.models import Message
from src.mcp import toolsets
from src.mcp.advanced.analysis import BUILDERS, run_focused_analysis
from src.mcp.advanced.questions import draft_followup_questions
from src.mcp.tools.selection import compare_contractors

# Ответ на уточнение короче разбора, но не втрое: с делителем 3 модель обрывала
# ответ на общей фразе вместо разбора конкретного вопроса (§9). Второго ключа
# в конфиге не заводим: величина производная, а не настраиваемая.
CLARIFY_COMPLETION_DIVISOR = 2

# Служебный ключ outcome: фактический расход ответа, который _persist снимает
# и кладёт в messages.tokens. В ChatResponse он не уходит — только в историю,
# чтобы следующая сборка контекста считала старые реплики по факту, а не оценкой.
REPLY_TOKENS = "_reply_tokens"

logger = logging.getLogger(__name__)

DEGRADED_TAIL = "Ниже — данные отчёта без ИИ-разбора."
PARTIAL_NOTICE = "Модель прислала не весь текст — недостающее дописано по данным отчёта."
INTERRUPTED = "\n\nИИ-анализ прерван, ниже детерминированный отчёт.\n\n"

STAGE_PREFETCH = "prefetch"
STAGE_VERDICT = "verdict"
STAGE_CONTEXT = "context"
STAGE_WAITING_LIMIT = "waiting_limit"
STAGE_LLM = "llm"
STAGE_TOOLS = "tools"
STAGE_FOCUSED_PREFIX = "focused_"
STAGE_REPAIR = "repair"
STAGE_PERSIST = "persist"

# Уточнение на базовом профиле идёт БЕЗ инструментов. Со схемами модель тратила
# ход на выбор инструмента и отвечала фрагментом вместо разбора вопроса; без них
# на тех же данных ответ получается полным. Заодно экономятся 1817 токенов (§9).
BASIC_CLARIFY_ROUNDS = 0

# Критерий рейтинга под фокус анализа. Ключи — пресеты роли, значения — критерии
# selection._RANKERS; «риск» остаётся значением по умолчанию для всего остального.
_RANK_BY = {"finance": "revenue", "legal": "debt_burden", "activity": "age"}

# Регулярка «упомянуто?» вместо валидатора: не нашлось — дописываем готовую строку
# из самого расхождения, ноль токенов и без перегенерации (§6.3).
# Шаблоны широкие намеренно: узкое слово ловило только буквальное совпадение,
# и дописка повторяла своими словами то, что модель уже сказала другими —
# «совокупность правовых проблем» и «формально низкий риск при 6 негативных
# факторах» стояли рядом об одном и том же (§9). Лучше промолчать о том, что
# сказано иначе, чем сказать дважды: критический статус всё равно подстрахован
# отдельным маркером.
_DISCREPANCY_MARKERS = {
    "green_but_execproc": r"исполнительн|взыскан|пристав",
    "green_but_negative": r"негативн|фактор|несоответств|расхожден|правов\w+ проблем",
    "many_closed_execproc": r"исполнительн|взыскан|пристав",
    "traffic_lights_disagree": r"ЗСК|светофор",
    "unknown_risk": r"не\s+смог|не\s+определ|неизвест|нет\s+оценк",
    "no_financials": r"отч[её]тност|финансов|выручк|баланс",
}
# Правило 5 §9 требует назвать не только расхождения, но и критический правовой
# статус, а он живёт вне discrepancies — иначе банкротство теряется молча.
_LEGAL_MARKERS = {
    "bankruptcy": r"банкрот|конкурсн|несостоятельн|ликвидац",
    "pending_exclusion": r"исключени|прекращени",
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
    llm_messages: list[dict] | None = None
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
    tool_rounds: int = 0
    tool_names: list[str] = field(default_factory=list)
    allowed_inns: tuple[str, ...] = ()
    followups: list[dict[str, Any]] = field(default_factory=list)
    # Наборы, которые реально дочитались за этот ход: интерфейсу нужно показать,
    # что кнопка сработала. Без этого у контрагента с пустым разделом ответ
    # выглядел неотличимо от обычного, и кнопка казалась сломанной.
    applied_sets: tuple[str, ...] = ()
    comparison: dict[str, Any] | None = None


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

    streamed: list[str] = []
    # Правило «писать ЗСК, а не ZSK» модель нарушает регулярно, а постобработка
    # ответа запрещена — он уже на экране. Поэтому чистим сам поток (§13.6).
    cleaner = sanitize.StreamCleaner()
    result: llm.Result | None = None
    failure: str | None = None
    messages = list(plan.llm_messages)
    allowed = set(plan.allowed_inns)
    names = list(plan.tool_names)
    remaining = plan.tool_rounds
    loaded: tuple[str, ...] = ()
    called_any = False

    while result is None and failure is None:
        use_tools = remaining > 0 and bool(names)
        tools_payload = catalog.openai_tools(names) if use_tools else None
        schema = None if use_tools else plan.schema
        if _request_tokens(messages, tools_payload) > plan.profile.budget_tokens:
            failure = "Контекст инструментов превысил бюджет хода."
            break
        if _will_wait(plan, messages, tools_payload):
            yield Stage(STAGE_WAITING_LIMIT)
        yield Stage(STAGE_LLM)
        called = False
        async for event in llm.stream(
            messages, schema, plan.profile.tpm_limit, plan.expected_completion, tools=tools_payload
        ):
            if isinstance(event, llm.ToolCalls):
                if not use_tools:
                    failure = "Модель вызвала инструмент вне разрешённого цикла."
                    break
                yield Stage(STAGE_TOOLS)
                messages, allowed, loaded, names = await _apply_tool_calls(
                    messages, event, allowed, loaded, plan, set(names)
                )
                plan.allowed_inns = tuple(sorted(allowed))
                remaining -= 1
                called_any = True
                next_tools = catalog.openai_tools(names) if remaining > 0 and names else None
                _compact_tool_results(messages, next_tools, plan.profile.budget_tokens)
                called = True
                break
            if isinstance(event, llm.Delta):
                # После tool_call буферизуем финальную реплику до проверки ИНН:
                # иначе неизвестный ИНН уже окажется на экране до валидации.
                if plan.scenario != agent_router.CLARIFY and not called_any:
                    text = cleaner.feed(event.text)
                    if text:
                        streamed.append(text)
                        yield Delta(text)
            elif isinstance(event, llm.Failure):
                failure = event.detail
                break
            else:
                result = event
                break
        # Придержанный хвост обязан уйти на экран: без него ответ обрывается
        # на два символа, а история перестаёт совпадать с показанным (§13.6).
        tail = cleaner.flush()
        if tail:
            streamed.append(tail)
            yield Delta(tail)
        if called:
            continue
        break

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
            requests_limit=profile.requests_limit,
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
            _plan_analyze(session, plan, route.inns[0])
        elif route.scenario == agent_router.COMPARE:
            _plan_compare(session, plan, route.inns)
        elif route.scenario == agent_router.CLARIFY:
            _plan_clarify(session, plan, last, buttons)
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


def _plan_analyze(session: Session, plan: _Plan, inn: str) -> None:
    """Первичный разбор — всегда базовый: факт-пакет и ничего сверху (§8).

    Наборы сюда не прикладываются намеренно. Складываясь с факт-пакетом, они
    давали 7848 токенов при бюджете 6400, и у 31 сочетания из 500 набор молча
    отваливался — кнопка срабатывала на лёгком контрагенте и не срабатывала
    на тяжёлом. Объяснить это клиенту нельзя, поэтому углублённые разборы
    вынесены на следующий ход, где факт-пакета в промпте уже нет.
    """
    pack = factpack.build(session, inn, mode=plan.profile.factpack_mode)
    if pack is None:
        raise TurnError(404, "Контрагента с таким ИНН в базе нет.")

    decision = verdicts.decide(pack)
    _configure_tools(session, plan, (pack["inn"],))
    focused = _focused_blocks(pack["inn"], plan)
    window = context.build(
        session,
        plan.session_id,
        profile=plan.profile,
        system_text=prompts.system(
            prompts.REPORT_KEYS, role=plan.role_preset, with_tools=plan.tool_rounds > 0
        ),
        user_block=(block := prompts.analyze_block(plan.message, decision, pack)),
        user_block_tokens=context.user_block_cost(block),
        # В разборе факт-пакет и так в контексте, якорь дублировал бы его (§4.1).
        with_anchor=False,
        extra_blocks=focused or None,
        tools_scope=_tools_scope(plan),
    )
    plan.stages = (
        STAGE_PREFETCH,
        STAGE_VERDICT,
        *(f"{STAGE_FOCUSED_PREFIX}{name}" for name in focused),
        STAGE_CONTEXT,
    )
    plan.pack = pack
    plan.packs = [pack]
    plan.verdict = decision["verdict"]
    plan.baseline = verdicts.apply(report_builder.build(pack), pack)
    plan.contractor = {"inn": pack["inn"], "short_name": pack["short_name"]}
    plan.title = pack["short_name"]
    plan.llm_messages = window.messages
    plan.schema = prompts.REPORT_SCHEMA
    plan.expected_completion = get_settings().tokens_expected_completion
    # Список «что запросить» детерминирован и нужен интерфейсу, а не модели:
    # в промпт он не уходит и токенов хода не занимает (ARCHITECTURE.md).
    questions = draft_followup_questions(pack["inn"])
    plan.followups = questions.get("items") or [] if questions.get("found") else []


def _plan_compare(session: Session, plan: _Plan, inns: tuple[str, ...]) -> None:
    # rank_by обязателен: без него _ranking возвращает пустой список, и на вопрос
    # «кто лучше» модели просто нечем отвечать. Критерий по умолчанию — риск,
    # фокус анализа его уточняет (ARCHITECTURE.md).
    payload = compare_contractors(
        list(inns), focus=plan.role_preset, rank_by=_RANK_BY.get(plan.role_preset, "risk")
    )
    if not payload["found"]:
        raise TurnError(404, payload["hint"])

    # Пакеты нужны не модели, а коду: вердикт и обязательные упоминания считаются
    # по ним, в промпт уходит сводка сравнения — она короче N пакетов.
    packs = factpack.build_many(
        session,
        [row["inn"] for row in payload["matrix"]],
        mode=plan.profile.factpack_mode,
    )
    decisions = [{"inn": pack["inn"], **verdicts.decide(pack)} for pack in packs]
    block = prompts.compare_block(plan.message, decisions, payload)
    # Наборы кнопок в сравнение не идут: кнопка висит на отчёте одного контрагента
    # (§7.4), а здесь их несколько, и дочитывать набор непонятно по кому.
    _configure_tools(session, plan, tuple(row["inn"] for row in payload["matrix"]))
    window = context.build(
        session,
        plan.session_id,
        profile=plan.profile,
        system_text=prompts.system(
            prompts.COMPARE_KEYS, role=plan.role_preset, with_tools=plan.tool_rounds > 0
        ),
        user_block=block,
        user_block_tokens=context.user_block_cost(block),
        with_anchor=True,
        tools_scope=_tools_scope(plan),
    )
    plan.stages = (STAGE_PREFETCH, STAGE_VERDICT, STAGE_CONTEXT)
    plan.packs = packs
    plan.comparison = {**prompts.compare_summary(payload), "verdicts": decisions}
    plan.baseline_text = _compare_text(payload, decisions)
    plan.llm_messages = window.messages
    plan.schema = prompts.COMPARE_SCHEMA
    plan.expected_completion = get_settings().tokens_expected_completion


def _plan_clarify(session: Session, plan: _Plan, last: Any, buttons: list[str] | None) -> None:
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
    _configure_tools(session, plan, (last.inn,))
    # Углублённые наборы живут ЗДЕСЬ, а не на первичном разборе (§8): там они
    # складывались с факт-пакетом и не влезали в бюджет. ИНН берётся из якоря
    # сессии — вводить его заново клиенту не нужно.
    sets = prefetch.collect(buttons or (), last.inn, plan.profile.max_buttons)
    if sets.data:
        # Схемы инструментов вместе с набором снова упирают ход в потолок
        # (1817 + 2898 + системная часть > бюджета). Данные уже в промпте,
        # дозапрашивать нечего.
        plan.tool_rounds = 0
        plan.tool_names = []
    block = prompts.clarify_block(plan.message, with_tools=plan.tool_rounds > 0)
    window = context.build(
        session,
        plan.session_id,
        profile=plan.profile,
        system_text=prompts.system(
            prompts.REPLY_KEYS, role=plan.role_preset, with_tools=plan.tool_rounds > 0
        ),
        user_block=block,
        user_block_tokens=context.user_block_cost(block),
        with_anchor=True,
        button_sets=sets.data,
        tools_scope=_tools_scope(plan),
    )
    plan.notice = _sets_notice(sets, window)
    plan.applied_sets = tuple(name for name in sets.data if name not in window.dropped_sets)
    plan.stages = (STAGE_PREFETCH, STAGE_CONTEXT) if sets.data else (STAGE_CONTEXT,)
    plan.llm_messages = window.messages
    plan.schema = prompts.REPLY_SCHEMA
    plan.expected_completion = get_settings().tokens_expected_completion // CLARIFY_COMPLETION_DIVISOR


def _will_wait(plan: _Plan, messages: list[dict] | None = None, tools: list[dict] | None = None) -> bool:
    """Придётся ли лимитеру ждать освобождения окна.

    Момент ожидания живёт внутри `limiter.reserve()`, наружу он не сигналится,
    а править коннектор ради подсказки интерфейсу — плохой обмен. Поэтому
    оцениваем то же условие снаружи: оценка запроса плюс ожидаемый ответ против
    свободного остатка минутного окна.
    """
    payload = messages if messages is not None else plan.llm_messages or ()
    need = _request_tokens(payload, tools) + plan.expected_completion
    tpm = plan.profile.tpm_limit
    return limiter.get_limiter(tpm).used + need > tpm


def _request_tokens(messages: list[dict], tools: list[dict] | None) -> int:
    """Оценка запроса той же мерой, что и бюджет в context.build — по содержимому.

    Дамп всего конверта считать нельзя: факт-пакет уходит в content строкой,
    и при повторной сериализации каждая кавычка внутри него превращается в \",
    добавляя сотни символов. Расхождение доходило до 350 токенов, и ход, честно
    уложившийся в бюджет при сборке, падал на этой проверке в деградацию.
    Вызовы инструментов считаются отдельно: их в content нет.
    """
    total = 0
    for message in messages:
        total += tokens.estimate(str(message.get("content") or ""))
        for call in message.get("tool_calls") or []:
            function = call.get("function") or {}
            total += tokens.estimate(f"{function.get('name', '')}{function.get('arguments', '')}")
    if tools:
        total += tokens.estimate(json.dumps(tools, ensure_ascii=False))
    return total


def _compact_tool_results(
    messages: list[dict],
    tools: list[dict] | None,
    budget: int,
) -> None:
    """Заменяет слишком большие tool-ответы явной пометкой, не режет JSON."""
    replacement = json.dumps(
        {
            "found": False,
            "reason": "tool_result_too_large",
            "hint": "Данных оказалось слишком много для одного ответа. Уточните запрос.",
        },
        ensure_ascii=False,
    )
    indices = sorted(
        (index for index, item in enumerate(messages) if item.get("role") == "tool"),
        key=lambda index: len(str(messages[index].get("content") or "")),
        reverse=True,
    )
    for index in indices:
        if _request_tokens(messages, tools) <= budget:
            return
        messages[index]["content"] = replacement


def _outcome(plan: _Plan, result: llm.Result) -> dict[str, Any]:
    """Исход хода из ответа модели. Чистая функция: БД здесь нет."""
    generated = "\n".join(
        str(result.data.get(key) or "")
        for key in (prompts.ANSWER, prompts.SUMMARY, prompts.ANALYSIS, prompts.KEY_RISKS)
    )
    if plan.scenario == agent_router.CLARIFY:
        check = validation.validate(generated, {"allowed_inns": plan.allowed_inns})
        if any(item.get("rule") == validation.UNKNOWN_INN for item in check["violations"]):
            return _degraded(plan, "Модель сослалась на ИНН вне текущей сессии.")

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
            # Подсказки нужны и после уточнения: без них клиент, дочитавший
            # финансы, снова упирался в тупик и должен был придумывать вопрос сам.
            "next_steps": nextsteps.for_report(
                last.get("report") or {}, last.get("verdict"), plan.applied_sets
            ),
            "notice": plan.notice,
            **_badge(last.get("report")),
            REPLY_TOKENS: _completion(result.usage, answer),
        }

    if plan.scenario == agent_router.COMPARE:
        baseline = plan.baseline_text or ""
        answer = _repair(_text(result.data, prompts.ANSWER) or baseline, plan.packs)
        return {
            "answer": answer,
            "summary": _text(result.data, prompts.SUMMARY),
            "analysis": _text(result.data, prompts.ANALYSIS) or baseline,
            "per_contractor": _per_contractor(result.data, plan.packs),
            "comparison": plan.comparison,
            "next_steps": nextsteps.for_compare(plan.packs),
            "degraded": False,
            "notice": _partial_notice(
                result, _text(result.data, prompts.ANSWER), _text(result.data, prompts.ANALYSIS)
            ),
            REPLY_TOKENS: _completion(result.usage, answer),
        }

    baseline = plan.baseline or {}
    answer = _repair(_text(result.data, prompts.ANSWER) or baseline["summary"], plan.packs)
    summary = _text(result.data, prompts.SUMMARY) or baseline["summary"]
    analysis = _text(result.data, prompts.ANALYSIS) or baseline["analysis"]
    return {
        "answer": answer,
        "verdict": plan.verdict,
        "summary": summary,
        "analysis": analysis,
        "report": plan.pack,
        "contractor": plan.contractor,
        "key_risks": _strings(result.data, prompts.KEY_RISKS) or _fallback_risks(plan.packs),
        "positives": _strings(result.data, prompts.POSITIVES),
        "followups": plan.followups,
        "next_steps": nextsteps.for_report(plan.pack, plan.verdict),
        **_badge(plan.pack),
        "degraded": False,
        "notice": _join(
            plan.notice,
            _partial_notice(
                result, _text(result.data, prompts.ANSWER), _text(result.data, prompts.ANALYSIS)
            ),
        ),
        REPLY_TOKENS: _completion(result.usage, answer),
    }


def _partial_notice(result: llm.Result, *visible: str | None) -> str | None:
    """Пометка о неполном ответе — только когда пропажу видно пользователю.

    Хвостовые поля код дозаполняет детерминированно (§6.3), и на экране почти
    всегда полный разбор: техническая тревога поверх него пугала на ровном месте
    (§15.4). Само расхождение уходит в лог — по нему видно, что уронила модель.
    """
    if not result.problems:
        return None
    logger.warning("ответ модели разошёлся со схемой: %s", "; ".join(result.problems))
    return None if all(visible) else PARTIAL_NOTICE


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
                "per_contractor": _per_contractor({}, plan.packs), "comparison": plan.comparison,
                "next_steps": nextsteps.for_compare(plan.packs),
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
            "next_steps": nextsteps.for_report(
                last.get("report") or {}, last.get("verdict"), plan.applied_sets
            ),
            "notice": notice,
            "key_risks": [],
            "positives": [],
            **_badge(last.get("report")),
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
        "key_risks": _fallback_risks(plan.packs),
        "positives": [],
        "followups": plan.followups,
        "next_steps": nextsteps.for_report(plan.pack, plan.verdict) if plan.pack else [],
        **_badge(plan.pack),
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
        elif plan.scenario == agent_router.COMPARE:
            _persist_comparison(session, plan)
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
                # Имя в шапке сообщения: без него уточняющий ответ выглядит
                # безадресным — по какому из проверенных он, неясно.
                "subject": (outcome.get("contractor") or {}).get("short_name"),
                "degraded": outcome.get("degraded", False),
                # Структурные блоки кладутся в историю целиком: после перезагрузки
                # страницы сообщение обязано выглядеть так же, как в момент ответа.
                "verdict": outcome.get("verdict"),
                "risk_level": outcome.get("risk_level"),
                "zsk_risk_level": outcome.get("zsk_risk_level"),
                "key_risks": outcome.get("key_risks") or [],
                "positives": outcome.get("positives") or [],
                "per_contractor": outcome.get("per_contractor") or [],
                "followups": outcome.get("followups") or [],
                # Подсказки следующего шага собраны кодом и стоят ноль токенов;
                # в историю кладутся вместе с остальными блоками, чтобы после
                # перезагрузки сообщение выглядело так же (§4).
                "next_steps": outcome.get("next_steps") or [],
                "datasets": [prefetch.LABELS.get(name, name) for name in plan.applied_sets],
                "comparison": outcome.get("comparison"),
                # Факт-пакет нужен фронту для графиков: ряды берутся из него,
                # отдельных запросов и токенов это не стоит (§10).
                "report": outcome.get("report"),
                # ИНН, возвращённые инструментами, становятся допустимыми и на
                # следующих ходах этой сессии; MCP-функции сами stateless.
                "_allowed_inns": list(plan.allowed_inns),
            },
        )
        if plan.needs_llm:
            # Детерминированные отказы квоту не тратят: они не обращаются к поставщику.
            client_repository.record_request(
                session, plan.user_id, report_generated=plan.scenario == agent_router.ANALYZE
            )
        messages = _turn_messages(session, plan.session_id)
        return {**outcome, "session": chat, "messages": messages}


def _persist_comparison(session: Session, plan: _Plan) -> None:
    """Привязывает каждого участника сравнения, не портя глобальный кэш."""
    for pack in plan.packs:
        existing = analyses_repository.get(session, pack["inn"], plan.role_preset)
        if existing is not None:
            analyses_repository.link_to_session(session, plan.session_id, existing)
            continue
        baseline = verdicts.apply(report_builder.build(pack), pack)
        analyses_repository.save(
            session,
            session_id=plan.session_id,
            inn=pack["inn"],
            analysis_type=plan.role_preset,
            verdict=baseline["verdict"],
            summary=baseline["summary"],
            report=pack,
            analysis=baseline["analysis"],
        )


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
        budget = f"Не успел дочитать: {labels} — отметьте их следующим сообщением по одному."
    focused = None
    if window.dropped_extra_blocks:
        labels = ", ".join(
            prefetch.LABELS.get(name, name) for name in window.dropped_extra_blocks
        )
        focused = f"Не успел углубиться в разбор: {labels}."
    return _join(sets.notice, budget, focused)


def _join(*parts: str | None) -> str | None:
    joined = " ".join(part for part in parts if part)
    return joined or None


def _text(data: dict[str, Any], key: str) -> str | None:
    """Хвостовые поля могли не прийти (Result.problems): ответ пользователю от этого
    не отменяется, недостающее место занимает детерминированный текст.

    Здесь же выравнивается написание «ЗСК»: то же, что делает StreamCleaner
    на дельтах, иначе история разошлась бы с показанным.
    """
    value = data.get(key)
    if not (isinstance(value, str) and value.strip()):
        return None
    return sanitize.zsk(value.strip())


def _strings(data: dict[str, Any], key: str) -> list[str]:
    """Списки для человека: технические вставки вычищаются здесь, а не промптом.
    Промпт частоту снижает, гарантии не даёт (ARCHITECTURE.md)."""
    raw = [item for item in data.get(key) or [] if isinstance(item, str) and item.strip()]
    return sanitize.lines(raw)


def _per_contractor(data: dict[str, Any], packs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Списки по каждому контрагенту сравнения (§9).

    Порядок и состав задаёт код по packs, а не модель: пропущенного она не добавит,
    лишнего не припишет. Не названные ею риски заполняются детерминированно.
    """
    # Только цифры: модель возвращала ИНН и с пробелами, и числом. Позиционного
    # запасного варианта здесь нет намеренно — приписать риски не тому
    # контрагенту хуже, чем показать, что по нему модель ничего не назвала.
    by_inn = {
        re.sub(r"\D", "", str(item.get("inn") or "")): item
        for item in data.get(prompts.CONTRACTORS) or []
        if isinstance(item, dict)
    }
    rows = []
    for pack in packs:
        answer = by_inn.get(pack["inn"], {})
        required = [text for _pattern, text in _required_mentions(pack)]
        rows.append(
            {
                "inn": pack["inn"],
                "short_name": pack["short_name"],
                "key_risks": _strings(answer, prompts.KEY_RISKS) or required,
                "positives": _strings(answer, prompts.POSITIVES),
            }
        )
    return rows


def _badge(pack: dict[str, Any] | None) -> dict[str, Any]:
    """Светофоры для шапки сообщения: без них вердикт виден только в досье справа."""
    basis = (pack or {}).get("verdict_basis") or {}
    return {"risk_level": basis.get("risk_level"), "zsk_risk_level": basis.get("zsk_risk_level")}


def _fallback_risks(packs: list[dict[str, Any]]) -> list[str]:
    """Риски для деградации: те же обязательные упоминания, что проверяет починка.

    Без них шаблонный ответ терял бы структуру, ради которой всё и делалось.
    """
    risks: list[str] = []
    for pack in packs:
        label = pack["short_name"] if len(packs) > 1 else ""
        risks += [sanitize.join(label, text) for _pattern, text in _required_mentions(pack)]
    return risks


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
        label = pack["short_name"] if len(packs) > 1 else ""
        for pattern, text in _required_mentions(pack):
            if pattern and re.search(pattern, answer, re.IGNORECASE):
                continue
            missing.append(sanitize.join(label, text))
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


# Коды светофоров нельзя показывать клиенту: LOW и GREEN — это имена значений
# источника, а не русский текст. В отчёте без модели строку никто не переписывает,
# поэтому слова подставляются здесь.
_RISK_WORDS = {"LOW": "низкий риск", "MEDIUM": "средний риск", "HIGH": "высокий риск"}
_ZSK_WORDS = {"GREEN": "зелёный", "YELLOW": "жёлтый", "RED": "красный"}


def _compare_text(payload: dict[str, Any], decisions: list[dict[str, Any]]) -> str:
    verdict_by_inn = {item["inn"]: item["verdict"] for item in decisions}
    lines = [f"Сравнение: {len(payload['matrix'])} контрагентов."]
    for row in payload["matrix"]:
        lines.append(
            f"— {row['short_name']} (ИНН {row['inn']}): {_RISK_WORDS.get(row.get('risk_level'), 'риск не определён')}, "
            f"ЗСК {_ZSK_WORDS.get(row.get('zsk_risk_level'), 'не определён')}, "
            f"негативных факторов {row.get('negative_factors', 0)}. "
            f"Вердикт: {verdict_by_inn.get(row['inn'], 'не определён')}."
        )
    # Блок различий убран: вперемешку с построчной сводкой он читался тяжело,
    # а те же числа стоят рядом в таблице сравнения на экране (§9). Дисклеймер
    # «решение остаётся за вами» тоже убран — он и так в сноске к вердикту.
    if payload["not_found"]:
        lines.append(f"Нет в базе: {', '.join(payload['not_found'])}.")
    return "\n".join(lines)


def _tool_rounds(profile: ExecutionProfile, scenario: str) -> int:
    if profile.attach_tools:
        return profile.max_iterations
    if scenario == agent_router.CLARIFY:
        return BASIC_CLARIFY_ROUNDS
    return 0


def _configure_tools(session: Session, plan: _Plan, extra_inns: tuple[str, ...]) -> None:
    plan.tool_rounds = _tool_rounds(plan.profile, plan.scenario)
    if plan.tool_rounds:
        if plan.profile.attach_tools:
            plan.tool_names = toolsets.resolve(plan.role_preset, plan.message)
        else:
            # Базовое уточнение получает только прямые безопасные инструменты.
            # load_tools потребовал бы ещё двух LLM-шагов (загрузка → вызов →
            # ответ), а run_focused_analysis запрещён границей профиля.
            plan.tool_names = [
                name
                for name in toolsets.CORE
                if name not in {"load_tools", "run_focused_analysis"}
            ]
    inns = set(extra_inns)
    inns.update(inn_module.extract(plan.message))
    for analysis, _contractor in analyses_repository.list_for_session(session, plan.session_id):
        inns.add(analysis.inn)
    inns.update(history_repository.allowed_inns(session, plan.session_id))
    plan.allowed_inns = tuple(inns)


def _tools_scope(plan: _Plan) -> str | None:
    if plan.tool_rounds <= 0:
        return None
    names = set(plan.tool_names)
    core = set(toolsets.CORE)
    if names <= core:
        return "core"
    if any(names <= core | set(area_names) for area_names in toolsets.AREAS.values()):
        return "role"
    # Роль и ключевые слова могут одновременно открыть несколько областей.
    # Для такой комбинации отдельной замеренной константы нет — резервируем
    # безопасную верхнюю границу полного каталога.
    return "all"


def _focused_blocks(inn: str, plan: _Plan) -> dict[str, Any]:
    if not plan.profile.allow_subagents:
        return {}
    names = list(BUILDERS) if plan.role_preset not in BUILDERS else [plan.role_preset]
    return {name: run_focused_analysis(inn, name) for name in names}


async def _apply_tool_calls(
    messages: list[dict],
    event: llm.ToolCalls,
    allowed: set[str],
    loaded: tuple[str, ...],
    plan: _Plan,
    permitted: set[str],
) -> tuple[list[dict], set[str], tuple[str, ...], list[str]]:
    assistant_calls = []
    tool_messages = []
    current_loaded = loaded
    current_allowed = set(allowed)
    for call in event.calls:
        arguments = dispatcher.parse_arguments(call.get("arguments"))
        payload, harvested, current_loaded = await anyio.to_thread.run_sync(
            lambda: dispatcher.dispatch(
                call.get("name") or "",
                arguments,
                current_allowed,
                current_loaded,
                permitted,
            )
        )
        current_allowed |= harvested
        call_id = call.get("id") or call.get("name") or "call"
        assistant_calls.append(
            {
                "id": call_id,
                "type": "function",
                "function": {
                    "name": call.get("name") or "",
                    "arguments": json.dumps(arguments, ensure_ascii=False),
                },
            }
        )
        tool_messages.append(
            {
                "role": "tool",
                "tool_call_id": call_id,
                "content": json.dumps(payload, ensure_ascii=False, default=str),
            }
        )
    names = toolsets.resolve(plan.role_preset, plan.message, current_loaded)
    updated = [
        *messages,
        {"role": "assistant", "content": event.content, "tool_calls": assistant_calls},
        *tool_messages,
    ]
    return updated, current_allowed, current_loaded, names
