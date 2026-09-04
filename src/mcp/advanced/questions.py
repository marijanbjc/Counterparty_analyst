from src.core import followups
from src.mcp.tools import activity as activity_tools
from src.mcp.tools import finance as finance_tools
from src.mcp.tools import legal as legal_tools
from src.mcp.tools import profile as profile_tools


def draft_followup_questions(inn: str) -> dict:
    """Формирует список того, что имеет смысл запросить у самого контрагента: документы
    и пояснения, вытекающие из найденных пробелов и негативных факторов. Каждый пункт
    содержит вопрос, его причину и поле-источник. Это не рекомендация работать
    или не работать — это перечень уточнений, которые снимут неопределённость.
    Формулировки готовы, дополнять и переписывать их не нужно."""
    status = profile_tools.get_legal_status(inn)
    if not status.get("found"):
        return status

    financials = finance_tools.get_financials(inn)
    balance = finance_tools.get_balance_sheet(inn)
    execproc = legal_tools.get_execution_proceedings(inn)
    arbitration = legal_tools.get_arbitration(inn)
    flags = profile_tools.get_fns_flags(inn)
    activity = activity_tools.get_activity(inn)

    items = followups.build(
        legal_severity=status["severity"],
        has_financials=financials["available"],
        negative_net_assets=balance["negative_net_assets"],
        execproc_active=execproc["active"],
        arbitration_pending=arbitration["as_defendant"]["pending_count"],
        flag_codes={flag["code"] for flag in flags["flags"] if flag["present"]},
        mass_okved=activity["mass_okved"]["flag"],
    )
    return {
        "found": True,
        "inn": status["inn"],
        "short_name": status["short_name"],
        "as_of": status["as_of"],
        "count": len(items),
        "items": items,
    }
