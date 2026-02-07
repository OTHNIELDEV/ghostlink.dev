from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from app.core.config import settings
from app.db.engine import init_db
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing Database...")
    await init_db()
    yield
    logger.info("Shutting down...")

from starlette.middleware.sessions import SessionMiddleware
from app.routers import (
    pages, sites, bridge, auth, users, dashboard,
    billing, organizations, webhooks, api_keys, optimizations, approvals, audit_logs,
    answer_capture, attribution, knowledge_graph, compliance, edge
)

app = FastAPI(title=settings.PROJECT_NAME, lifespan=lifespan)

app.add_middleware(SessionMiddleware, secret_key=settings.SECRET_KEY)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(
    TrustedHostMiddleware, 
    allowed_hosts=["*"]
)

app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(pages.router)
app.include_router(sites.router, prefix="/api")
# Compatibility alias: expose direct /sites endpoints as well.
app.include_router(sites.router)
app.include_router(dashboard.router, prefix="/api")
app.include_router(bridge.router, prefix="/api")
app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(users.router, prefix="/users", tags=["users"])
app.include_router(billing.router, prefix="/billing")
app.include_router(organizations.router, prefix="/api/organizations")
app.include_router(api_keys.router, prefix="/api/api-keys")
app.include_router(webhooks.router, prefix="/webhooks")
app.include_router(optimizations.router, prefix=settings.API_V1_STR)
app.include_router(approvals.router, prefix=settings.API_V1_STR)
app.include_router(audit_logs.router, prefix=settings.API_V1_STR)
app.include_router(answer_capture.router, prefix=settings.API_V1_STR)
app.include_router(attribution.router, prefix=settings.API_V1_STR)
app.include_router(knowledge_graph.router, prefix=settings.API_V1_STR)
app.include_router(compliance.router, prefix=settings.API_V1_STR)
app.include_router(edge.router, prefix=settings.API_V1_STR)
