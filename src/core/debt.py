from src.core import aggregates
from src.db.models import Contractor, FinReport

NET_ASSETS = "net_assets"
REVENUE = "revenue"
ABSOLUTE = "absolute"


def _latest(reports: list[FinReport]) -> FinReport | None:
    return max(reports, key=lambda r: r.year) if reports else None


def _pending_defendant_amount(contractor: Contractor) -> int:
    side = aggregates.arbitration(contractor, [])["as_defendant"]
    return side["pending_amount"]


def build(contractor: Contractor, reports: list[FinReport]) -> dict:
    execproc = int(contractor.execproc_active_amount or 0)
    arbitration = _pending_defendant_amount(contractor)
    current_debt = execproc + arbitration

    latest = _latest(reports)
    net_assets = latest.capitals if latest else None
    revenue = aggregates.latest_revenue(reports)

    # Отрицательный или нулевой капитал делает долю бессмысленной: делить не на что.
    to_net_assets = current_debt / net_assets if net_assets and net_assets > 0 else None
    to_revenue = current_debt / revenue if revenue and revenue > 0 else None

    if to_net_assets is not None:
        basis = NET_ASSETS
    elif to_revenue is not None:
        basis = REVENUE
    else:
        basis = ABSOLUTE

    return {
        "current_debt": current_debt,
        "debt_parts": {
            "execproc_active": execproc,
            "arbitration_pending_defendant": arbitration,
        },
        "net_assets": net_assets,
        "net_assets_year": latest.year if latest else None,
        "negative_net_assets": bool(net_assets is not None and net_assets < 0),
        "revenue": revenue,
        "debt_to_net_assets": round(to_net_assets, 4) if to_net_assets is not None else None,
        "debt_to_revenue": round(to_revenue, 4) if to_revenue is not None else None,
        "basis": basis,
        "comparable": basis != ABSOLUTE,
    }
