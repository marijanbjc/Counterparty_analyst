from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import Analysis, Contractor, SessionAnalysis


def save(
    session: Session,
    session_id: UUID,
    inn: str,
    analysis_type: str,
    verdict: str,
    summary: str,
    report: dict,
    analysis: str,
) -> Analysis:
    item = session.scalar(
        select(Analysis).where(Analysis.inn == inn, Analysis.analysis_type == analysis_type)
    )
    if item is None:
        item = Analysis(inn=inn, analysis_type=analysis_type)
        session.add(item)
    item.verdict = verdict
    item.summary = summary
    item.report = report
    item.analysis = analysis
    session.flush()

    link = session.get(SessionAnalysis, (session_id, item.id))
    if link is None:
        session.add(SessionAnalysis(session_id=session_id, analysis_id=item.id))
    session.flush()
    return item


def get(session: Session, inn: str, analysis_type: str | None = None) -> Analysis | None:
    query = select(Analysis).where(Analysis.inn == inn)
    if analysis_type:
        query = query.where(Analysis.analysis_type == analysis_type)
    return session.scalar(query.order_by(Analysis.created_at.desc()).limit(1))


def list_for_session(session: Session, session_id: UUID) -> list[tuple[Analysis, Contractor]]:
    query = (
        select(Analysis, Contractor)
        .join(SessionAnalysis, SessionAnalysis.analysis_id == Analysis.id)
        .join(Contractor, Contractor.inn == Analysis.inn)
        .where(SessionAnalysis.session_id == session_id)
        .order_by(SessionAnalysis.created_at.desc())
    )
    return list(session.execute(query).tuples())


def last_for_session(session: Session, session_id: UUID) -> Analysis | None:
    query = (
        select(Analysis)
        .join(SessionAnalysis, SessionAnalysis.analysis_id == Analysis.id)
        .where(SessionAnalysis.session_id == session_id)
        .order_by(SessionAnalysis.created_at.desc())
        .limit(1)
    )
    return session.scalar(query)


def update_text(
    session: Session,
    item: Analysis,
    summary: str | None = None,
    analysis: str | None = None,
) -> Analysis:
    if summary is not None:
        item.summary = summary
    if analysis is not None:
        item.analysis = analysis
    session.flush()
    session.refresh(item)
    return item
