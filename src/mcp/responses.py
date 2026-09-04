"""Общий контракт ответов инструментов — mcp_architecture.md §2.1, §2.2, §2.7."""

from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from src.core import inn as inn_module
from src.core.aggregates import iso
from src.db.contragents import repository
from src.db.engine import db_session
from src.db.models import Contractor

NOT_APPLICABLE = "not_applicable"

_NOT_IN_DATABASE = (
    "Контрагента с таким ИНН в базе нет. Переспросите ИНН у пользователя."
)


def invalid_inn(value: str) -> dict:
    return {"found": False, "reason": "invalid_inn", "inn": value, "hint": inn_module.FORMAT_HINT}


def not_in_database(value: str) -> dict:
    # Отказ намеренно не перечисляет известные ИНН: иначе на каждой опечатке
    # модели вываливается содержимое базы (mcp_architecture.md §4.1).
    return {"found": False, "reason": "not_in_database", "inn": value, "hint": _NOT_IN_DATABASE}


def for_contractor(value: str, builder: Callable[[Session, Contractor], dict[str, Any]]) -> dict:
    """Валидация ИНН, поиск контрагента и общие поля ответа — один раз на все инструменты."""
    value = (value or "").strip()
    if not inn_module.is_valid(value):
        return invalid_inn(value)

    with db_session() as session:
        contractor = repository.get_contractor(session, value)
        if contractor is None:
            return not_in_database(value)
        payload = builder(session, contractor)
        return {
            "found": True,
            "inn": contractor.inn,
            "short_name": contractor.short_name,
            "as_of": iso(contractor.report_date),
            **payload,
        }


def factor_items(rows) -> list[dict]:
    return [
        {"code": row.code, "polarity": row.polarity, "name": row.name}
        for row in rows
    ]
