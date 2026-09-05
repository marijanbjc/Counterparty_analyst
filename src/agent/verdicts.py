"""Вердикт считает код, модель его объясняет (§5.3).

Эскалация только по severity правового статуса: хотя бы одно расхождение детектора
есть у половины базы, и поднимать вердикт по каждому значило бы объявить эту половину
нежелательной. Банкротство и предстоящее исключение из ЕГРЮЛ — другое дело.

Critical переводит вердикт сразу в «Не рекомендуется», а не на ступень выше.
Шаг вверх давал «Работать с осторожностью» при открытом конкурсном производстве:
на экране это читалось как противоречие — в тексте банкротство, в вердикте
предложение работать. Под critical попадают только банкротство и предстоящее
исключение из ЕГРЮЛ; оба означают, что лица скоро не будет.

Светофор банка при этом не трогается: risk_level остаётся в досье как есть,
меняется только наш производный вердикт (§8.2).
"""

from typing import Any

from src.core.legal_status import CRITICAL
from src.core.report import verdict_for

WORK = "Работать"
WORK_WITH_CARE = "Работать с осторожностью"
NOT_RECOMMENDED = "Не рекомендуется"


def decide(fact_pack: dict[str, Any]) -> dict[str, Any]:
    basis = fact_pack.get("verdict_basis") or {}
    status = fact_pack.get("legal_status") or {}
    base = verdict_for(basis.get("risk_level"))
    escalated = status.get("severity") == CRITICAL
    return {
        "verdict": NOT_RECOMMENDED if escalated else base,
        "base_verdict": base,
        "escalated": escalated,
        "reason": status.get("status_reason") if escalated else None,
    }


def apply(result: dict[str, Any], fact_pack: dict[str, Any]) -> dict[str, Any]:
    """Накладывает эскалацию на готовый отчёт `core/report.py`, который считает
    вердикт без правового статуса. Причина называется прямым текстом: банкротство
    проговаривается всегда, даже при зелёном светофоре (§8.2)."""
    decision = decide(fact_pack)
    if not decision["escalated"]:
        return result
    note = f"Вердикт повышен до «{decision['verdict']}»: {decision['reason']}."
    return {
        **result,
        "verdict": decision["verdict"],
        "summary": f"{result['summary']} {note}",
        "analysis": f"{result['analysis']}\n{note}",
    }
