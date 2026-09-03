from datetime import date, datetime
from decimal import Decimal

from src.core.normalize import to_int
from src.db.models import ArbitrationByYear, Contractor, ExecutionProceeding, FinReport

TREND_SENSITIVITY = 0.05


def money(value: Decimal | int | float | None) -> int | None:
    return None if value is None else int(round(float(value)))


def iso(value: datetime | date | None) -> str | None:
    return value.date().isoformat() if isinstance(value, datetime) else (value.isoformat() if value else None)


def trend(values: list[int | None]) -> str | None:
    known = [v for v in values if v is not None]
    if len(known) < 2:
        return None
    first, last = known[0], known[-1]
    if first == 0:
        return "growing" if last > 0 else "flat"
    change = (last - first) / abs(first)
    if change > TREND_SENSITIVITY:
        return "growing"
    if change < -TREND_SENSITIVITY:
        return "declining"
    return "flat"


def latest_revenue(reports: list[FinReport]) -> int | None:
    for report in sorted(reports, key=lambda r: r.year, reverse=True):
        if report.proceeds is not None:
            return report.proceeds
    return None


def financials(reports: list[FinReport]) -> dict:
    if not reports:
        return {"available": False, "years": [], "trend": {"proceeds": None, "profit": None}}
    ordered = sorted(reports, key=lambda r: r.year)
    return {
        "available": True,
        "years": [{"year": r.year, "proceeds": r.proceeds, "profit": r.profit} for r in ordered],
        "trend": {
            "proceeds": trend([r.proceeds for r in ordered]),
            "profit": trend([r.profit for r in ordered]),
        },
    }


def balance(reports: list[FinReport]) -> list[dict]:
    return [
        {
            "year": r.year,
            "total_assets": r.total_assets,
            "current_assets": r.current_assets,
            "uncurrent_assets": r.uncurrent_assets,
            "receivables": r.receivables,
            "bankroll": r.bankroll,
            "total_liabilities": r.total_liabilities,
            "capitals": r.capitals,
            "borrowed_funds": r.borrowed_funds,
            "accounts_payable": r.accounts_payable,
            "long_term_total": r.long_term_total,
            "short_term_total": r.short_term_total,
        }
        for r in sorted(reports, key=lambda r: r.year)
    ]


# В источнике сторона ответчика называется "defandant" (опечатка в спецификации),
# а счётчики внутри статусов префиксуются одной буквой: pf/pa/pp и df/da/dp.
def _arbitration_side(status: dict, side: str) -> dict:
    block = status.get(f"{side}Arbitration") or {}
    letter = side[0]
    statuses = {
        suffix: block.get(f"{side}Arbitration{name}") or {}
        for suffix, name in (("f", "Finished"), ("a", "Appealed"), ("p", "Pending"))
    }
    # блок лежит сырым JSONB, поэтому числа могут прийти как {"$numberLong": ...}
    def total(kind: str) -> int:
        return sum(to_int(data.get(f"{letter}{suffix}{kind}")) or 0 for suffix, data in statuses.items())

    return {
        "count": total("Count"),
        "amount": total("Amount"),
        "pending": to_int(statuses["p"].get(f"{letter}pCount")) or 0,
    }


def arbitration(contractor: Contractor, by_year: list[ArbitrationByYear]) -> dict:
    status = contractor.arbitration_by_status or {}
    return {
        "granularity": "aggregates_only",
        "total_count": contractor.arbitration_count or 0,
        "total_amount": money(contractor.arbitration_amount),
        "as_plaintiff": _arbitration_side(status, "plaintiff"),
        "as_defendant": _arbitration_side(status, "defandant"),
        "by_year": [
            {
                "year": row.year,
                "plaintiff_count": row.plaintiff_count,
                "plaintiff_amount": money(row.plaintiff_amount),
                "defendant_count": row.defendant_count,
                "defendant_amount": money(row.defendant_amount),
            }
            for row in by_year
        ],
    }


def execproc_summary(contractor: Contractor) -> dict:
    return {
        "total": contractor.execproc_total,
        "total_amount": money(contractor.execproc_total_amount),
        "active": contractor.execproc_active,
        "active_amount": money(contractor.execproc_active_amount),
    }


def execution_proceedings(
    contractor: Contractor, top_active: list[ExecutionProceeding], by_year: dict[int, int]
) -> dict:
    return {
        **execproc_summary(contractor),
        "top_active": [
            {"number": item.number, "date": iso(item.date), "amount": money(item.amount)} for item in top_active
        ],
        "by_year": {str(year): count for year, count in sorted(by_year.items())},
    }
