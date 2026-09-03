from src.config.settings import get_settings
from src.db.models import Contractor

GREEN_RISK = {"LOW"}
GREEN_ZSK = {"GREEN"}


def _millions(value: int | None) -> str:
    return f"{(value or 0) / 1_000_000:.1f} млн ₽".replace(".", ",")


def traffic_lights_disagree(contractor: Contractor) -> bool:
    return (contractor.risk_level, contractor.zsk_risk_level) in {("HIGH", "GREEN"), ("LOW", "RED")}


def _looks_green(contractor: Contractor) -> bool:
    return contractor.risk_level in GREEN_RISK and contractor.zsk_risk_level in GREEN_ZSK


def _execproc_reasons(contractor: Contractor, revenue: int | None) -> list[str]:
    settings = get_settings()
    active_amount = int(contractor.execproc_active_amount or 0)
    reasons = []
    if revenue and active_amount / revenue > settings.risk_active_execproc_revenue_share:
        reasons.append(f"{100 * active_amount / revenue:.0f} % выручки")
    if not revenue and contractor.execproc_active >= settings.risk_active_execproc_count_without_revenue:
        reasons.append(f"{contractor.execproc_active} активных производств при отсутствии отчётности")
    if active_amount > settings.risk_active_execproc_absolute:
        reasons.append(_millions(active_amount))
    return reasons


def detect(contractor: Contractor, revenue: int | None, has_financials: bool) -> list[dict]:
    settings = get_settings()
    found = []

    if _looks_green(contractor):
        reasons = _execproc_reasons(contractor, revenue)
        if reasons:
            found.append(
                {
                    "code": "green_but_execproc",
                    "text": (
                        f"Светофор зелёный, но есть активные исполнительные производства: "
                        f"{contractor.execproc_active} шт. на {_millions(contractor.execproc_active_amount)} "
                        f"({', '.join(reasons)})"
                    ),
                }
            )
        if contractor.negative_factors_count >= settings.risk_negative_factors_threshold:
            found.append(
                {
                    "code": "green_but_negative",
                    "text": (
                        f"Формально низкий риск при {contractor.negative_factors_count} "
                        f"негативных факторах"
                    ),
                }
            )

    if contractor.execproc_total >= settings.risk_many_execproc_threshold:
        found.append(
            {
                "code": "many_closed_execproc",
                "text": (
                    f"Историческая долговая нагрузка: {contractor.execproc_total} производств "
                    f"на {_millions(contractor.execproc_total_amount)}, из них активны "
                    f"{contractor.execproc_active} на {_millions(contractor.execproc_active_amount)}"
                ),
            }
        )

    if traffic_lights_disagree(contractor):
        found.append(
            {
                "code": "traffic_lights_disagree",
                "text": f"Уровень риска {contractor.risk_level} расходится с оценкой ЗСК {contractor.zsk_risk_level}",
            }
        )

    if contractor.risk_level == "UNKNOWN":
        found.append({"code": "unknown_risk", "text": "Банк не смог присвоить уровень риска"})

    if not has_financials:
        found.append({"code": "no_financials", "text": "Финансовая отчётность отсутствует"})

    return found
