from math import ceil

from src.config.settings import get_settings


def estimate(text: str) -> int:
    """Оценка по символам — единственный блок, которого API ещё не видел."""
    if not text:
        return 0
    settings = get_settings()
    return ceil(len(text) / settings.tokens_chars_per_token * settings.tokens_safety_margin)


def of_message(role: str, content: str, tokens: int | None) -> int:
    # tokens из БД — фактический расход реплики, он точнее любой оценки.
    return tokens if tokens is not None else estimate(content)


def system_prompt() -> int:
    return get_settings().tokens_system_prompt


def tools(scope: str) -> int:
    settings = get_settings()
    return {
        "core": settings.tokens_tools_core,
        "role": settings.tokens_tools_role,
        "all": settings.tokens_tools_all,
    }[scope]


def fact_pack(variant: str) -> int:
    settings = get_settings()
    return {
        "full": settings.tokens_factpack_full,
        "slim": settings.tokens_factpack_slim,
    }[variant]
