from src.core.aggregates import iso
from src.core.normalize import dig, to_date
from src.db.models import Contractor

CRITICAL = "critical"
ATTENTION = "attention"
NONE = "none"

# Причина приходит свободным текстом из ЕГРЮЛ, кода в источнике нет — классифицируем
# по устойчивым фрагментам формулировок. Порядок важен: первое совпадение выигрывает.
_PATTERNS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("bankruptcy", CRITICAL, ("банкрот", "конкурсн")),
    ("pending_exclusion", CRITICAL, ("исключени", "егрюл")),
    ("address_change", ATTENTION, ("изменени", "места нахождения")),
    ("capital_decrease", ATTENTION, ("уменьшени", "уставного капитала")),
)


def classify(reason: str | None) -> tuple[str, str]:
    if not reason:
        return "none", NONE
    lowered = reason.lower()
    for code, severity, markers in _PATTERNS:
        if all(marker in lowered for marker in markers):
            return code, severity
    # Незнакомая причина всё равно означает изменение в статусе лица,
    # поэтому молча считать её безобидной нельзя.
    return "other", ATTENTION


def build(contractor: Contractor, factors: list[dict] | None = None) -> dict:
    code, severity = classify(contractor.status_reason)
    return {
        "status": contractor.status,
        "status_date": iso(_status_date(contractor)),
        "status_reason": contractor.status_reason,
        "reason_code": code,
        "severity": severity,
        "factors": factors or [],
    }


def _status_date(contractor: Contractor):
    return to_date(dig(contractor.raw, "status", "date"))
