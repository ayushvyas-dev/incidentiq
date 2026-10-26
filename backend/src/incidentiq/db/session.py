"""SQLAlchemy engine and session setup."""

import math
import os
from collections.abc import Iterator

from sqlalchemy import create_engine as sqlalchemy_create_engine
from sqlalchemy.engine import URL, Engine, make_url
from sqlalchemy.orm import Session, sessionmaker


def get_database_url(value: str | None = None) -> URL:
    """Read a database URL and ensure the psycopg 3 SQLAlchemy dialect is used."""
    value = value or os.getenv("DATABASE_URL")
    if not value:
        raise RuntimeError("DATABASE_URL is not configured")

    url = make_url(value)
    if url.drivername == "postgresql":
        url = url.set(drivername="postgresql+psycopg")
    if url.drivername != "postgresql+psycopg":
        raise ValueError("DATABASE_URL must use PostgreSQL with psycopg 3")
    return url


def create_engine(database_url: str | None = None) -> Engine:
    try:
        connect_timeout = int(os.getenv("DATABASE_CONNECT_TIMEOUT_SECONDS", "10"))
        pool_timeout = float(os.getenv("DATABASE_POOL_TIMEOUT_SECONDS", "10"))
    except ValueError as error:
        raise ValueError("Database timeouts must be numeric") from error
    if connect_timeout < 1 or not math.isfinite(pool_timeout) or pool_timeout <= 0:
        raise ValueError("Database timeouts must be positive")
    return sqlalchemy_create_engine(
        get_database_url(database_url),
        pool_pre_ping=True,
        pool_timeout=pool_timeout,
        connect_args={"connect_timeout": connect_timeout},
    )


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session(factory: sessionmaker[Session]) -> Iterator[Session]:
    with factory() as session:
        yield session
