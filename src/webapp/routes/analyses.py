import json
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response, status

from src.core import report as report_builder
from src.db.analyses import repository as analyses_repository
from src.db.client import repository as client_repository
from src.db.models import Analysis
from src.webapp.dependencies import CurrentUser, DbSession
from src.webapp.schemas import AnalysisSummaryResponse, ReportUpdateRequest

router = APIRouter(prefix="/api", tags=["analyses"])


def _owned_last_analysis(
    session: DbSession,
    session_id: UUID,
    user: CurrentUser,
) -> Analysis:
    if client_repository.get_session(session, session_id, user_id=user.id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Сессия не найдена.")
    item = analyses_repository.last_for_session(session, session_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="В сессии ещё нет отчётов.")
    return item


def _payload(item: Analysis) -> dict:
    report = item.report or {}
    return {
        "inn": item.inn,
        "short_name": report.get("short_name"),
        "as_of": report.get("as_of"),
        "analysis_type": item.analysis_type,
        "verdict": item.verdict,
        "summary": item.summary,
        "analysis": item.analysis,
        "report": item.report,
        "created_at": item.created_at,
    }


@router.get("/sessions/{session_id}/analyses", response_model=list[AnalysisSummaryResponse])
def list_session_analyses(
    session_id: UUID,
    session: DbSession,
    user: CurrentUser,
) -> list[AnalysisSummaryResponse]:
    if client_repository.get_session(session, session_id, user_id=user.id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Сессия не найдена.")
    return [
        AnalysisSummaryResponse(
            inn=item.inn,
            short_name=contractor.short_name,
            analysis_type=item.analysis_type,
            verdict=item.verdict,
            summary=item.summary,
            created_at=item.created_at,
        )
        for item, contractor in analyses_repository.list_for_session(session, session_id)
    ]


@router.get("/sessions/{session_id}/report")
def get_session_report(session_id: UUID, session: DbSession, user: CurrentUser) -> dict:
    return _payload(_owned_last_analysis(session, session_id, user))


@router.put("/sessions/{session_id}/report")
def update_session_report(
    session_id: UUID,
    payload: ReportUpdateRequest,
    session: DbSession,
    user: CurrentUser,
) -> dict:
    item = _owned_last_analysis(session, session_id, user)
    return _payload(
        analyses_repository.update_text(
            session,
            item,
            summary=payload.summary,
            analysis=payload.analysis,
        )
    )


@router.get("/sessions/{session_id}/report/export")
def export_session_report(
    session_id: UUID,
    session: DbSession,
    user: CurrentUser,
    format: str = Query(pattern="^(json|md)$"),
) -> Response:
    item = _owned_last_analysis(session, session_id, user)
    payload = _payload(item)
    if format == "json":
        body = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
        media_type, extension = "application/json", "json"
    else:
        body = report_builder.to_markdown(payload)
        media_type, extension = "text/markdown", "md"
    name = "-".join(filter(None, ["report", item.inn, payload["as_of"]]))
    return Response(
        body,
        media_type=f"{media_type}; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}.{extension}"'},
    )


@router.get("/analyses/{inn}")
def get_analysis(
    inn: str,
    session: DbSession,
    user: CurrentUser,
    analysis_type: str | None = None,
) -> dict:
    item = analyses_repository.get(session, inn, analysis_type)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Сохранённый анализ не найден.")
    return _payload(item)
