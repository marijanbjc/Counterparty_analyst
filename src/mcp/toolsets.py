"""Какой набор инструментов уходит в промпт — ARCHITECTURE.md"""

import re

CORE = (
    "get_contractor_full",
    "get_legal_status",
    "get_basic_info",
    "get_risk_factors",
    "compare_contractors",
    "run_focused_analysis",
    "build_chart",
    "draft_followup_questions",
    "load_tools",
)

AREAS: dict[str, tuple[str, ...]] = {
    "finance": (
        "get_financials",
        "get_balance_sheet",
        "get_liabilities",
        "get_financial_ratios",
        "get_debt_burden",
    ),
    "legal": ("get_arbitration", "get_execution_proceedings", "get_debt_burden"),
    "security": ("get_fns_flags", "get_ownership", "get_affiliations", "find_similar_contractors"),
    "activity": ("get_activity", "get_licenses", "get_inspections", "get_procurements"),
}

# Роль из интерфейса → предметная область. «Общий» отдаёт всё.
ROLE_AREAS = {"finance": "finance", "legal": "legal", "security": "security", "activity": "activity"}

# Роутер добавляет область по ключевым словам запроса, не спрашивая модель (§10.5).
# Начала слов, а не подстроки: «иск» внутри «рискует» и «счет» внутри «отчет»
# дают ложные срабатывания, поэтому сравнение идёт по границе слова.
ROUTER_KEYWORDS: dict[str, tuple[str, ...]] = {
    "finance": (
        "выручк", "прибыл", "убыт", "доход", "баланс", "актив", "капитал", "долг",
        "задолженн", "обязательств", "рентабельн", "кредит", "зараб", "оборот", "финанс",
        "дебиторк", "кредиторк", "отчетност", "отчётност",
    ),
    "legal": (
        "суд", "арбитраж", "иск", "ответчик", "истец", "пристав",
        "взыскан", "исполнительн", "производств", "спор", "тяжб",
    ),
    "security": (
        "директор", "руководител", "учредител", "владел", "налогов", "фнс",
        "блокиров", "счет", "счёт", "адрес", "реестр", "связанн", "аффилирован",
        "бенефициар", "номинал", "массов",
    ),
    "activity": (
        "оквэд", "деятельност", "лицензи", "разрешен", "проверк", "надзор",
        "тендер", "закупк", "госконтракт", "занимает",
    ),
}

_PATTERNS = {
    area: re.compile(r"\b(?:" + "|".join(words) + r")", re.IGNORECASE)
    for area, words in ROUTER_KEYWORDS.items()
}


def areas_for_text(text: str) -> list[str]:
    return [area for area, pattern in _PATTERNS.items() if pattern.search(text or "")]


def resolve(role: str | None = None, message: str | None = None, loaded: tuple[str, ...] = ()) -> list[str]:
    """Итоговый список имён инструментов для одного шага агента.

    Роль «general» и неизвестная роль отдают весь каталог; в остальных случаях
    ядро дополняется областью роли, областями роутера и уже подгруженными.
    """
    if role not in ROLE_AREAS:
        return all_tools()

    names = list(CORE)
    areas = {ROLE_AREAS[role], *areas_for_text(message or ""), *loaded}
    for area in areas:
        names += [name for name in AREAS.get(area, ()) if name not in names]
    return names


def all_tools() -> list[str]:
    names = list(CORE)
    for area in AREAS.values():
        names += [name for name in area if name not in names]
    return names
