from fastapi import APIRouter
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from src.db.engine import get_engine
from src.webapp.schemas import HealthResponse

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    try:
        with get_engine().connect() as connection:
            connection.execute(text("select 1"))
    except SQLAlchemyError as error:
        return HealthResponse(status="degraded", database=False, detail=type(error).__name__)
    return HealthResponse(status="ok", database=True)
