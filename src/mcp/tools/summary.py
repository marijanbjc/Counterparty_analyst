from sqlalchemy.orm import Session

from src.core import debt, factpack, legal_status
from src.db.contragents import repository
from src.db.models import Contractor
from src.mcp.responses import factor_items, for_contractor

CHAPTERS = ("finance", "arbitr", "execproc", "reestrs", "manager", "okved", "relatedComp", "license", "site", "filials")


def get_risk_factors(inn: str, chapter: str | None = None) -> dict:
    """Все готовые формулировки рисков от банка одним запросом, с фильтром по разделу.
    Возвращает негативные и позитивные факторы. Предметные инструменты возвращают
    свои факторы сами — этот нужен для обзорных вопросов и для общего разбора.
    Если negative_shown меньше negative_total, показана только часть — скажи
    об этом пользователю, чтобы он не считал список исчерпывающим."""

    def build(session: Session, contractor: Contractor) -> dict:
        chapters = (chapter,) if chapter else ()
        rows = repository.get_factors(session, contractor.inn, chapters)
        negative = [row for row in rows if row.polarity == "negative"]
        return {
            "chapter": chapter,
            "negative": factor_items(negative),
            "positive": factor_items([row for row in rows if row.polarity == "positive"]),
            "negative_total": contractor.negative_factors_count,
            "negative_shown": len(negative),
        }

    return for_contractor(inn, build)


def get_contractor_full(inn: str) -> dict:
    """Готовая сводка по контрагенту одним вызовом: оба светофора, правовой статус,
    профиль, финансы, суды, взыскания, факторы риска и результат детектора расхождений.
    Вызывай в начале разбора, дальше уточняй предметными инструментами. Блок
    discrepancies содержит расхождения между формальной оценкой риска и фактами —
    если он не пуст, его содержимое обязательно проговаривается в ответе.
    Поле legal_status со значением severity = "critical" означает банкротство
    или предстоящее исключение из реестра и называется всегда, независимо от светофора."""

    def build(session: Session, contractor: Contractor) -> dict:
        pack = factpack.build(session, contractor.inn, mode=factpack.FULL)
        pack.pop("inn", None)
        pack.pop("short_name", None)
        pack.pop("as_of", None)
        marks = [row for row in repository.get_factors(session, contractor.inn, ("reestrs",))
                 if row.code == "liquidationStatus"]
        # Правовой статус подмешивается всегда: банкротство не должно зависеть
        # от того, догадается ли модель запросить get_legal_status (§4.2).
        pack["legal_status"] = legal_status.build(contractor, factor_items(marks))
        pack["debt_burden"] = debt.build(contractor, repository.get_fin_reports(session, contractor.inn))
        return pack

    return for_contractor(inn, build)
