from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

# В снапшоте коды факторов приходят вперемешку с кириллическими омоглифами
# (например "аrbitrationDefendant" с русской «а») — без замены ломается матчинг.
HOMOGLYPHS = str.maketrans("аеорсухАЕОРСУХ", "aeopcyxAEOPCYX")


def unwrap(value: Any) -> Any:
    if isinstance(value, dict):
        for key in ("$numberLong", "$numberInt", "$numberDouble", "$date"):
            if key in value:
                return value[key]
    return value


def to_int(value: Any) -> int | None:
    value = unwrap(value)
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def to_decimal(value: Any) -> Decimal | None:
    value = unwrap(value)
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def to_date(value: Any) -> datetime | None:
    value = unwrap(value)
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def to_text(value: Any) -> str | None:
    value = unwrap(value)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def normalize_code(code: Any) -> str | None:
    code = to_text(code)
    return code.translate(HOMOGLYPHS) if code else None


def dig(source: Any, *path: str) -> Any:
    for key in path:
        if not isinstance(source, dict):
            return None
        source = source.get(key)
    return source
