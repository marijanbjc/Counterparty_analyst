"""Сборка контекста по бюджету токенов, а не по числу реплик (§4).

Десять последних сообщений — это от 200 до 20 000 токенов: среди них может оказаться
развёрнутый отчёт. Поэтому окно режется по бюджету профиля, и режется строго в одном
порядке: системный промпт, вердикт с факт-пакетом и якорь сессии не трогаются никогда,
диалог уходит первым и с самых старых реплик.
"""

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from src.agent import tokens
from src.agent.profiles import ExecutionProfile
from src.config.settings import get_settings
from src.db.analyses import repository as analyses_repository
from src.db.history import repository as history_repository
from src.db.models import Analysis, Contractor

ANCHOR_HEADER = "[Разобрано в этой сессии]"
DIALOG_ROLES = frozenset({"user", "assistant"})

_ZSK_LABELS = {"GREEN": "зелёный", "YELLOW": "жёлтый", "RED": "красный"}


def build(
    session: Session,
    session_id: UUID,
    *,
    profile: ExecutionProfile,
    system_text: str,
    user_block: str,
    user_block_tokens: int,
    with_anchor: bool,
) -> list[dict[str, str]]:
    budget = profile.budget_tokens
    head: list[dict[str, str]] = [{"role": "system", "content": system_text}]
    # Замеренная константа — нижняя граница: если текст промпта длиннее замера,
    # верим оценке, иначе бюджет окажется занижен молча.
    spent = max(tokens.system_prompt(), tokens.estimate(system_text)) + user_block_tokens

    if with_anchor:
        text = anchor(session, session_id, attach_tools=profile.attach_tools)
        if text:
            head.append({"role": "system", "content": text})
            spent += tokens.estimate(text)

    dialog = _dialog(session, session_id, room=budget - spent)
    return [*head, *dialog, {"role": "user", "content": user_block}]


def anchor(session: Session, session_id: UUID, attach_tools: bool = False) -> str | None:
    """Компактная сводка разобранного, собранная кодом из analyses (§4.1).

    Решения модели не требует, а значит не может быть забыта: после обрезки окна
    ИНН модель берёт отсюда, а не воспроизводит по памяти.
    """
    limit = get_settings().context_anchor_max_contractors
    rows = analyses_repository.list_for_session(session, session_id)[:limit]
    if not rows:
        return None
    lines = [ANCHOR_HEADER]
    for number, (analysis, contractor) in enumerate(rows, start=1):
        lines.extend(_anchor_entry(number, analysis, contractor, attach_tools))
    return "\n".join(lines)


def _anchor_entry(
    number: int, analysis: Analysis, contractor: Contractor, attach_tools: bool
) -> list[str]:
    pack = analysis.report or {}
    basis = pack.get("verdict_basis") or {}
    zsk = basis.get("zsk_risk_level")
    lines = [
        f"{number}. {contractor.short_name} (ИНН {analysis.inn}) — вердикт: {analysis.verdict}.",
        f"   Риск {basis.get('risk_level') or 'не определён'} / "
        f"ЗСК {_ZSK_LABELS.get(zsk, zsk or 'не определён')}. "
        f"Данные на {pack.get('as_of') or 'неизвестную дату'}.",
    ]
    lines.extend(f"   ! {text}" for text in _critical(pack))
    numbers = _numbers(pack)
    if numbers:
        lines.append(f"   {numbers}")
    if attach_tools:
        # Строка §4.1 полезна только когда схемы инструментов приложены (§4.2):
        # иначе она предлагает модели вызов, которого у неё нет.
        lines.append(f'   Полный отчёт: get_analysis("{analysis.inn}").')
    return lines


def _critical(pack: dict[str, Any]) -> list[str]:
    status = pack.get("legal_status") or {}
    found = []
    if status.get("severity") == "critical" and status.get("status_reason"):
        found.append(f"В ЕГРЮЛ: {status['status_reason']}")
    found.extend(item["text"] for item in pack.get("discrepancies") or [])
    return found


def _numbers(pack: dict[str, Any]) -> str:
    parts = []
    years = (pack.get("financials") or {}).get("years") or []
    latest = next((row for row in reversed(years) if row.get("proceeds") is not None), None)
    if latest:
        parts.append(f"Выручка {latest['year']}: {_millions(latest['proceeds'])}.")
    execution = pack.get("execution_proceedings") or {}
    if execution.get("total"):
        parts.append(
            f"Исп. производства: активных {execution.get('active', 0)}, всего {execution['total']}."
        )
    return " ".join(parts)


def _millions(value: int) -> str:
    return f"{value / 1_000_000:,.1f} млн ₽".replace(",", " ").replace(".", ",")


def _dialog(session: Session, session_id: UUID, room: int) -> list[dict[str, str]]:
    settings = get_settings()
    rows = history_repository.last_messages(session, session_id, settings.context_history_max_messages)
    picked: list[dict[str, str]] = []
    # Идём от свежих к старым и обрываемся на первой не влезшей: старые уходят первыми.
    for message in reversed(rows):
        if message.role not in DIALOG_ROLES:
            continue
        cost = tokens.of_message(message.role, message.content, message.tokens)
        if cost > room:
            break
        room -= cost
        picked.append({"role": message.role, "content": message.content})
    picked.reverse()
    return picked


def user_block_cost(text: str, pack_variant: str | None = None, packs: int = 1) -> int:
    """Факт-пакет меряется замеренной константой, остальное — оценкой (§4.3).

    Обрамление в несколько строк не считается отдельно: оно укрывается запасом 15 %,
    заложенным в саму оценку.
    """
    cost = tokens.estimate(text)
    if pack_variant is not None:
        cost += tokens.fact_pack(pack_variant) * packs
    return cost
