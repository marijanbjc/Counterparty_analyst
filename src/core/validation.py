"""Детерминированная проверка ответа модели — ARCHITECTURE.md

Сплошная сверка всех чисел ответа с факт-пакетом сознательно не выполняется:
годы, порядковые числительные и округления давали бы ложные срабатывания.
Проверяются три инварианта, которые однозначны и дорого стоят при нарушении.
"""

from src.core import inn as inn_module
from src.core.report import RISK_VERDICTS

UNKNOWN_INN = "unknown_inn"
VERDICT_MISMATCH = "verdict_mismatch"
DISCREPANCY_OMITTED = "discrepancy_omitted"

# Порядок строгости. Проверка односторонняя: ответ осторожнее светофора допустим
# и даже ожидаем при сработавшем детекторе расхождений, а оптимистичнее — нет.
VERDICT_LEVEL = {"Работать": 0, "Работать с осторожностью": 1, "Не рекомендуется": 2}

_VERDICT_MARKERS = (
    ("Не рекомендуется", ("не рекоменд", "не сто́ит работать", "не стоит работать")),
    ("Работать с осторожностью", ("осторожн",)),
    ("Работать", ("работать", "можно сотрудничать")),
)

_DISCREPANCY_MARKERS = {
    "green_but_execproc": ("исполнительн", "взыскан"),
    "green_but_negative": ("негативн", "фактор"),
    "many_closed_execproc": ("производств", "взыскан"),
    "traffic_lights_disagree": ("расход", "противореч", "зск"),
    "unknown_risk": ("не определ", "не присво", "unknown"),
    "no_financials": ("отчётност", "отчетност", "финансов"),
    "green_but_status_reason": ("банкрот", "исключен", "егрюл"),
}


def stated_verdict(text: str) -> str | None:
    """Какой вердикт прозвучал в ответе. Порядок проверки от строгого к мягкому:
    «работать с осторожностью» содержит слово «работать» и иначе схлопнулось бы в него."""
    lowered = (text or "").lower()
    for verdict, markers in _VERDICT_MARKERS:
        if any(marker in lowered for marker in markers):
            return verdict
    return None


def _mentioned(text: str, discrepancy: dict) -> bool:
    # Достаточно, чтобы в ответе прозвучал предмет пометки: точную формулировку
    # детектора модель повторять не обязана.
    markers = _DISCREPANCY_MARKERS.get(discrepancy.get("code", ""), ())
    lowered = text.lower()
    return any(marker in lowered for marker in markers)


def validate(answer: str, context: dict) -> dict:
    text = answer or ""
    violations = []

    allowed = {str(item) for item in context.get("allowed_inns") or []}
    unknown = [value for value in inn_module.extract(text) if value not in allowed]
    if unknown:
        violations.append({"rule": UNKNOWN_INN, "detail": f"ИНН вне белого списка сессии: {', '.join(unknown)}"})

    risk_level = (context.get("verdict_basis") or {}).get("risk_level")
    expected = RISK_VERDICTS.get(risk_level or "UNKNOWN")
    stated = stated_verdict(text)
    if expected and stated and VERDICT_LEVEL[stated] < VERDICT_LEVEL[expected]:
        violations.append({
            "rule": VERDICT_MISMATCH,
            "detail": (
                f"Ответ мягче оценки банка: прозвучало «{stated}» при уровне риска "
                f"{risk_level}, которому соответствует «{expected}»"
            ),
        })

    omitted = [item["code"] for item in context.get("discrepancies") or [] if not _mentioned(text, item)]
    if omitted:
        violations.append({"rule": DISCREPANCY_OMITTED,
                           "detail": f"Не упомянуты расхождения: {', '.join(omitted)}"})

    return {"passed": not violations, "violations": violations}
