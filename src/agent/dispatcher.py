"""Вызовы инструментов модели: белый список ИНН и in-process MCP-функции.

Инструменты MCP stateless и не знают сессии. Проверка ИНН живёт здесь —
между tool_call и функцией (known_issues.md §5, architecture.md §9.1 слой 4).
"""

from __future__ import annotations

import json
from typing import Any

from src.agent.catalog import FUNCTIONS
from src.core import inn as inn_module
from src.mcp.server import load_tools

NOT_IN_SESSION = {
    "found": False,
    "reason": "inn_not_in_session",
    "hint": "Этот ИНН в диалоге не назывался. Уточните его у пользователя.",
}


def dispatch(
    name: str,
    arguments: dict[str, Any],
    allowed: set[str],
    loaded: tuple[str, ...],
    permitted: set[str],
) -> tuple[dict[str, Any], set[str], tuple[str, ...]]:
    if name not in permitted:
        return (
            {
                "found": False,
                "reason": "tool_not_permitted",
                "hint": f"Инструмент {name or '<empty>'} не разрешён на этом шаге.",
            },
            set(),
            loaded,
        )
    if name == "load_tools":
        area = str(arguments.get("area") or "")
        result = load_tools(area)
        # toolsets.resolve() принимает имена областей, а не имена функций.
        # Храним именно область, иначе динамически загруженные схемы не появятся
        # в следующем запросе к модели.
        updated = loaded if result.get("reason") or area in loaded else loaded + (area,)
        return result, set(), updated
    if name not in FUNCTIONS:
        known = ", ".join(sorted(FUNCTIONS))
        return (
            {"found": False, "reason": "unknown_tool", "hint": f"Нет инструмента {name}. Доступны: {known}."},
            set(),
            loaded,
        )

    blocked = _blocked_inns(arguments, allowed)
    if blocked:
        return {**NOT_IN_SESSION, "inn": blocked}, set(), loaded

    try:
        result = FUNCTIONS[name](**arguments)
    except (IndexError, TypeError, ValueError) as exc:
        return {"found": False, "reason": "bad_request", "hint": str(exc)}, set(), loaded

    harvested = _harvest(name, result)
    return result, harvested, loaded


def parse_arguments(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return value if isinstance(value, dict) else {}
    return {}


def _blocked_inns(arguments: dict[str, Any], allowed: set[str]) -> list[str]:
    values: list[str] = []
    inn = arguments.get("inn")
    if isinstance(inn, str):
        values.append(inn)
    inns = arguments.get("inns")
    if isinstance(inns, list):
        values.extend(item for item in inns if isinstance(item, str))
    target = arguments.get("target")
    if isinstance(target, str):
        values.append(target)
    elif isinstance(target, list):
        values.extend(item for item in target if isinstance(item, str))
    return [value for value in values if inn_module.is_valid(value) and value not in allowed]


def _harvest(name: str, result: dict[str, Any]) -> set[str]:
    found: set[str] = set()
    inn = result.get("inn")
    if isinstance(inn, str) and inn_module.is_valid(inn):
        found.add(inn)
    expandable = {
        "get_affiliations": ("items",),
        "find_similar_contractors": ("items",),
        "compare_contractors": ("matrix",),
    }
    for key in expandable.get(name, ()):
        for row in result.get(key) or []:
            if not isinstance(row, dict):
                continue
            value = row.get("inn")
            if isinstance(value, str) and inn_module.is_valid(value):
                found.add(value)
    return found
