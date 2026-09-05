"""Очистка списков для человека от служебных вставок (ARCHITECTURE.md).

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
# Правило 12 промпта модель нарушает регулярно и во всех сочетаниях раскладок:
# «ZSK», «ZCK», «ZСК», «ЗCK». Классы символов перечисляют обе кириллицы и обе
# латиницы, иначе смешанное написание проскакивает. Замена однозначна: другого
# слова из этих трёх букв в наших текстах не бывает.
_ZSK = re.compile(r"\b[ZЗ][SCСЅ][KКK]\b", re.IGNORECASE)


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


def zsk(text: str) -> str:
    """Только замена раскладки, без чистки скобок.

    Нужна для answer, summary и analysis: они уходят в БД и в якорь сессии,
    и там должно лежать ровно то, что показано на экране. Замена не меняет
    длину строки — иначе разъехалась бы дописка расхождений, которая считает
    отступ по длине уже отданного потока (§13.6).
    """
    return _ZSK.sub("ЗСК", text or "")


def lines(items: list[str]) -> list[str]:
    return [cleaned for cleaned in (line(item) for item in items or []) if cleaned]


def join(label: str, text: str) -> str:
    """Склейка «кто: что» без двойной точки, когда label кончается сокращением."""
    if not label:
        return text
    separator = " " if label.rstrip().endswith(".") else ": "
    return f"{label.rstrip().rstrip(':')}{separator}{text}"


# Первая буква искомого слова в любой раскладке: по ней ищем начало возможного
# неполного совпадения на границе чанка.
_ZSK_START = re.compile(r"[ZЗ]", re.IGNORECASE)
# «ЗСК» — три буквы, значит незавершённым может оказаться хвост в две.
_HOLD = 2


class StreamCleaner:
    """Чистка ответа по мере его поступления (§13.6).

    Ответ уходит на экран дельтами, и постобработка целиком запрещена: история
    обязана совпадать с показанным. Поэтому чистим сам поток и придерживаем
    хвост, если он может оказаться началом «ЗСК»: слово регулярно приезжает
    двумя чанками, и без задержки замена бы его не увидела.

    Скобочные группы здесь не трогаем: открывающая и закрывающая скобки могут
    разъехаться на сотни символов, и удерживать такой хвост значит потерять
    стриминг ради косметики.
    """

    def __init__(self) -> None:
        self._tail = ""

    def feed(self, chunk: str) -> str:
        cleaned = _ZSK.sub("ЗСК", self._tail + (chunk or ""))
        cut = self._pending(cleaned)
        self._tail = cleaned[cut:]
        return cleaned[:cut]

    def flush(self) -> str:
        rest, self._tail = self._tail, ""
        return _ZSK.sub("ЗСК", rest)

    @staticmethod
    def _pending(text: str) -> int:
        """Позиция, с которой хвост может оказаться незавершённым «ЗСК»."""
        window = text[-_HOLD:]
        match = _ZSK_START.search(window)
        return len(text) if match is None else len(text) - len(window) + match.start()
