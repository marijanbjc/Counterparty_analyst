from sqlalchemy import extract, func, select
from sqlalchemy.orm import Session

from src.db.models import (
    ArbitrationByYear,
    Cofounder,
    Contractor,
    ExecutionProceeding,
    FinReport,
    RelatedCompany,
    ReputationalFactor,
)


def get_contractor(session: Session, inn: str) -> Contractor | None:
    return session.get(Contractor, inn)


def get_fin_reports(
    session: Session, inn: str, year_from: int | None = None, year_to: int | None = None
) -> list[FinReport]:
    query = select(FinReport).where(FinReport.inn == inn)
    if year_from is not None:
        query = query.where(FinReport.year >= year_from)
    if year_to is not None:
        query = query.where(FinReport.year <= year_to)
    return list(session.scalars(query.order_by(FinReport.year)))


def get_arbitration_years(
    session: Session, inn: str, year_from: int | None = None, year_to: int | None = None
) -> list[ArbitrationByYear]:
    query = select(ArbitrationByYear).where(ArbitrationByYear.inn == inn)
    if year_from is not None:
        query = query.where(ArbitrationByYear.year >= year_from)
    if year_to is not None:
        query = query.where(ArbitrationByYear.year <= year_to)
    return list(session.scalars(query.order_by(ArbitrationByYear.year)))


def get_top_execproc(session: Session, inn: str, active_only: bool = True, limit: int = 5) -> list[ExecutionProceeding]:
    query = select(ExecutionProceeding).where(ExecutionProceeding.inn == inn)
    if active_only:
        query = query.where(ExecutionProceeding.active.is_(True))
    return list(session.scalars(query.order_by(ExecutionProceeding.amount.desc().nullslast()).limit(limit)))


def get_execproc_by_year(session: Session, inn: str) -> dict[int, int]:
    year = extract("year", ExecutionProceeding.date).label("year")
    query = select(year, func.count()).where(ExecutionProceeding.inn == inn, ExecutionProceeding.date.isnot(None))
    rows = session.execute(query.group_by(year).order_by(year)).all()
    return {int(row[0]): row[1] for row in rows}


def get_factors(session: Session, inn: str, chapters: tuple[str, ...] = ()) -> list[ReputationalFactor]:
    query = select(ReputationalFactor).where(ReputationalFactor.inn == inn)
    if chapters:
        query = query.where(ReputationalFactor.chapter.in_(chapters))
    return list(session.scalars(query))


def get_related_companies(session: Session, inn: str) -> list[RelatedCompany]:
    return list(session.scalars(select(RelatedCompany).where(RelatedCompany.inn == inn)))


def get_cofounders(session: Session, inn: str) -> list[Cofounder]:
    return list(session.scalars(select(Cofounder).where(Cofounder.inn == inn)))


def count_related(session: Session, inn: str) -> int:
    return session.scalar(select(func.count()).select_from(RelatedCompany).where(RelatedCompany.inn == inn)) or 0


def _search_query(
    risk_levels: tuple[str, ...],
    zsk_levels: tuple[str, ...],
    okved_prefix: str | None,
    with_negative_factors: bool | None,
    region: str | None,
):
    query = select(Contractor)
    if region:
        query = query.where(Contractor.region == region)
    if risk_levels:
        query = query.where(Contractor.risk_level.in_(risk_levels))
    if zsk_levels:
        query = query.where(Contractor.zsk_risk_level.in_(zsk_levels))
    if okved_prefix:
        query = query.where(Contractor.main_okved_code.startswith(okved_prefix))
    if with_negative_factors is True:
        query = query.where(Contractor.negative_factors_count > 0)
    if with_negative_factors is False:
        query = query.where(Contractor.negative_factors_count == 0)
    return query


def search_contractors(
    session: Session,
    risk_levels: tuple[str, ...] = (),
    zsk_levels: tuple[str, ...] = (),
    okved_prefix: str | None = None,
    with_negative_factors: bool | None = None,
    region: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[Contractor]:
    query = _search_query(risk_levels, zsk_levels, okved_prefix, with_negative_factors, region)
    return list(session.scalars(query.order_by(Contractor.short_name).offset(offset).limit(limit)))


def count_search(
    session: Session,
    risk_levels: tuple[str, ...] = (),
    zsk_levels: tuple[str, ...] = (),
    okved_prefix: str | None = None,
    with_negative_factors: bool | None = None,
    region: str | None = None,
) -> int:
    query = _search_query(risk_levels, zsk_levels, okved_prefix, with_negative_factors, region)
    return session.scalar(select(func.count()).select_from(query.subquery())) or 0


def list_regions(session: Session) -> list[str]:
    rows = session.scalars(
        select(Contractor.region).where(Contractor.region.isnot(None)).distinct().order_by(Contractor.region)
    )
    return list(rows)
