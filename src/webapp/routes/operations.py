from fastapi import APIRouter, HTTPException, status

from src.core import factpack
from src.core import inn as inn_module
from src.db.client import repository as client_repository
from src.webapp.dependencies import CurrentUser, DbSession
from src.webapp.schemas import CompareRequest, ProfileResponse

router = APIRouter(prefix="/api", tags=["operations"])


@router.get("/me", response_model=ProfileResponse)
def profile(session: DbSession, user: CurrentUser) -> ProfileResponse:
    quota = client_repository.get_quota(session, user.id)
    return ProfileResponse(
        login=user.login,
        display_name=user.display_name,
        tariff="Демо",
        requests_used=quota.requests_used if quota else 0,
        requests_limit=quota.requests_limit if quota else 100,
        reports_generated=quota.reports_generated if quota else 0,
    )


@router.post("/compare")
def compare(payload: CompareRequest, session: DbSession, user: CurrentUser) -> dict:
    unique_inns = list(dict.fromkeys(payload.inns))
    invalid = [inn for inn in unique_inns if not inn_module.is_valid(inn)]
    if invalid:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": inn_module.FORMAT_HINT, "invalid": invalid},
        )

    packs = factpack.build_many(session, unique_inns, role=payload.role_preset)
    found = {pack["inn"] for pack in packs}
    missing = [inn for inn in unique_inns if inn not in found]
    if missing:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={"message": "Часть контрагентов отсутствует в базе.", "missing": missing},
        )

    client_repository.record_request(session, user.id)
    return {"items": packs, "count": len(packs)}
