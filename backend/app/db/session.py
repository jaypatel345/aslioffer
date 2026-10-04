from typing import Generator
from sqlalchemy import inspect, text
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
    _add_missing_columns()
    logger.info("Database tables initialized successfully.")


# Columns added after a table first shipped. create_all() creates missing tables
# but never alters existing ones, so a database from an older checkout would
# fail on the first query. Additive, nullable columns only.
_ADDED_COLUMNS = {
    "offers": {"access_token_hash": "VARCHAR"},
}


def _add_missing_columns() -> None:
    inspector = inspect(engine)
    for table, columns in _ADDED_COLUMNS.items():
        if not inspector.has_table(table):
            continue
        existing = {col["name"] for col in inspector.get_columns(table)}
        for name, ddl_type in columns.items():
            if name not in existing:
                with engine.begin() as conn:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl_type}"))
                logger.info("Added column %s.%s", table, name)


# Ensure tables exist immediately upon engine startup (especially for SQLite zero-config mode)
try:
    init_db()
except Exception as _e:
    logger.warning("Auto init_db deferred: %s", str(_e))


def get_session() -> Generator[Session, None, None]:
    """Dependency for obtaining a database session."""
    with Session(engine) as session:
        yield session
