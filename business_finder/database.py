from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from business_finder.config import get_settings


class Base(DeclarativeBase):
    pass


def get_database_engine_config() -> tuple[str, dict[str, object]]:
    """Return SQLAlchemy URL and connect_args for local SQLite or Turso/libSQL."""
    settings = get_settings()

    if settings.turso_database_url:
        if not settings.turso_auth_token:
            raise ValueError("TURSO_AUTH_TOKEN is required when TURSO_DATABASE_URL is set.")
        return f"sqlite+{settings.turso_database_url}?secure=true", {"auth_token": settings.turso_auth_token}

    connect_args: dict[str, object] = {}
    if settings.database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    return settings.database_url, connect_args


def create_database_engine() -> Engine:
    database_url, connect_args = get_database_engine_config()
    return create_engine(database_url, connect_args=connect_args)


engine = create_database_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_session() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session
