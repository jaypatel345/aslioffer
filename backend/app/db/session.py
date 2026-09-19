from typing import Generator
from sqlmodel import SQLModel, create_engine, Session
from app.core.config import settings
from app.core.logging import logger

connect_args = {}
if settings.DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(
    settings.DATABASE_URL,
    echo=False,
    connect_args=connect_args,
)


def init_db() -> None:
    """Initialize database tables."""
    from app.db import models  # noqa: F401

    logger.info("Initializing database tables...")
    SQLModel.metadata.create_all(engine)
    logger.info("Database tables initialized successfully.")


# Ensure tables exist immediately upon engine startup (especially for SQLite zero-config mode)
try:
    init_db()
except Exception as _e:
    logger.warning("Auto init_db deferred: %s", str(_e))


def get_session() -> Generator[Session, None, None]:
    """Dependency for obtaining a database session."""
    with Session(engine) as session:
        yield session
