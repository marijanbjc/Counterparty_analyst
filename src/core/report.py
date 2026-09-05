from typing import Any

RISK_VERDICTS = {
    "LOW": "Работать",
    "MEDIUM": "Работать с осторожностью",
    "HIGH": "Не рекомендуется",
    "UNKNOWN": "Работать с осторожностью",
}


def verdict_for(risk_level: str | None) -> str:
    return RISK_VERDICTS.get(risk_level or "UNKNOWN", "Работать с осторожностью")


def _money(value: int | None) -> str:
    if value is None:
        return "нет данных"
    return f"{value:,.0f} ₽".replace(",", " ")


def _risk_label(value: str | None) -> str:
    return {
        "LOW": "низкий",
        "MEDIUM": "средний",
        "HIGH": "высокий",
        "UNKNOWN": "не определён",
    }.get(value or "UNKNOWN", value or "не определён")


# Коды светофоров и сухие формулировки вида «0 производств на нет данных»
# уходят прямо на экран в отчёте без модели — переписать их там некому.
_ZSK_LABELS = {"GREEN": "зелёный", "YELLOW": "жёлтый", "RED": "красный"}
_MONTHS = ("января", "февраля", "марта", "апреля", "мая", "июня",
           "июля", "августа", "сентября", "октября", "ноября", "декабря")


def _date(value: str | None) -> str:
    try:
        year, month, day = (value or "").split("-")
        return f"{int(day)} {_MONTHS[int(month) - 1]} {year}"
    except (ValueError, IndexError):
        return "неизвестную дату"


def _execproc_line(execution: dict[str, Any]) -> str:
    total = execution.get("total") or 0
    if not total:
        return "Исполнительных производств нет."
    active = execution.get("active") or 0
    if not active:
        return f"Действующих исполнительных производств нет, в истории {total}."
    return (
        f"Действующих исполнительных производств: {active} "
        f"на {_money(execution.get('active_amount'))}, всего в истории {total}."
    )


def _arbitration_line(arbitration: dict[str, Any]) -> str:
    total = arbitration.get("total_count") or 0
    if not total:
        return "Арбитражных дел нет."
    amount = arbitration.get("total_amount")
    tail = f" на {_money(amount)}" if amount else ""
    return f"Арбитражных дел: {total}{tail}."


def build(fact_pack: dict[str, Any]) -> dict[str, Any]:
    basis = fact_pack["verdict_basis"]
    risk_level = basis.get("risk_level")
    verdict = verdict_for(risk_level)
    execution = fact_pack["execution_proceedings"]
    arbitration = fact_pack["arbitration"]
    discrepancies = fact_pack.get("discrepancies") or []

    summary = (
        f"{fact_pack['short_name']}: риск {_risk_label(risk_level)}, "
        f"ЗСК {_ZSK_LABELS.get(basis.get('zsk_risk_level'), 'не определён')}. "
        f"Вердикт: {verdict}."
    )
    lines = [
        f"Данные на {_date(fact_pack.get('as_of'))}.",
        _execproc_line(execution),
        _arbitration_line(arbitration),
    ]
    factors = fact_pack["risk_factors"].get("negative_total") or 0
    if factors:
        lines.append(f"Негативных факторов: {factors}.")
    lines.extend(item["text"] for item in discrepancies)

    return {
        "verdict": verdict,
        "summary": summary,
        "analysis": "\n".join(lines),
        "report": fact_pack,
        "degraded": True,
        "notice": "ИИ-разбор недоступен. Ниже — данные отчёта.",
    }


def to_markdown(result: dict[str, Any]) -> str:
    report = result["report"]
    return "\n".join(
        [
            f"# {report['short_name']}",
            "",
            f"**ИНН:** {report['inn']}",
            f"**Вердикт:** {result['verdict']}",
            f"**Актуальность:** {report.get('as_of') or 'нет данных'}",
            "",
            result["summary"],
            "",
            "## Анализ",
            result["analysis"],
        ]
    )
