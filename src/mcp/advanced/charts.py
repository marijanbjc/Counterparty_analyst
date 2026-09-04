from src.core import charts
from src.mcp.tools import finance as finance_tools
from src.mcp.tools import legal as legal_tools
from src.mcp.tools import selection as selection_tools

SINGLE = ("revenue_profit", "execproc_timeline", "arbitration_sides", "balance_structure", "debt_vs_assets")


def _bad_request(hint: str) -> dict:
    return {"found": False, "reason": "bad_request", "hint": hint}


def build_chart(target: str | list[str], chart_type: str, metric: str = "revenue") -> dict:
    """Возвращает данные для построения графика — ряды, подписи и единицы измерения.
    Изображение не создаётся, график рисует интерфейс. Вызывай, когда числовой ряд
    нагляднее показать визуально: динамика выручки, взысканий, структура баланса,
    сравнение нескольких контрагентов. Поле missing_points перечисляет пропуски
    в ряду — они отображаются разрывом, а не нулём."""
    if chart_type not in charts.CHART_TYPES:
        return _bad_request(f"Допустимые chart_type: {', '.join(charts.CHART_TYPES)}.")

    if chart_type == "compare_metric":
        inns = target if isinstance(target, list) else [target]
        if metric not in charts.COMPARE_METRICS:
            return _bad_request(f"Допустимые metric: {', '.join(charts.COMPARE_METRICS)}.")
        payload = selection_tools.compare_contractors(inns)
        if not payload.get("found"):
            return payload
        return {"found": True, **charts.compare_metric(payload["matrix"], metric)}

    inn = target[0] if isinstance(target, list) else target
    if chart_type == "revenue_profit":
        source = finance_tools.get_financials(inn)
        if not source.get("found"):
            return source
        return {"found": True, "inn": source["inn"], "short_name": source["short_name"],
                **charts.revenue_profit(source["years"])}

    if chart_type == "execproc_timeline":
        source = legal_tools.get_execution_proceedings(inn)
        if not source.get("found"):
            return source
        return {"found": True, "inn": source["inn"], "short_name": source["short_name"],
                **charts.execproc_timeline(source["by_year"])}

    if chart_type == "arbitration_sides":
        source = legal_tools.get_arbitration(inn)
        if not source.get("found"):
            return source
        return {"found": True, "inn": source["inn"], "short_name": source["short_name"],
                **charts.arbitration_sides(source["by_year"])}

    if chart_type == "balance_structure":
        balance = finance_tools.get_balance_sheet(inn)
        if not balance.get("found"):
            return balance
        liabilities = finance_tools.get_liabilities(inn)
        return {"found": True, "inn": balance["inn"], "short_name": balance["short_name"],
                **charts.balance_structure(balance["years"], liabilities["years"])}

    burden = finance_tools.get_debt_burden(inn)
    if not burden.get("found"):
        return burden
    return {"found": True, "inn": burden["inn"], "short_name": burden["short_name"],
            **charts.debt_vs_assets(burden)}
