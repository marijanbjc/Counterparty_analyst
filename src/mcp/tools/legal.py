from sqlalchemy.orm import Session

from src.core import aggregates
from src.db.contragents import repository
from src.db.models import Contractor
from src.mcp.responses import factor_items, for_contractor


def get_arbitration(inn: str, year_from: int | None = None, year_to: int | None = None) -> dict:
    """Арбитражные споры в агрегированном виде. Конкретных дел в источнике нет:
    ни номеров, ни сторон, ни предметов спора — описывать отдельные дела запрещено.
    Роль контрагента меняет смысл радикально: истец взыскивает свои деньги, ответчик
    рискует не рассчитаться. Поля pending — открытые дела, то есть текущий риск;
    остальное завершено. Общее число дел бери только из total_count: сумма дел истца
    и ответчика меньше общего числа, часть дел не классифицирована по стороне,
    складывать стороны нельзя."""

    def build(session: Session, contractor: Contractor) -> dict:
        by_year = repository.get_arbitration_years(session, contractor.inn, year_from, year_to)
        payload = aggregates.arbitration(contractor, by_year)
        return {**payload, "factors": factor_items(repository.get_factors(session, contractor.inn, ("arbitr",)))}

    return for_contractor(inn, build)


def get_execution_proceedings(inn: str, active_only: bool = True, limit: int = 5) -> dict:
    """Исполнительные производства — стадия принудительного взыскания после суда,
    более тревожный сигнал, чем сам спор. Возвращает две пары счётчиков: действующие
    взыскания и всего за историю, включая закрытые. Разница между ними может быть
    на два порядка, поэтому всегда уточняй, о каких именно идёт речь: закрытое
    производство 2014 года не является текущей проблемой. Полный список не отдаётся —
    только агрегат, крупнейшие действующие и распределение по годам возбуждения."""

    def build(session: Session, contractor: Contractor) -> dict:
        top = repository.get_top_execproc(session, contractor.inn, active_only=active_only, limit=min(limit, 20))
        payload = aggregates.execution_proceedings(
            contractor, top, repository.get_execproc_by_year(session, contractor.inn)
        )
        # Имя поля не должно врать: при active_only=False в топ попадают и закрытые.
        payload["top"] = payload.pop("top_active")
        payload["top_scope"] = "active" if active_only else "all"
        return {**payload, "factors": factor_items(repository.get_factors(session, contractor.inn, ("execproc",)))}

    return for_contractor(inn, build)
