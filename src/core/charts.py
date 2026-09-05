"""Данные для графиков — изображение не строится (ARCHITECTURE.md)."""

RUB, COUNT, PERCENT = "RUB", "count", "percent"

CHART_TYPES = (
    "revenue_profit",
    "execproc_timeline",
    "arbitration_sides",
    "balance_structure",
    "debt_vs_assets",
    "compare_metric",
)

COMPARE_METRICS = {
    "revenue": ("Выручка", RUB),
    "net_assets": ("Чистые активы", RUB),
    "current_debt": ("Текущий долг", RUB),
    "execproc_active": ("Действующие взыскания", COUNT),
    "negative_factors": ("Негативные факторы", COUNT),
}


def _series(name: str, points: list[int | None]) -> dict:
    return {"name": name, "points": points}


def _chart(chart_type: str, labels: list[str], series: list[dict], unit: str, sources: list[str]) -> dict:
    # Пропуск в ряду — разрыв, а не ноль: молчаливая замена превратила бы
    # отсутствие данных в утверждение о нулевом значении.
    missing = [
        label
        for index, label in enumerate(labels)
        if all(item["points"][index] is None for item in series)
    ]
    return {
        "type": chart_type,
        "labels": labels,
        "series": series,
        "unit": unit,
        "source_fields": sources,
        "missing_points": missing,
    }


def revenue_profit(years: list[dict]) -> dict:
    return _chart(
        "revenue_profit",
        [str(row["year"]) for row in years],
        [
            _series("Выручка", [row["proceeds"] for row in years]),
            _series("Прибыль", [row["profit"] for row in years]),
        ],
        RUB,
        ["financials.years.proceeds", "financials.years.profit"],
    )


def execproc_timeline(by_year: dict[str, int]) -> dict:
    labels = sorted(by_year)
    return _chart(
        "execproc_timeline",
        labels,
        [_series("Возбуждено производств", [by_year[label] for label in labels])],
        COUNT,
        ["execution_proceedings.by_year"],
    )


def arbitration_sides(by_year: list[dict]) -> dict:
    return _chart(
        "arbitration_sides",
        [str(row["year"]) for row in by_year],
        [
            _series("Истец", [row["plaintiff_count"] for row in by_year]),
            _series("Ответчик", [row["defendant_count"] for row in by_year]),
        ],
        COUNT,
        ["arbitration.by_year"],
    )


def balance_structure(years: list[dict], liabilities: list[dict]) -> dict:
    duties = {row["year"]: row["total_liabilities"] for row in liabilities}
    return _chart(
        "balance_structure",
        [str(row["year"]) for row in years],
        [
            _series("Активы", [row["total_assets"] for row in years]),
            _series("Обязательства", [duties.get(row["year"]) for row in years]),
            _series("Чистые активы", [row["net_assets"] for row in years]),
        ],
        RUB,
        ["balance_sheet.total_assets", "liabilities.total_liabilities", "balance_sheet.net_assets"],
    )


def debt_vs_assets(burden: dict) -> dict:
    return _chart(
        "debt_vs_assets",
        ["Текущий долг", "Чистые активы"],
        [_series("Сумма", [burden["current_debt"], burden["net_assets"]])],
        RUB,
        ["debt_burden.current_debt", "debt_burden.net_assets"],
    )


def compare_metric(rows: list[dict], metric: str) -> dict:
    title, unit = COMPARE_METRICS[metric]
    # Подписи берутся из строк по индексу, а не через словарь: у двух контрагентов
    # может совпасть краткое наименование, и словарь схлопнул бы их в одну точку.
    return _chart(
        "compare_metric",
        [row["short_name"] for row in rows],
        [_series(title, [row.get(metric) for row in rows])],
        unit,
        [f"matrix.{metric}"],
    )
