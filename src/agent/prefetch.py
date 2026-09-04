"""Наборы данных под кнопками: дочитывает код, а не модель (§7).

Схемы инструментов в промпт не уходят, поэтому набор стоит ровно столько,
сколько весят его данные — замеры по всем контрагентам в §7.1.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from src.mcp.advanced import charts as charts_tools
from src.mcp.advanced import questions as questions_tools
from src.mcp.tools import activity as activity_tools
from src.mcp.tools import finance as finance_tools
from src.mcp.tools import legal as legal_tools
from src.mcp.tools import profile as profile_tools
from src.mcp.tools import relations as relations_tools

# Первые четыре имени совпадают с toolsets.AREAS и с ролями интерфейса:
# область, роль и кнопка — одно и то же слово во всём приложении (§7.3).
FINANCE = "finance"
LEGAL = "legal"
SECURITY = "security"
ACTIVITY = "activity"
FOLLOWUPS = "followups"
CHARTS = "charts"

LABELS: dict[str, str] = {
    FINANCE: "Финансы",
    LEGAL: "Юридический",
    SECURITY: "Безопасность",
    ACTIVITY: "Деятельность",
    FOLLOWUPS: "Что запросить",
    CHARTS: "Графики",
}


def _finance(inn: str) -> dict:
    return {
        "balance_sheet": finance_tools.get_balance_sheet(inn),
        "liabilities": finance_tools.get_liabilities(inn),
        "ratios": finance_tools.get_financial_ratios(inn),
    }


def _legal(inn: str) -> dict:
    return {
        "arbitration": legal_tools.get_arbitration(inn),
        "execution_proceedings": legal_tools.get_execution_proceedings(inn),
    }


def _security(inn: str) -> dict:
    return {
        "fns_flags": profile_tools.get_fns_flags(inn),
        "ownership": profile_tools.get_ownership(inn),
        "affiliations": relations_tools.get_affiliations(inn),
    }


def _activity(inn: str) -> dict:
    return {
        "activity": activity_tools.get_activity(inn),
        "licenses": activity_tools.get_licenses(inn),
        "inspections": activity_tools.get_inspections(inn),
        "procurements": activity_tools.get_procurements(inn),
    }


def _followups(inn: str) -> dict:
    return {"questions": questions_tools.draft_followup_questions(inn)}


def _charts(inn: str) -> dict:
    return {
        "revenue_profit": charts_tools.build_chart(inn, "revenue_profit"),
        "execproc_timeline": charts_tools.build_chart(inn, "execproc_timeline"),
    }


_SETS: dict[str, Callable[[str], dict]] = {
    FINANCE: _finance,
    LEGAL: _legal,
    SECURITY: _security,
    ACTIVITY: _activity,
    FOLLOWUPS: _followups,
    CHARTS: _charts,
}

NAMES: tuple[str, ...] = tuple(_SETS)


@dataclass(frozen=True)
class Prefetched:
    data: dict[str, dict]
    dropped: tuple[str, ...] = ()  # отсечены потолком тарифа
    unknown: tuple[str, ...] = ()  # имён нет в каталоге наборов
    max_buttons: int = 0

    @property
    def notice(self) -> str | None:
        """Отсечённое сверх потолка нельзя проглатывать: пользователь отметил набор
        и вправе знать, что тот не дочитан и почему (§7.4)."""
        if not self.dropped:
            return None
        labels = ", ".join(LABELS[name] for name in self.dropped)
        return (
            f"На вашем тарифе за один ход дочитывается до {self.max_buttons} наборов данных. "
            f"Не поместились: {labels} — отметьте их следующим сообщением."
        )


def collect(names: Sequence[str], inn: str, max_buttons: int) -> Prefetched:
    """Дочитывает наборы `names` по контрагенту `inn`, не больше `max_buttons` за ход.

    Список приходит от клиента, поэтому мусор и повторы в нём не роняют ход:
    неизвестное имя пропускается с пометкой, а не исключением.
    """
    requested: list[str] = []
    for raw in names or ():
        name = (raw or "").strip().lower()
        if name and name not in requested:
            requested.append(name)

    unknown = tuple(name for name in requested if name not in _SETS)
    known = [name for name in requested if name in _SETS]
    limit = max(max_buttons, 0)

    return Prefetched(
        data={name: _SETS[name](inn) for name in known[:limit]},
        dropped=tuple(known[limit:]),
        unknown=unknown,
        max_buttons=limit,
    )
