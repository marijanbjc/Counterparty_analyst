from sqlalchemy.orm import Session

from src.core import raw_blocks
from src.db.contragents import repository
from src.db.models import Contractor
from src.mcp.responses import factor_items, for_contractor

MASS_OKVED = "massOkved"


def get_activity(inn: str) -> dict:
    """Виды деятельности по ЕГРЮЛ: основной код ОКВЭД, общее количество кодов
    и группировка по разделам. Полный список кодов не отдаётся — их бывает больше сотни.
    Флаг mass_okved означает, что среди кодов есть входящие в перечень, который
    по статистике налоговой чаще выбирают фирмы-однодневки; это повод насторожиться,
    но не признак нарушения. Флаг приходит готовым: не выводи его самостоятельно
    из количества кодов и используй приложенную формулировку банка."""

    def build(session: Session, contractor: Contractor) -> dict:
        rows = repository.get_factors(session, contractor.inn, ("okved",))
        flagged = next((row for row in rows if row.code == MASS_OKVED and row.polarity == "negative"), None)
        return {
            **raw_blocks.activity(contractor.raw),
            "mass_okved": {"flag": flagged is not None, "name": flagged.name if flagged else None},
            "factors": factor_items(rows),
        }

    return for_contractor(inn, build)


def get_licenses(inn: str) -> dict:
    """Лицензии и разрешительные документы: вид деятельности, выдавший орган, дата выдачи,
    статус. Нулевое количество означает, что лицензий в отчёте нет, и это не означает
    работу без лицензии — большинству видов деятельности лицензия не требуется.
    Трактовать ноль как нарушение запрещено."""

    def build(session: Session, contractor: Contractor) -> dict:
        return {
            **raw_blocks.licenses(contractor.raw),
            "factors": factor_items(repository.get_factors(session, contractor.inn, ("license",))),
        }

    return for_contractor(inn, build)


def get_inspections(inn: str) -> dict:
    """Проверки государственных надзорных органов: сколько, кем, когда и с каким
    результатом. Большое количество проверок само по себе не негатив — значительная
    их часть является профилактическими визитами и предостережениями, а не проверками
    по факту нарушения. Смотри на by_result: violation_not_detected означает,
    что нарушений не выявлено."""

    def build(session: Session, contractor: Contractor) -> dict:
        return raw_blocks.inspections(contractor.raw)

    return for_contractor(inn, build)


def get_procurements(inn: str) -> dict:
    """Участие в государственных закупках: победы в тендерах, число и сумма подписанных
    контрактов, разбивка по годам и законам. Это положительный сигнал: контрагент
    прошёл проверку государственного заказчика и исполнял контракты. Отсутствие
    закупок нейтрально и ни о чём не говорит — большинство компаний в них не участвует."""

    def build(session: Session, contractor: Contractor) -> dict:
        return raw_blocks.procurements(contractor.raw)

    return for_contractor(inn, build)
