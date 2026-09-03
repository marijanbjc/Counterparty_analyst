import re

# Родовые слова остаются строчными: «Московская область», а не «Московская Область».
GENERIC_WORDS = {"область", "край", "округ", "автономный", "республика", "город"}


def _capitalize(word: str) -> str:
    return "-".join(part[:1].upper() + part[1:] if part else part for part in word.split("-"))


def _prettify(region: str) -> str:
    words = region.lower().split()
    return " ".join(
        _capitalize(word) if index == 0 or word not in GENERIC_WORDS else word
        for index, word in enumerate(words)
    )


# Адрес приходит в фиксированном формате «индекс, РЕГИОН, район, город, улица».
def parse_region(address: str | None) -> str | None:
    if not address:
        return None
    parts = [part.strip() for part in address.split(",")]
    if len(parts) < 2 or not parts[1]:
        return None
    region = re.sub(r"\s*\([^)]*\)", "", parts[1])
    region = re.sub(r"^Г\.?\s*", "", region, flags=re.IGNORECASE)
    return _prettify(region) or None
