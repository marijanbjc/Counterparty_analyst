"""Роутер хода: сценарий определяется числом ИНН в сообщении, а не догадкой модели (§1.5).

Все решения здесь детерминированы и стоят ноль токенов; квота проверяется первой,
чтобы исчерпанный лимит не оплачивался вызовом поставщика.
"""

from dataclasses import dataclass

from src.agent.profiles import within_quota
from src.core import inn as inn_module
from src.mcp.tools.selection import MAX_ITEMS

ASK = "ask"
CLARIFY = "clarify"
ANALYZE = "analyze"
COMPARE = "compare"
QUOTA_EXCEEDED = "quota_exceeded"
COMPARE_LIMIT = "compare_limit"

ASK_ANSWER = (
    "Назовите ИНН контрагента, которого нужно проверить. "
    f"{inn_module.FORMAT_HINT} "
    "Поиска по названию, отрасли или региону у меня нет — работаю по конкретному ИНН."
)


@dataclass(frozen=True)
class Route:
    scenario: str
    inns: tuple[str, ...] = ()
    needs_llm: bool = False
    answer: str | None = None  # готовая реплика, когда модель не нужна
    error: str | None = None  # ошибка ввода: 422


def choose(
    message: str,
    has_context: bool,
    requests_used: int,
    requests_limit: int,
    max_compare: int,
) -> Route:
    if not within_quota(requests_used, requests_limit):
        return Route(
            QUOTA_EXCEEDED,
            answer=(
                f"Лимит проверок исчерпан: использовано {requests_used} из {requests_limit}. "
                "Продолжить можно на платном тарифе — он снимает ограничение по числу проверок "
                f"и открывает сравнение до {MAX_ITEMS} контрагентов."
            ),
        )

    inns = tuple(inn_module.extract(message))

    if not inns:
        if has_context:
            return Route(CLARIFY, needs_llm=True)
        return Route(ASK, answer=ASK_ANSWER)

    if len(inns) == 1:
        return Route(ANALYZE, inns=inns, needs_llm=True)

    if len(inns) > MAX_ITEMS:
        return Route(
            COMPARE,
            inns=inns,
            error=f"За один раз сравниваю не больше {MAX_ITEMS} контрагентов, а в сообщении их {len(inns)}.",
        )

    if len(inns) > max_compare:
        return Route(
            COMPARE_LIMIT,
            inns=inns,
            answer=(
                f"На вашем тарифе сравнение до {max_compare} контрагентов, а в сообщении их {len(inns)}. "
                f"Оставьте {max_compare} ИНН или перейдите на платный тариф — там сравнение до {MAX_ITEMS}."
            ),
        )

    return Route(COMPARE, inns=inns, needs_llm=True)
