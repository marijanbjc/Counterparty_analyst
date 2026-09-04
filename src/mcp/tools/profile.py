from sqlalchemy.orm import Session

from src.core import fns_flags, legal_status, raw_blocks
from src.core import inn as inn_module
from src.core.aggregates import iso
from src.db.contragents import repository
from src.db.models import Contractor
from src.mcp.responses import NOT_APPLICABLE, factor_items, for_contractor

SOLE_PROPRIETOR = "sole_proprietor"


def _is_sole(contractor: Contractor) -> bool:
    return inn_module.entity_kind(contractor.inn) == SOLE_PROPRIETOR


def get_basic_info(inn: str) -> dict:
    """Регистрационные и контактные данные контрагента: наименования, идентификаторы,
    дата регистрации и возраст, адрес и регион, телефоны, руководитель, налоговый режим,
    филиалы. Вызывай первым в любом сценарии проверки — задаёт рамку для остальных
    инструментов. Численность персонала в источнике отсутствует, поле всегда пустое.
    КПП у индивидуального предпринимателя не существует — это неприменимое поле,
    а не пропуск данных. Обрати внимание на должность руководителя: «конкурсный
    управляющий» означает, что в отношении компании идёт процедура банкротства."""

    def build(session: Session, contractor: Contractor) -> dict:
        sole = _is_sole(contractor)
        return {
            "full_name": contractor.full_name,
            "ogrn": contractor.ogrn,
            "okpo": contractor.okpo,
            "kpp": NOT_APPLICABLE if sole else contractor.kpp,
            "entity_kind": inn_module.entity_kind(contractor.inn),
            "registered": iso(contractor.registration_date),
            "age_years": contractor.years_from_registration,
            "company_size": contractor.company_size,
            "address": contractor.address,
            "region": contractor.region,
            "phones": raw_blocks.phones(contractor.raw),
            "email": contractor.email,
            "website": contractor.website,
            "auth_person": {
                "name": contractor.auth_person_name,
                "position": contractor.auth_person_position,
                "since": iso(contractor.auth_person_date),
            },
            "tax_systems": NOT_APPLICABLE if sole else (contractor.tax_systems or []),
            "branches": raw_blocks.branches(contractor.raw),
            "staff": None,
            "factors": factor_items(repository.get_factors(session, contractor.inn, ("site", "filials"))),
        }

    return for_contractor(inn, build)


def get_legal_status(inn: str) -> dict:
    """Правоспособность контрагента по ЕГРЮЛ: действует ли юридическое лицо и не начата ли
    процедура его прекращения. Ключевое: поле status почти всегда равно CURRENT
    и само по себе ничего не означает — смотри на status_reason и severity.
    Значение severity = "critical" означает банкротство или предстоящее исключение
    из реестра; такой факт обязательно проговаривается в ответе, даже если светофор
    зелёный. Значение "attention" — маркер грядущих изменений, о нём стоит упомянуть
    как о поводе уточнить."""

    def build(session: Session, contractor: Contractor) -> dict:
        rows = repository.get_factors(session, contractor.inn, ("reestrs",))
        marks = [row for row in rows if row.code == "liquidationStatus"]
        return legal_status.build(contractor, factor_items(marks))

    return for_contractor(inn, build)


def get_fns_flags(inn: str) -> dict:
    """Метки налоговой службы и метки по руководителю: блокировка счетов, массовый
    или фиктивный адрес, недостоверные регистрационные данные, массовый или номинальный
    руководитель, налоговые долги, недобросовестный поставщик. По каждой метке возвращается
    признак наличия и готовая формулировка банка — используй её, не сочиняй свою.
    Блокировка счетов по постановлению ФНС — распространённая ситуация, банк и налоговая
    обязаны её применять по требованиям регулятора; подавай её как повод уточнить,
    а не как приговор. Метки фиктивного адреса и номинального руководителя весомее."""

    def build(session: Session, contractor: Contractor) -> dict:
        return fns_flags.build(repository.get_factors(session, contractor.inn, fns_flags.CHAPTERS))

    return for_contractor(inn, build)


def get_ownership(inn: str) -> dict:
    """Владельцы и руководитель: уставный капитал, состав учредителей с долями, текущий
    руководитель и дата его назначения. Для индивидуального предпринимателя весь блок
    неприменим — учредителей и уставного капитала у него не бывает, и это не пропуск
    данных. Истории смены руководителя в источнике нет: утверждать, что директор
    менялся или менялся часто, нельзя."""

    def build(session: Session, contractor: Contractor) -> dict:
        auth_person = {
            "name": contractor.auth_person_name,
            "position": contractor.auth_person_position,
            "since": iso(contractor.auth_person_date),
        }
        if _is_sole(contractor):
            return {
                "share_capital": NOT_APPLICABLE,
                "cofounders": NOT_APPLICABLE,
                "director_is_sole_founder": NOT_APPLICABLE,
                "auth_person": auth_person,
                "factors": [],
            }

        rows = repository.get_cofounders(session, contractor.inn)
        founders = [
            {
                "name": row.name,
                "inn": row.founder_inn,
                "amount": row.amount,
                "share": float(row.share) if row.share is not None else None,
                "date_from": iso(row.date_from),
                "active": row.active,
            }
            for row in rows
        ]
        sole_founder = len(rows) == 1 and bool(
            contractor.auth_person_inn and contractor.auth_person_inn == rows[0].founder_inn
        )
        return {
            "share_capital": contractor.share_capital,
            "cofounders": founders,
            "director_is_sole_founder": sole_founder,
            "auth_person": auth_person,
            "factors": factor_items(repository.get_factors(session, contractor.inn, ("manager",))),
        }

    return for_contractor(inn, build)
