"""Профиль исполнения — параметр конвейера, а не вторая ветка кода (§8.4).

В профиле нет ни одного поля, влияющего на оценку риска: вердикт, оба светофора
и расхождения детектора одинаковы на обоих тарифах (§8.2).
"""

from dataclasses import dataclass
from functools import lru_cache

from src.config.settings import get_settings

BASIC = "basic"
EXTENDED = "extended"

FACTPACK_SLIM = "slim"
FACTPACK_FULL = "full"

BASIC_MAX_ITERATIONS = 0
EXTENDED_MAX_ITERATIONS = 4


@dataclass(frozen=True)
class ExecutionProfile:
    name: str
    attach_tools: bool
    max_iterations: int
    factpack_mode: str
    max_buttons: int
    allow_subagents: bool
    max_compare: int
    context_budget_share: float
    requests_limit: int
    label: str

    @property
    def budget_tokens(self) -> int:
        # llm_tpm_limit — минутное окно ключа поставщика, бюджет хода — сколько
        # кладём в один запрос. Это разные величины; context_token_budget держит
        # потолок, выше которого доля не поднимается ни на каком тарифе (§8.4).
        settings = get_settings()
        return min(int(settings.llm_tpm_limit * self.context_budget_share), settings.context_token_budget)


@lru_cache
def _profiles() -> dict[str, ExecutionProfile]:
    settings = get_settings()
    return {
        "free": ExecutionProfile(
            name=BASIC,
            attach_tools=False,
            max_iterations=BASIC_MAX_ITERATIONS,
            factpack_mode=FACTPACK_SLIM,
            max_buttons=settings.tariff_free_max_buttons,
            allow_subagents=False,
            max_compare=settings.tariff_free_max_compare,
            context_budget_share=settings.context_budget_share,
            requests_limit=settings.tariff_free_requests_limit,
            label="Бесплатный",
        ),
        "paid": ExecutionProfile(
            name=EXTENDED,
            attach_tools=True,
            max_iterations=EXTENDED_MAX_ITERATIONS,
            factpack_mode=FACTPACK_FULL,
            max_buttons=settings.tariff_paid_max_buttons,
            allow_subagents=True,
            max_compare=settings.tariff_paid_max_compare,
            context_budget_share=settings.context_budget_share,
            requests_limit=settings.tariff_paid_requests_limit,
            label="Платный",
        ),
    }


def profile_for(tariff: str) -> ExecutionProfile:
    profiles = _profiles()
    # Неизвестный тариф деградирует в basic: опечатка не открывает платный контур.
    return profiles.get(tariff, profiles["free"])
