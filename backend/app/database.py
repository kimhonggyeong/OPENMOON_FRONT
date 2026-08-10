from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings

settings = get_settings()
connect_args = {"check_same_thread": False} if settings.resolved_database_url.startswith("sqlite") else {}
engine = create_engine(
    settings.resolved_database_url,
    connect_args=connect_args,
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def init_db() -> None:
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=engine)

    # create_all does not add columns to an existing local database.
    columns = {column["name"] for column in inspect(engine).get_columns("mails")}
    if "starred" not in columns:
        boolean_type = "BOOLEAN" if engine.dialect.name != "sqlite" else "INTEGER"
        with engine.begin() as connection:
            connection.execute(
                text(f"ALTER TABLE mails ADD COLUMN starred {boolean_type} NOT NULL DEFAULT 0")
            )
