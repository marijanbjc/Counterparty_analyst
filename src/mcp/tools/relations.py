from sqlalchemy.orm import Session

from src.core.aggregates import iso
from src.db.contragents import repository
from src.db.models import Contractor
from src.mcp.responses import factor_items, for_contractor


def get_affiliations(inn: str, limit: int = 20) -> dict:
    """Связанные компании контрагента: наименования, ИНН, руководители. Поле
    same_director_count показывает, сколько из них возглавляет тот же человек —
    это признак группы компаний, а не случайных связей. in_database перечисляет
    те связанные компании, которые есть в базе и которые можно проверить остальными
    инструментами; обычно этот список пуст. Наличие связей само по себе нейтрально
    и рисков не означает."""

    def build(session: Session, contractor: Contractor) -> dict:
        rows = repository.get_related_companies(session, contractor.inn)
        director = (contractor.auth_person_name or "").strip().upper()
        items = [
            {
                "inn": row.related_inn,
                "ogrn": row.related_ogrn,
                "name": row.name,
                "registered": iso(row.registration_date),
                "auth_person_name": row.auth_person_name,
                "auth_person_position": row.auth_person_position,
                "same_director": bool(director and (row.auth_person_name or "").strip().upper() == director),
            }
            for row in rows
        ]
        known = repository.existing_inns(session, [item["inn"] for item in items if item["inn"]])
        return {
            "count": len(items),
            "same_director_count": sum(1 for item in items if item["same_director"]),
            "in_database": sorted(known),
            "returned": min(len(items), limit),
            "items": items[:limit],
            "factors": factor_items(repository.get_factors(session, contractor.inn, ("relatedComp",))),
        }

    return for_contractor(inn, build)
