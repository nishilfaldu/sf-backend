from collections.abc import Generator

from sqlalchemy import Table, create_engine, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def _engine_kwargs(database_url: str) -> dict:
    if not database_url.startswith("sqlite"):
        return {}

    kwargs: dict = {"connect_args": {"check_same_thread": False}}
    if ":memory:" in database_url or "mode=memory" in database_url:
        # A plain in-memory SQLite database lives and dies with its connection.
        # StaticPool keeps a single connection alive so every request — and every
        # thread FastAPI hands work to — sees the same data for the process's lifetime.
        kwargs["poolclass"] = StaticPool
    return kwargs


settings = get_settings()

engine = create_engine(
    settings.database_url,
    echo=settings.sql_echo,
    **_engine_kwargs(settings.database_url),
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
    if engine.dialect.name != "sqlite":
        return
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def init_db() -> None:
    """Create tables and upgrade existing ones. Safe to call repeatedly."""
    from app import models  # noqa: F401  (register models on Base.metadata)
    from app.models import Contact

    Base.metadata.create_all(bind=engine)
    # create_all will not ALTER a pre-existing `contacts` table. Add `photo`
    # from the mapped column so file-backed SQLite/Postgres from before this
    # field keep working.
    _add_missing_column(Contact.__table__, "photo")


def _add_missing_column(table: Table, column_name: str) -> None:
    inspector = inspect(engine)
    inspector.clear_cache()
    if table.name not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns(table.name)}
    if column_name in existing:
        return

    column = table.c[column_name]
    type_sql = column.type.compile(dialect=engine.dialect)
    if engine.dialect.name == "postgresql":
        ddl = text(
            f"ALTER TABLE {table.name} ADD COLUMN IF NOT EXISTS {column.name} {type_sql}"
        )
    else:
        ddl = text(f"ALTER TABLE {table.name} ADD COLUMN {column.name} {type_sql}")

    try:
        with engine.begin() as connection:
            connection.execute(ddl)
    except DBAPIError:
        inspector.clear_cache()
        existing = {column["name"] for column in inspector.get_columns(table.name)}
        if column_name not in existing:
            raise
    inspector.clear_cache()


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a session that is always closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
