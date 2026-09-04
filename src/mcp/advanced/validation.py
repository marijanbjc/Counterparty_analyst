"""Валидаторы вызываются кодом в узлах графа и модели не предоставляются (§8.4, §8.5)."""

from src.config.settings import get_settings
from src.core import validation


def validate_answer(answer: str, context: dict) -> dict:
    """Служебный. Три инварианта: ИНН из белого списка сессии, вердикт согласован
    с risk_level, расхождения детектора упомянуты в тексте."""
    return validation.validate(answer, context or {})


def validate_conclusions(answer: str, fact_pack: dict) -> dict:
    """Служебный, за флагом конфига. Второй проход LLM: проверка смысла, а не арифметики.
    Реализация — заглушка, включается после того, как основной контур заработает."""
    if not get_settings().llm_validator_enabled:
        return {"passed": True, "issues": [], "skipped": True, "reason": "disabled_in_config"}
    return {"passed": True, "issues": [], "skipped": True, "reason": "not_implemented"}
