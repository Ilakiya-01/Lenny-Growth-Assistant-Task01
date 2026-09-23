"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import chat, dev_agent, health, sessions
from app.config import get_settings
from app.db.database import check_connection
from app.errors import register_exception_handlers

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("lenny.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    if not settings.database_url:
        logger.warning("DATABASE_URL is not configured: session endpoints will respond with 503.")
    elif check_connection():
        logger.info("Database connection verified.")
    else:
        logger.warning("Database connection failed: session endpoints will respond with 503.")
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(sessions.router)
    # The production chat workflow. Unlike the development routes below, this is
    # registered in every environment: it is what the frontend calls.
    app.include_router(chat.router)
    if settings.dev_agent_endpoints_enabled:
        # Phase 3 verification path (router -> LLM factory -> provider), kept
        # beside the production chat workflow for isolated agent inspection.
        app.include_router(dev_agent.router)
    else:
        logger.info("Development agent endpoints are disabled because APP_ENV=production.")
    register_exception_handlers(app)

    return app


app = create_app()
