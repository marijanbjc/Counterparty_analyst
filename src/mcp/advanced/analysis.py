from src.core import findings
from src.mcp.tools import activity as activity_tools
from src.mcp.tools import finance as finance_tools
from src.mcp.tools import legal as legal_tools
from src.mcp.tools import profile as profile_tools
from src.mcp.tools import relations as relations_tools


def _finance(inn: str):
    return findings.finance(
        finance_tools.get_financials(inn),
        finance_tools.get_balance_sheet(inn),
        finance_tools.get_debt_burden(inn),
        finance_tools.get_financial_ratios(inn),
    )


def _legal(inn: str):
    return findings.legal(
        legal_tools.get_arbitration(inn),
        legal_tools.get_execution_proceedings(inn),
        profile_tools.get_legal_status(inn),
        finance_tools.get_debt_burden(inn),
    )


def _security(inn: str):
    return findings.security(
        profile_tools.get_fns_flags(inn),
        profile_tools.get_ownership(inn),
        relations_tools.get_affiliations(inn),
        profile_tools.get_legal_status(inn),
    )


def _activity(inn: str):
    return findings.activity(
        activity_tools.get_activity(inn),
        activity_tools.get_licenses(inn),
        activity_tools.get_inspections(inn),
        activity_tools.get_procurements(inn),
    )


BUILDERS = {"finance": _finance, "legal": _legal, "security": _security, "activity": _activity}


def run_focused_analysis(inn: str, focus: str) -> dict:
    """Запускает углублённый разбор по одному направлению и возвращает готовые тезисы
    вместо сырых данных. Вызывай, когда нужен глубокий разбор одного аспекта — это
    дешевле, чем последовательно вызывать пять инструментов и держать их ответы
    в контексте. Каждый тезис снабжён ссылкой на поле-источник. Вердикт и рекомендации
    разбор не выносит — только наблюдения."""
    if focus not in BUILDERS:
        return {"found": False, "reason": "bad_request",
                "hint": f"Допустимые значения focus: {', '.join(findings.FOCUS_AREAS)}."}

    probe = profile_tools.get_legal_status(inn)
    if not probe.get("found"):
        return probe

    items, missing = BUILDERS[focus](inn)
    return {
        "found": True,
        "inn": probe["inn"],
        "short_name": probe["short_name"],
        "as_of": probe["as_of"],
        "focus": focus,
        "findings": items,
        "summary": findings.summarize(items),
        "missing": missing,
    }
