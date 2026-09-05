"""Наборы данных под кнопками: дочитывает код, а не модель (§7).

Схемы инструментов в промпт не уходят, поэтому набор стоит ровно столько,
сколько весят его данные — замеры по всем контрагентам в §7.1.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

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

LABELS: dict[str, str] = {
    FINANCE: "Финансы",
    LEGAL: "Юридический",
    SECURITY: "Безопасность",
    ACTIVITY: "Деятельность",
    FOLLOWUPS: "Что запросить",
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


# Для оценки связей достаточно счётчиков и короткого списка: полные карточки
# двадцати компаний раздували набор до 3 836 токенов (known_issues.md §7).
SECURITY_AFFILIATIONS_LIMIT = 5


def _present_flags(inn: str) -> dict:
    """Только стоящие метки ФНС. Снятые приходят с формулировками вида
    «не найден в реестре…» и весят больше, чем сами метки, а для оценки риска
    не нужны: их отсутствие видно по счётчику (known_issues.md §7)."""
    payload = profile_tools.get_fns_flags(inn)
    flags = payload.get("flags") or []
    present = [flag for flag in flags if flag.get("present")]
    return {
        **{key: value for key, value in payload.items() if key != "flags"},
        "flags": present,
        "confirmed_absent": len(flags) - len(present),
    }


def _security(inn: str) -> dict:
    return {
        "fns_flags": _present_flags(inn),
        "ownership": profile_tools.get_ownership(inn),
        "affiliations": relations_tools.get_affiliations(inn, limit=SECURITY_AFFILIATIONS_LIMIT),
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


_SETS: dict[str, Callable[[str], dict]] = {
    FINANCE: _finance,
    LEGAL: _legal,
    SECURITY: _security,
    ACTIVITY: _activity,
    FOLLOWUPS: _followups,
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
        parts: list[str] = []
        if self.dropped:
            labels = ", ".join(LABELS[name] for name in self.dropped)
            parts.append(
                f"На вашем тарифе за один ход дочитывается до {self.max_buttons} наборов данных. "
                f"Не поместились: {labels} — отметьте их следующим сообщением."
            )
        if self.unknown:
            parts.append(f"Неизвестные наборы данных пропущены: {', '.join(self.unknown)}.")
        return " ".join(parts) or None


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

    selected = known[:limit]
    data = {name: _SETS[name](inn) for name in selected}
    return Prefetched(
        data=data,
        dropped=tuple(known[limit:]),
        unknown=unknown,
        max_buttons=limit,
    )
