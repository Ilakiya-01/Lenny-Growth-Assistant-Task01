"""Database engine and session management."""

import logging
from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.errors import DatabaseNotConfiguredError

logger = logging.getLogger("lenny.db")


@lru_cache
def get_engine() -> Engine:
    """Return the process-wide SQLAlchemy engine."""
    settings = get_settings()
    if not settings.sqlalchemy_database_url:
        raise DatabaseNotConfiguredError(
            "DATABASE_URL is not set. Copy .env.example to .env in the repository root and configure it."
        )
    return create_engine(settings.sqlalchemy_database_url, pool_pre_ping=True, pool_recycle=1800)


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding one database session per request."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def check_connection() -> bool:
    """Return True when the configured database accepts a simple query."""
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # noqa: BLE001 - connectivity probe reports any failure as "unavailable"
        logger.warning("Database connection check failed: %s", exc)
        return False
