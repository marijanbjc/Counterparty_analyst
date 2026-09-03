from src.webapp.routes.analyses import router as analyses_router
from src.webapp.routes.auth import router as auth_router
from src.webapp.routes.chat import router as chat_router
from src.webapp.routes.contractors import router as contractors_router
from src.webapp.routes.health import router as health_router
from src.webapp.routes.operations import router as operations_router
from src.webapp.routes.sessions import router as sessions_router

ROUTERS = (
    auth_router,
    sessions_router,
    chat_router,
    contractors_router,
    analyses_router,
    operations_router,
    health_router,
)
