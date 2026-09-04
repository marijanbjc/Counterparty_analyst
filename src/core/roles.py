ROLE_CHAPTERS = {
    "finance": ("finance",),
    "legal": ("arbitr", "execproc"),
    "security": ("reestrs", "manager"),
    "activity": ("okved", "license"),
    # Не область, а её отсутствие: фильтр по главам не накладывается.
    "general": (),
}

DEFAULT_ROLE = "general"


def chapters_for(role: str | None) -> tuple[str, ...]:
    return ROLE_CHAPTERS.get(role or DEFAULT_ROLE, ())
