"""Блоки отчёта, оставшиеся в contractors.raw: они не нормализованы в таблицы,
потому что по ним не считает SQL (ARCHITECTURE.md)."""

from collections import Counter

from src.core.aggregates import iso
from src.core.normalize import to_date, to_int, to_text

INSPECTION_RESULTS = {
    "InspectionsViolationNotDetected": "violation_not_detected",
    "InspectionsUnknownResult": "unknown_result",
    "InspectionsCanceled": "canceled",
}


def _items(raw: dict, block: str) -> list[dict]:
    value = (raw or {}).get(block)
    return value if isinstance(value, list) else []


def phones(raw: dict) -> list[str]:
    numbers = []
    for item in _items(raw, "phones"):
        number = "".join(filter(None, [to_text(item.get("phoneCode")), to_text(item.get("phoneNumber"))]))
        if number:
            numbers.append(number)
    return numbers


def branches(raw: dict) -> dict:
    info = (raw or {}).get("branchesInfo") or {}
    return {
        "count": to_int(info.get("branchesCount")) or 0,
        "items": [
            {"name": to_text(b.get("name")), "address": to_text(b.get("address"))}
            for b in info.get("branches") or []
        ],
    }


def activity(raw: dict) -> dict:
    info = (raw or {}).get("kindsOfActivityInfo") or {}
    main = info.get("mainKindOfActivity") or {}
    others = [item for item in info.get("otherKindsOfActivity") or [] if item.get("code")]

    divisions: Counter = Counter()
    sample: dict[str, str] = {}
    for item in others:
        code = to_text(item.get("code")) or ""
        division = code.split(".")[0]
        if not division:
            continue
        divisions[division] += 1
        sample.setdefault(division, to_text(item.get("description")) or "")

    return {
        "main_okved": {"code": to_text(main.get("code")), "description": to_text(main.get("description"))},
        "okved_count": (1 if main.get("code") else 0) + len(others),
        # Справочника разделов ОКВЭД в источнике нет, поэтому вместо названия раздела
        # отдаём описание одного из входящих в него кодов и честно называем поле.
        "by_division": [
            {"division": division, "count": count, "sample_description": sample.get(division)}
            for division, count in divisions.most_common()
        ],
    }


def licenses(raw: dict) -> dict:
    items = [
        {
            "number": to_text(item.get("number")),
            "name": to_text(item.get("name")),
            "issuing_authority": to_text(item.get("issuingAuthority")),
            "issue_date": iso(to_date(item.get("issueDate"))),
            "end_date": iso(to_date(item.get("endDate"))),
            "status": to_text(item.get("status")),
        }
        for item in _items(raw, "licenses")
    ]
    return {"count": len(items), "items": items}


AUTHORITY_LIMIT = 5


def inspections(raw: dict, recent_limit: int = 5, authority_limit: int = AUTHORITY_LIMIT) -> dict:
    rows = _items(raw, "inspections")
    if not rows:
        return {"total": 0, "by_result": {}, "by_form": {}, "authorities": [],
                "authorities_total": 0, "authorities_other": 0, "period": None, "recent": []}

    parsed = [
        {
            "form": to_text(item.get("form")),
            "authority": to_text(item.get("authorityName")),
            "start_date": iso(to_date(item.get("startDate"))),
            "end_date": iso(to_date(item.get("endDate"))),
            "status": to_text(item.get("inspectionStatus")),
        }
        for item in rows
    ]
    results: Counter = Counter(
        INSPECTION_RESULTS.get(item["status"] or "", "other") for item in parsed
    )
    dates = sorted(item["start_date"] for item in parsed if item["start_date"])
    ordered = sorted(parsed, key=lambda item: item["start_date"] or "", reverse=True)

    return {
        "total": len(parsed),
        "by_result": dict(results),
        "by_form": dict(Counter(item["form"] for item in parsed if item["form"])),
        # Список органов не ограничивался, и один контрагент с 52 надзорными
        # органами раздувал набор «Деятельность» вчетверо (ARCHITECTURE.md).
        **_authorities(parsed, authority_limit),
        "period": {"first": dates[0], "last": dates[-1]} if dates else None,
        "recent": ordered[:recent_limit],
    }


def _authorities(parsed: list[dict], limit: int) -> dict:
    counted = Counter(item["authority"] for item in parsed if item["authority"]).most_common()
    return {
        "authorities": [{"name": name, "count": count} for name, count in counted[:limit]],
        "authorities_total": len(counted),
        "authorities_other": max(len(counted) - limit, 0),
    }


def procurements(raw: dict) -> dict:
    rows = _items(raw, "procurements")
    by_year: dict[int, dict] = {}
    by_law: dict[str, dict] = {}
    wins = signed = 0
    amount: int | None = None

    for item in rows:
        year = to_int(item.get("procurementsYear"))
        law = to_text(item.get("federalLawCode"))
        win = to_int(item.get("tenderWinnerCnt")) or 0
        sign = to_int(item.get("contractSignedCnt")) or 0
        # contractSignedAmt отсутствует в части записей — суммируем только известное,
        # иначе пропуск превратится в ноль.
        value = to_int(item.get("contractSignedAmt"))

        wins += win
        signed += sign
        if value is not None:
            amount = (amount or 0) + value

        for key, store in ((year, by_year), (law, by_law)):
            if key is None:
                continue
            bucket = store.setdefault(key, {"tender_wins": 0, "contracts_signed": 0, "amount": None})
            bucket["tender_wins"] += win
            bucket["contracts_signed"] += sign
            if value is not None:
                bucket["amount"] = (bucket["amount"] or 0) + value

    return {
        "tender_wins": wins,
        "contracts_signed": signed,
        "contracts_amount": amount,
        "by_year": [{"year": year, **data} for year, data in sorted(by_year.items())],
        "by_law": [{"law": law, **data} for law, data in sorted(by_law.items())],
    }
