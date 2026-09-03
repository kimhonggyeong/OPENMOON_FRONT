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


def _ensure_columns(table_name: str, definitions: dict[str, str]) -> None:
    # Add missing columns without deleting or recreating the existing local database.
    columns = {
        column["name"]
        for column in inspect(engine).get_columns(table_name)
    }
    missing = [
        (column_name, ddl)
        for column_name, ddl in definitions.items()
        if column_name not in columns
    ]
    if not missing:
        return

    with engine.begin() as connection:
        for column_name, ddl in missing:
            connection.execute(
                text(
                    f"ALTER TABLE {table_name} "
                    f"ADD COLUMN {column_name} {ddl}"
                )
            )


def init_db() -> None:
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _ensure_columns("quotation_drafts", {"email_recipients": "JSON"})

    # Phase 5: 메일 soft-delete.
    # 기존 DB에는 create_all만으로 컬럼이 추가되지 않으므로 명시적으로 보정한다.
    mail_columns = {
        column["name"]
        for column in inspect(engine).get_columns("mails")
    }

    if "deleted_at" not in mail_columns:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "ALTER TABLE mails "
                    "ADD COLUMN deleted_at DATETIME"
                )
            )

    # create_all does not add columns to an existing local database.
    boolean_type = "BOOLEAN" if engine.dialect.name != "sqlite" else "INTEGER"

    _ensure_columns(
        "mails",
        {
            "starred": f"{boolean_type} NOT NULL DEFAULT 0",
        },
    )
    _ensure_columns(
        "mail_items",
        {
            # SQLite stores SQLAlchemy JSON values as JSON text and decodes
            # them back to Python dictionaries through the JSON type.
            "spec_attributes": "JSON NOT NULL DEFAULT '{}'",
            "cost_price": "INTEGER",
        },
    )
    _ensure_columns(
        "quotation_draft_items",
        {
            "spec_attributes": "JSON NOT NULL DEFAULT '{}'",
            "cost_price": "INTEGER",
        },
    )
