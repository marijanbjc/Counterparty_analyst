from fastapi import APIRouter, HTTPException, status

from src.core import factpack
from src.core import inn as inn_module
from src.webapp.dependencies import CurrentUser, DbSession
from src.webapp.schemas import RolePreset

router = APIRouter(prefix="/api/contractors", tags=["contractors"])


@router.get("/{inn}")
def get_contractor(inn: str, session: DbSession, user: CurrentUser, role: RolePreset | None = None) -> dict:
    if not inn_module.is_valid(inn):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=inn_module.FORMAT_HINT)

    pack = factpack.build(session, inn, mode=factpack.FULL, role=role)
    if pack is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Контрагента с таким ИНН в базе нет.")
    return pack
