from fastapi import APIRouter, HTTPException, status

from src.agent.profiles import profile_for
from src.core import factpack
from src.core import inn as inn_module
from src.db.client import repository as client_repository
from src.webapp.dependencies import CurrentUser, DbSession
from src.webapp.schemas import CompareRequest, CompareResponse, ProfileResponse

router = APIRouter(prefix="/api", tags=["operations"])


@router.get("/me", response_model=ProfileResponse)
def profile(session: DbSession, user: CurrentUser) -> ProfileResponse:
    quota = client_repository.get_quota(session, user.id)
    execution = profile_for(user.tariff)
    return ProfileResponse(
        login=user.login,
        display_name=user.display_name,
        tariff=user.tariff,
        tariff_label=execution.label,
        profile=execution.name,
        requests_used=quota.requests_used if quota else 0,
        requests_limit=execution.requests_limit,
        reports_generated=quota.reports_generated if quota else 0,
    )


@router.post("/compare", response_model=CompareResponse)
def compare(payload: CompareRequest, session: DbSession, user: CurrentUser) -> CompareResponse:
    execution = profile_for(user.tariff)
    quota = client_repository.get_quota(session, user.id)
    requests_used = quota.requests_used if quota else 0
    if requests_used >= execution.requests_limit:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Лимит проверок исчерпан: {requests_used} из {execution.requests_limit}.",
        )

    unique_inns = list(dict.fromkeys(payload.inns))
    invalid = {inn for inn in unique_inns if not inn_module.is_valid(inn)}
    valid = [inn for inn in unique_inns if inn not in invalid]
    if not valid:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": inn_module.FORMAT_HINT, "invalid": sorted(invalid)},
        )
    if len(valid) > execution.max_compare:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"На вашем тарифе можно сравнить до {execution.max_compare} контрагентов.",
        )

    packs = factpack.build_many(
        session,
        valid,
        role=payload.role_preset,
        mode=execution.factpack_mode,
    )
    found = {pack["inn"] for pack in packs}
    client_repository.record_request(session, user.id)
    return CompareResponse(
        items=packs,
        count=len(packs),
        missing=[inn for inn in valid if inn not in found],
        invalid=[inn for inn in unique_inns if inn in invalid],
    )
