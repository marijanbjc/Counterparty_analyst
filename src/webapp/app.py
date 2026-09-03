from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from src.config.settings import get_settings
from src.webapp.routes import ROUTERS


def _database_unavailable(request: Request, exc: SQLAlchemyError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": "База данных недоступна, повторите запрос позже."},
    )


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="ИИ-агент проверки контрагентов", debug=settings.app_debug)
    app.add_exception_handler(SQLAlchemyError, _database_unavailable)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    for router in ROUTERS:
        app.include_router(router)
    return app
