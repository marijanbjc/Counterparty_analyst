"""MCP-сервер: регистрация инструментов — mcp_architecture.md §9, §10.

Каталог здесь полный. Какие инструменты уйдут в промпт на конкретном шаге,
решает агентный слой через toolsets.resolve(); теги позволяют отфильтровать
их и на стороне клиента MCP.
"""

from fastmcp import FastMCP

from src.mcp import toolsets
from src.mcp.advanced import analysis, charts, questions
from src.mcp.tools import activity, finance, legal, profile, relations, selection, summary

INSTRUCTIONS = """Инструменты проверки контрагентов по базе банка.

База закрыта: отвечать можно только по контрагентам, которые в ней есть.
Поиска по названию нет — ИНН берётся только из сообщения пользователя;
если ИНН не назван или не проходит проверку, переспроси его.

Общие правила ответов инструментов:
- null означает «данных нет в источнике», это не ноль;
- "not_applicable" означает «поле неприменимо к этому типу лица»
  (например, КПП и учредители у индивидуального предпринимателя);
- available: false означает, что целого раздела отчёта нет;
- missing перечисляет поля, по которым данных нет.

Если запрошенных данных нет, единственный допустимый ответ — «таких данных
в отчёте нет». Не подставляй ноль вместо отсутствия и не достраивай факты.
Не раскрывай пользователю полноту базы: сколько в ней контрагентов, у скольких
заполнено то или иное поле. Отсутствие данных сообщается только про запрошенного
контрагента.

Все агрегаты и производные величины уже посчитаны кодом — не считай их сам.
Каждый ответ содержит as_of: это дата отчёта, данные не сегодняшние."""

# Область → инструменты; ядро помечается тегом core (§10.4).
_TAGS = {name: {"core"} for name in toolsets.CORE}
for area, names in toolsets.AREAS.items():
    for name in names:
        _TAGS.setdefault(name, set()).add(area)

_FUNCTIONS = (
    profile.get_basic_info,
    profile.get_legal_status,
    profile.get_fns_flags,
    profile.get_ownership,
    finance.get_financials,
    finance.get_balance_sheet,
    finance.get_liabilities,
    finance.get_financial_ratios,
    finance.get_debt_burden,
    legal.get_arbitration,
    legal.get_execution_proceedings,
    activity.get_activity,
    activity.get_licenses,
    activity.get_inspections,
    activity.get_procurements,
    relations.get_affiliations,
    summary.get_risk_factors,
    summary.get_contractor_full,
    selection.compare_contractors,
    selection.find_similar_contractors,
    analysis.run_focused_analysis,
    charts.build_chart,
    questions.draft_followup_questions,
)


def load_tools(area: str) -> dict:
    """Подгружает дополнительный набор инструментов, если нужного среди доступных нет.
    Вызывай только тогда, когда для ответа не хватает данных, а подходящего
    инструмента в списке не видно. Подгруженные инструменты становятся доступны
    сразу — следующим шагом вызывай нужный.

    area:
      finance — выручка, прибыль, убыток, баланс, активы, обязательства,
                долговая нагрузка, коэффициенты
      legal — арбитражные споры, исполнительные производства, взыскания
      security — метки налоговой, блокировка счетов, учредители, руководитель,
                 связанные компании
      activity — виды деятельности ОКВЭД, лицензии, проверки надзорных органов,
                 госзакупки
    """
    names = toolsets.AREAS.get(area)
    if names is None:
        return {"loaded": [], "reason": "unknown_area",
                "hint": f"Допустимые area: {', '.join(toolsets.AREAS)}."}
    return {"loaded": list(names)}


def build_server() -> FastMCP:
    mcp = FastMCP(name="contractor-audit", instructions=INSTRUCTIONS)
    for function in (*_FUNCTIONS, load_tools):
        mcp.tool(function, tags=_TAGS.get(function.__name__, {"core"}))
    return mcp


def run() -> None:
    build_server().run()
