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
    _migrate_legacy_contact_addresses()


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


_LEGACY_ADDRESS_COLUMNS = ("address", "city", "state", "postal_code", "country")


def _migrate_legacy_contact_addresses() -> None:
    """Copy a pre-existing single address off `contacts` into `addresses`.

    `create_all` adds the new table but leaves leftover columns on an older
    `contacts` table. One `home` row per contact that had any postal field set.
    Contacts that already have address rows are left alone.
    """
    inspector = inspect(engine)
    inspector.clear_cache()
    tables = inspector.get_table_names()
    if "contacts" not in tables or "addresses" not in tables:
        return
    contact_cols = {column["name"] for column in inspector.get_columns("contacts")}
    if not all(column in contact_cols for column in _LEGACY_ADDRESS_COLUMNS):
        return

    with engine.begin() as connection:
        already_moved = {
            row[0]
            for row in connection.execute(text("SELECT DISTINCT contact_id FROM addresses"))
        }
        rows = connection.execute(
            text("SELECT id, address, city, state, postal_code, country FROM contacts")
        ).mappings()
        for row in rows:
            if row["id"] in already_moved:
                continue
            if not any(row[column] for column in _LEGACY_ADDRESS_COLUMNS):
                continue
            connection.execute(
                text(
                    """
                    INSERT INTO addresses
                        (contact_id, type, address, city, state, postal_code, country)
                    VALUES
                        (:contact_id, 'home', :address, :city, :state, :postal_code, :country)
                    """
                ),
                {
                    "contact_id": row["id"],
                    "address": row["address"],
                    "city": row["city"],
                    "state": row["state"],
                    "postal_code": row["postal_code"],
                    "country": row["country"],
                },
            )


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a session that is always closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
