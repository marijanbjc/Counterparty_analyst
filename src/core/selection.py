"""Работа с несколькими контрагентами — ARCHITECTURE.md"""

from sqlalchemy.orm import Session

from src.core import aggregates, debt, discrepancy, factpack, legal_status
from src.core.legal_status import CRITICAL
from src.db.contragents import repository
from src.db.models import Contractor

RISK_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
SEVERITY_ORDER = {"none": 0, "attention": 1, "critical": 2}
RANK_CRITERIA = ("risk", "debt_burden", "revenue", "age")

# Порядок колонок сводки зависит от фокуса: модель читает объект сверху вниз,
# поэтому первым должно идти то, ради чего сравнение затеяли (§7.1).
_IDENTITY = ("inn", "short_name")
_RISK = ("risk_level", "zsk_risk_level", "legal_severity", "legal_reason_code",
         "negative_factors", "discrepancies")
_FINANCE = ("financials_available", "revenue", "profit", "net_assets", "negative_net_assets")
_DEBT = ("current_debt", "debt_to_net_assets", "debt_comparable", "execproc_active",
         "arbitration_total", "arbitration_pending_defendant")
_PROFILE = ("age_years", "company_size")

COLUMN_ORDER = {
    "finance": _IDENTITY + _FINANCE + _DEBT + _RISK + _PROFILE,
    "legal": _IDENTITY + _DEBT + _RISK + _FINANCE + _PROFILE,
    "security": _IDENTITY + _RISK + _PROFILE + _DEBT + _FINANCE,
    "activity": _IDENTITY + _PROFILE + _RISK + _FINANCE + _DEBT,
}
DEFAULT_ORDER = _IDENTITY + _RISK + _FINANCE + _DEBT + _PROFILE

REGION_AND_ACTIVITY = "region_and_activity"
ACTIVITY_ONLY = "activity_only"
NO_MATCH = "none"


def _row(session: Session, contractor: Contractor) -> dict:
    reports = repository.get_fin_reports(session, contractor.inn)
    financials = aggregates.financials(reports)
    latest = max(reports, key=lambda r: r.year) if reports else None
    burden = debt.build(contractor, reports)
    arbitration = aggregates.arbitration(contractor, [])
    status = legal_status.build(contractor)
    return {
        "inn": contractor.inn,
        "short_name": contractor.short_name,
        "risk_level": contractor.risk_level,
        "zsk_risk_level": contractor.zsk_risk_level,
        "legal_severity": status["severity"],
        "legal_reason_code": status["reason_code"],
        "age_years": contractor.years_from_registration,
        "company_size": contractor.company_size,
        "financials_available": financials["available"],
        "revenue": aggregates.latest_revenue(reports),
        "profit": latest.profit if latest else None,
        "net_assets": burden["net_assets"],
        "negative_net_assets": burden["negative_net_assets"],
        "current_debt": burden["current_debt"],
        "debt_to_net_assets": burden["debt_to_net_assets"],
        "debt_comparable": burden["comparable"],
        "execproc_active": contractor.execproc_active,
        # История и текущее по судам — разные величины: у половины базы дела
        # были и закончились, и показывать только текущие значит скрыть опыт
        # судебных споров (ARCHITECTURE.md).
        "arbitration_total": arbitration["total_count"],
        "arbitration_pending_defendant": arbitration["as_defendant"]["pending_count"],
        "negative_factors": contractor.negative_factors_count,
        # Числом расхождения были непригодны: модель писала «одно несоответствие»,
        # и что именно за несоответствие, пользователь узнать не мог. Текст уже
        # сформулирован детектором — отдаём его как есть (ARCHITECTURE.md).
        "discrepancies": [
            item["text"]
            for item in discrepancy.detect(contractor, burden["revenue"], financials["available"])
        ],
    }


def _ordered(row: dict, focus: str | None) -> dict:
    order = COLUMN_ORDER.get(focus or "", DEFAULT_ORDER)
    return {name: row[name] for name in order if name in row}


def _differences(rows: list[dict]) -> list[dict]:
    found = []
    ranked = [r for r in rows if r["risk_level"] in RISK_ORDER]
    if ranked and len({r["risk_level"] for r in ranked}) > 1:
        worst = max(ranked, key=lambda r: RISK_ORDER[r["risk_level"]])
        found.append({"metric": "risk_level", "text": f"Худший уровень риска у {worst['short_name']}: {worst['risk_level']}"})

    critical = [r for r in rows if r["legal_severity"] == "critical"]
    if critical:
        names = ", ".join(r["short_name"] for r in critical)
        found.append({"metric": "legal_status", "text": f"Процедура прекращения или банкротства: {names}"})

    burdened = [r for r in rows if r["debt_to_net_assets"] is not None]
    if burdened:
        worst = max(burdened, key=lambda r: r["debt_to_net_assets"])
        if worst["debt_to_net_assets"] > 0:
            share = round(worst["debt_to_net_assets"] * 100)
            found.append({"metric": "debt_burden", "text": f"Наибольшая долговая нагрузка у {worst['short_name']}: {share} % чистых активов"})

    negative_assets = [r for r in rows if r["negative_net_assets"]]
    if negative_assets:
        names = ", ".join(r["short_name"] for r in negative_assets)
        found.append({"metric": "net_assets", "text": f"Отрицательные чистые активы: {names}"})

    no_reports = [r for r in rows if not r["financials_available"]]
    if no_reports:
        names = ", ".join(r["short_name"] for r in no_reports)
        found.append({"metric": "financials", "text": f"Финансовая отчётность отсутствует: {names}. Это отсутствие информации, а не показатель"})

    if len({r["negative_factors"] for r in rows}) > 1:
        worst = max(rows, key=lambda r: r["negative_factors"])
        found.append({"metric": "negative_factors", "text": f"Больше всего негативных факторов у {worst['short_name']}: {worst['negative_factors']}"})
    return found


# Отсутствие данных не равно плохому показателю, поэтому такие контрагенты
# не проваливаются в конец рейтинга, а выносятся отдельной группой (§7.1).
_RANKERS = {
    "risk": (lambda r: r["risk_level"] in RISK_ORDER,
             lambda r: (RISK_ORDER[r["risk_level"]], SEVERITY_ORDER.get(r["legal_severity"], 0))),
    "debt_burden": (lambda r: r["debt_to_net_assets"] is not None, lambda r: r["debt_to_net_assets"]),
    "revenue": (lambda r: r["revenue"] is not None, lambda r: -r["revenue"]),
    "age": (lambda r: r["age_years"] is not None, lambda r: -r["age_years"]),
}


def _ranking(rows: list[dict], criterion: str | None) -> tuple[list[dict], list[str]]:
    """Места по критерию. Равные ключи получают ОДНО место (§7.1).

    Сквозная нумерация делала из двух одинаковых контрагентов первого и второго,
    и на вопрос «кто лучше» выходил ответ, которого в данных нет.
    """
    if criterion not in _RANKERS:
        return [], []
    comparable, key = _RANKERS[criterion]
    ranked = sorted([r for r in rows if comparable(r)], key=key)
    places: list[dict] = []
    for index, row in enumerate(ranked):
        same = index > 0 and key(row) == key(ranked[index - 1])
        place = places[-1]["place"] if same else index + 1
        places.append({"place": place, "inn": row["inn"], "short_name": row["short_name"]})
    return places, [r["inn"] for r in rows if not comparable(r)]


def compare(session: Session, inns: list[str], focus: str | None = None, rank_by: str | None = None) -> dict:
    unique = list(dict.fromkeys(inns))
    contractors = [(i, repository.get_contractor(session, i)) for i in unique]
    found = [c for _, c in contractors if c is not None]
    rows = [_row(session, c) for c in found]
    ranking, not_comparable = _ranking(rows, rank_by)
    return {
        "items": factpack.build_many(session, [c.inn for c in found]),
        "matrix": [_ordered(row, focus) for row in rows],
        "differences": _differences(rows),
        "ranking": ranking,
        "rank_by": rank_by if rank_by in _RANKERS else None,
        "not_comparable": not_comparable,
        "not_found": [i for i, c in contractors if c is None],
    }


# Подбор альтернативы — ARCHITECTURE.md Фильтры ТОЛЬКО по открытым
# реестрам: ЕГРЮЛ, ФССП, кад.арбитр. Уровень риска и ЗСК сюда не входят и наружу
# не отдаются — отфильтровать по ним значит неявно выдать оценку банка по
# контрагенту, которого клиент не запрашивал.
ALTERNATIVES_LIMIT = 3
# Кандидатов перебираем с запасом: фильтры отсеивают большинство найденных.
_ALTERNATIVES_POOL = 50


def _is_clean(session: Session, contractor: Contractor) -> bool:
    if contractor.status != "CURRENT":
        return False
    if legal_status.build(contractor)["severity"] == CRITICAL:
        return False
    if (contractor.execproc_active or 0) > 0:
        return False
    pending = aggregates.arbitration(contractor, [])["as_defendant"]["pending_count"]
    return not pending


def alternatives(session: Session, contractor: Contractor, same_region: bool = True) -> dict:
    """Похожие компании без банкротства, взысканий и незавершённых исков.

    Отдаём только открытые сведения и не больше трёх: длинный список
    превращается в выборку из базы и раскрывает её объём. Сколько нашлось
    всего, не сообщаем никогда (§7, правило 10).
    """
    division = (contractor.main_okved_code or "").split(".")[0]
    if not division:
        return {"items": [], "same_region": same_region, "region": contractor.region,
                "can_widen": False, "okved": None}

    region = contractor.region if same_region else None
    rows = repository.similar_contractors(
        session, contractor.inn, division, region, _ALTERNATIVES_POOL
    )
    clean = [row for row in rows if _is_clean(session, row)][:ALTERNATIVES_LIMIT]
    # Предлагать снять регион можно только когда он вообще был задан и когда
    # без него что-то найдётся: пустая кнопка хуже честного отказа.
    can_widen = bool(same_region and contractor.region and not clean) and any(
        _is_clean(session, row)
        for row in repository.similar_contractors(
            session, contractor.inn, division, None, _ALTERNATIVES_POOL
        )
    )
    return {
        "items": [
            {
                "inn": row.inn,
                "short_name": row.short_name,
                "region": row.region,
                "main_okved": row.main_okved_description,
            }
            for row in clean
        ],
        "same_region": same_region,
        "region": contractor.region,
        "can_widen": can_widen,
        "okved": contractor.main_okved_description,
    }


def similar(session: Session, contractor: Contractor, limit: int) -> dict:
    code = contractor.main_okved_code or ""
    division = code.split(".")[0]
    if not division:
        return {"match_level": NO_MATCH, "basis": {"region": contractor.region, "okved_division": None},
                "total": 0, "items": []}

    # Регион известен не у всех: без него совпадение изначально только по виду
    # деятельности, и выдавать его за географическое нельзя.
    level = REGION_AND_ACTIVITY if contractor.region else ACTIVITY_ONLY
    rows = repository.similar_contractors(session, contractor.inn, division, contractor.region, limit)
    if not rows and contractor.region:
        # Регион сузил выборку до пустой — деградируем до одного раздела ОКВЭД,
        # но обязаны сообщить это модели через match_level (§7.2).
        level = ACTIVITY_ONLY
        rows = repository.similar_contractors(session, contractor.inn, division, None, limit)

    return {
        "match_level": level if rows else NO_MATCH,
        "basis": {"region": contractor.region, "okved_division": division},
        "total": len(rows),
        "items": [
            {
                "inn": row.inn,
                "short_name": row.short_name,
                "region": row.region,
                "main_okved": {"code": row.main_okved_code, "description": row.main_okved_description},
                "risk_level": row.risk_level,
                "zsk_risk_level": row.zsk_risk_level,
            }
            for row in rows
        ],
    }
