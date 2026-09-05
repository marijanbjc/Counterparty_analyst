"""Очистка списков для человека от служебных вставок (known_issues.md §14.1).

Сплошную чистку регуляркой делать нельзя: форма протечки произвольна — со знаком
равенства и без, в скобках и в тексте, прозой. Правило, достаточно широкое, чтобы
поймать всё, начнёт резать нормальные предложения.

Поэтому берём узкий и безопасный случай — скобочную группу без единой кириллической
буквы, но с латиницей. Он покрывает все наблюдавшиеся протечки
(«(severity = critical)», «(discrepancy)», «(pending_count = 0)») и не может
испортить связный текст: скобки с русскими словами, суммами и датами не трогаются.
"""

import re

_PARENS = re.compile(r"\s*[(\[]([^()\[\]]*)[)\]]")
_CYRILLIC = re.compile(r"[а-яё]", re.IGNORECASE)
_LATIN = re.compile(r"[a-z]", re.IGNORECASE)
# Правило 12 промпта модель нарушает регулярно: «ZSK», «ZCK», «ЗCK» вперемешку
# латиницей и кириллицей. Замена детерминированная и однозначная.
_ZSK = re.compile(r"\bZ[SC]K\b", re.IGNORECASE)


def _drop(match: re.Match[str]) -> str:
    inner = match.group(1)
    technical = _LATIN.search(inner) and not _CYRILLIC.search(inner)
    return "" if technical else match.group(0)


def line(text: str) -> str:
    """Убирает технические скобки и приводит хвостовую пунктуацию в порядок."""
    cleaned = _ZSK.sub("ЗСК", text or "")
    cleaned = _PARENS.sub(_drop, cleaned)
    cleaned = re.sub(r"\s+([,.;:])", r"\1", cleaned)
    return re.sub(r"\s{2,}", " ", cleaned).strip()


def lines(items: list[str]) -> list[str]:
    return [cleaned for cleaned in (line(item) for item in items or []) if cleaned]


def join(label: str, text: str) -> str:
    """Склейка «кто: что» без двойной точки, когда label кончается сокращением."""
    if not label:
        return text
    separator = " " if label.rstrip().endswith(".") else ": "
    return f"{label.rstrip().rstrip(':')}{separator}{text}"
