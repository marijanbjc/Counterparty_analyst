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


def build(fact_pack: dict[str, Any]) -> dict[str, Any]:
    basis = fact_pack["verdict_basis"]
    risk_level = basis.get("risk_level")
    verdict = verdict_for(risk_level)
    execution = fact_pack["execution_proceedings"]
    arbitration = fact_pack["arbitration"]
    discrepancies = fact_pack.get("discrepancies") or []

    summary = (
        f"{fact_pack['short_name']}: риск {_risk_label(risk_level)}, "
        f"ЗСК {basis.get('zsk_risk_level') or 'не определён'}. "
        f"Вердикт: {verdict}."
    )
    lines = [
        f"Данные актуальны на {fact_pack.get('as_of') or 'неизвестную дату'}.",
        (
            f"Исполнительные производства: {execution.get('active', 0)} активных "
            f"на {_money(execution.get('active_amount'))}; всего {execution.get('total', 0)}."
        ),
        (
            f"Арбитраж: {arbitration.get('total_count', 0)} производств "
            f"на {_money(arbitration.get('total_amount'))}; в источнике доступны только агрегаты."
        ),
        f"Негативных факторов: {fact_pack['risk_factors'].get('negative_total', 0)}.",
    ]
    lines.extend(item["text"] for item in discrepancies)

    return {
        "verdict": verdict,
        "summary": summary,
        "analysis": "\n".join(lines),
        "report": fact_pack,
        "degraded": True,
        "notice": "ИИ-анализ пока не подключён. Показан детерминированный отчёт.",
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
