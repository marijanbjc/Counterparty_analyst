import re

# 12 раньше 10, иначе от ИНН предпринимателя откусывается первая десятка цифр;
# границы по цифрам отсекают ОГРН и прочие длинные номера.
INN_PATTERN = re.compile(r"(?<!\d)(?:\d{12}|\d{10})(?!\d)")

_WEIGHTS_10 = (2, 4, 10, 3, 5, 9, 4, 6, 8)
_WEIGHTS_11 = (7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
_WEIGHTS_12 = (3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8)

FORMAT_HINT = (
    "ИНН — это 10 цифр для организации или 12 цифр для индивидуального предпринимателя, "
    "без пробелов и разделителей."
)


def _checksum(digits: list[int], weights: tuple[int, ...]) -> int:
    return sum(weight * digit for weight, digit in zip(weights, digits)) % 11 % 10


def is_valid(value: str) -> bool:
    value = (value or "").strip()
    if not value.isdigit() or len(value) not in (10, 12):
        return False
    digits = [int(char) for char in value]
    if len(digits) == 10:
        return _checksum(digits[:9], _WEIGHTS_10) == digits[9]
    return _checksum(digits[:10], _WEIGHTS_11) == digits[10] and _checksum(digits[:11], _WEIGHTS_12) == digits[11]


def entity_kind(value: str) -> str | None:
    if not is_valid(value):
        return None
    return "organization" if len(value) == 10 else "sole_proprietor"


def extract(text: str) -> list[str]:
    seen: dict[str, None] = {}
    for candidate in INN_PATTERN.findall(text or ""):
        if is_valid(candidate):
            seen.setdefault(candidate, None)
    return list(seen)
