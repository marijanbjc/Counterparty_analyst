from src.webapp.routes.auth import router as auth_router
from src.webapp.routes.contractors import router as contractors_router
from src.webapp.routes.health import router as health_router
from src.webapp.routes.sessions import router as sessions_router

ROUTERS = (auth_router, sessions_router, contractors_router, health_router)
