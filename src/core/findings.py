"""Тезисы узкого разбора. Пока считаются детерминированно по тем же данным,
что видит модель; синтез через LLM подключается в агентном слое (§8.1)."""

CRITICAL, ATTENTION, NEUTRAL, POSITIVE = "critical", "attention", "neutral", "positive"

FOCUS_AREAS = ("finance", "legal", "security", "activity")


def _money(value: int | None) -> str:
    return "нет данных" if value is None else f"{value:,.0f} ₽".replace(",", " ")


def finance(financials: dict, balance: dict, burden: dict, ratios: dict) -> tuple[list[dict], list[str]]:
    items, missing = [], []
    if not financials["available"]:
        missing.append("financials")
        items.append({"statement": "Финансовая отчётность в отчёте отсутствует — оценить финансовое состояние нечем.",
                      "source_fields": ["financials.available"], "severity": NEUTRAL})
    else:
        years = financials["years"]
        last = years[-1] if years else None
        if last and last["proceeds"] is not None:
            items.append({"statement": f"Выручка за {last['year']} год — {_money(last['proceeds'])}.",
                          "source_fields": ["financials.years.proceeds"], "severity": NEUTRAL})
        if last and last["profit"] is not None and last["profit"] < 0:
            items.append({"statement": f"За {last['year']} год получен убыток {_money(last['profit'])}.",
                          "source_fields": ["financials.years.profit"], "severity": ATTENTION})
        if financials["trend"]["proceeds"]:
            items.append({"statement": f"Динамика выручки: {financials['trend']['proceeds']}.",
                          "source_fields": ["financials.trend.proceeds"], "severity": NEUTRAL})
        if any(row["profit"] is None for row in years):
            missing.append("profit")

    if balance.get("negative_net_assets"):
        items.append({"statement": "Чистые активы отрицательны: обязательства превышают активы.",
                      "source_fields": ["balance_sheet.net_assets"], "severity": CRITICAL})
    if burden["comparable"] and burden["debt_to_net_assets"] and burden["debt_to_net_assets"] > 1:
        share = round(burden["debt_to_net_assets"] * 100)
        items.append({"statement": f"Текущий долг {_money(burden['current_debt'])} превышает чистые активы: {share} %.",
                      "source_fields": ["debt_burden.debt_to_net_assets"], "severity": CRITICAL})
    elif not burden["comparable"] and burden["current_debt"] > 0:
        items.append({"statement": f"Текущий долг {_money(burden['current_debt'])}; соотнести его с масштабом бизнеса нечем.",
                      "source_fields": ["debt_burden.current_debt"], "severity": ATTENTION})
    if not ratios.get("available"):
        missing.append("coefficients")
    return items, missing


def legal(arbitration: dict, execproc: dict, status: dict, burden: dict) -> tuple[list[dict], list[str]]:
    items, missing = [], []
    if status["severity"] == CRITICAL:
        items.append({"statement": f"В ЕГРЮЛ указана причина: {status['status_reason']}",
                      "source_fields": ["legal_status.status_reason"], "severity": CRITICAL})

    defendant = arbitration["as_defendant"]
    if defendant["pending_count"]:
        items.append({"statement": f"Открытых дел в роли ответчика: {defendant['pending_count']} на {_money(defendant['pending_amount'])}.",
                      "source_fields": ["arbitration.as_defendant.pending_count"], "severity": ATTENTION})
    elif arbitration["total_count"]:
        items.append({"statement": f"Арбитражные дела есть ({arbitration['total_count']}), открытых среди них нет.",
                      "source_fields": ["arbitration.total_count"], "severity": NEUTRAL})
    else:
        items.append({"statement": "Арбитражных дел в отчёте нет.",
                      "source_fields": ["arbitration.total_count"], "severity": POSITIVE})

    if execproc["active"]:
        items.append({"statement": f"Действующих исполнительных производств: {execproc['active']} на {_money(execproc['active_amount'])}; всего за историю {execproc['total']}.",
                      "source_fields": ["execution_proceedings.active"], "severity": ATTENTION})
    elif execproc["total"]:
        items.append({"statement": f"Действующих взысканий нет, за историю {execproc['total']} производств.",
                      "source_fields": ["execution_proceedings.total"], "severity": NEUTRAL})
    if not burden["comparable"]:
        missing.append("debt_comparison_base")
    return items, missing


def security(flags: dict, ownership: dict, affiliations: dict, status: dict) -> tuple[list[dict], list[str]]:
    items, missing = [], []
    for flag in flags["flags"]:
        if flag["present"]:
            items.append({"statement": flag["name"], "source_fields": [f"fns_flags.{flag['code']}"],
                          "severity": CRITICAL if flag["severity"] == CRITICAL else ATTENTION})
    if not flags["flags"]:
        missing.append("fns_flags")
    if status["severity"] == CRITICAL:
        items.append({"statement": f"В ЕГРЮЛ указана причина: {status['status_reason']}",
                      "source_fields": ["legal_status.status_reason"], "severity": CRITICAL})
    if ownership.get("director_is_sole_founder") is True:
        items.append({"statement": "Руководитель является единственным учредителем.",
                      "source_fields": ["ownership.director_is_sole_founder"], "severity": NEUTRAL})
    if affiliations["same_director_count"]:
        items.append({"statement": f"Связанных компаний под тем же руководителем: {affiliations['same_director_count']} из {affiliations['count']}.",
                      "source_fields": ["affiliations.same_director_count"], "severity": NEUTRAL})
    return items, missing


def activity(profile: dict, licenses: dict, inspections: dict, procurements: dict) -> tuple[list[dict], list[str]]:
    items, missing = [], []
    main = profile["main_okved"]
    items.append({"statement": f"Основной вид деятельности — {main['code']} {main['description']}; всего кодов {profile['okved_count']}.",
                  "source_fields": ["activity.main_okved"], "severity": NEUTRAL})
    if profile["mass_okved"]["flag"]:
        items.append({"statement": profile["mass_okved"]["name"], "source_fields": ["activity.mass_okved"],
                      "severity": ATTENTION})
    if licenses["count"]:
        items.append({"statement": f"Лицензий в отчёте: {licenses['count']}.",
                      "source_fields": ["licenses.count"], "severity": POSITIVE})
    else:
        missing.append("licenses")
    if inspections["total"]:
        clean = inspections["by_result"].get("violation_not_detected", 0)
        items.append({"statement": f"Проверок надзорных органов: {inspections['total']}, из них без выявленных нарушений {clean}.",
                      "source_fields": ["inspections.by_result"], "severity": NEUTRAL})
    else:
        missing.append("inspections")
    if procurements["tender_wins"]:
        items.append({"statement": f"Побед в тендерах: {procurements['tender_wins']}, подписано контрактов на {_money(procurements['contracts_amount'])}.",
                      "source_fields": ["procurements.tender_wins"], "severity": POSITIVE})
    return items, missing


def summarize(items: list[dict]) -> str:
    critical = [i for i in items if i["severity"] == CRITICAL]
    attention = [i for i in items if i["severity"] == ATTENTION]
    if critical:
        return f"Критичных наблюдений: {len(critical)}, требующих внимания: {len(attention)}."
    if attention:
        return f"Критичных наблюдений нет, требующих внимания: {len(attention)}."
    return "Наблюдений, требующих внимания, не выявлено."
