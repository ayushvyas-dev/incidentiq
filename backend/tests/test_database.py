from uuid import UUID

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from incidentiq.db import session as database_session
from incidentiq.db.repositories import Repository
from incidentiq.db.session import get_database_url
from incidentiq.models import Base, Document, DocumentChunk


@pytest.fixture
def session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as value:
        yield value
    engine.dispose()


def test_document_and_chunk_persist_and_round_trip(session):
    documents = Repository(session, Document)
    document = documents.add(
        filename="runbook.md",
        source_type="runbook",
        content_sha256="a" * 64,
        document_metadata={"team": "platform"},
    )
    chunk = Repository(session, DocumentChunk).add(
        document_id=document.id,
        chunk_index=0,
        content="Check the connection pool.",
    )
    session.commit()

    loaded = documents.get(document.id)
    assert loaded is not None
    assert isinstance(loaded.id, UUID)
    assert loaded.document_metadata == {"team": "platform"}
    assert loaded.chunks[0].id == chunk.id


def test_database_url_selects_psycopg_and_rejects_other_drivers():
    url = get_database_url("postgresql://user:secret@localhost/db")
    assert url.drivername == "postgresql+psycopg"
    assert url.password == "secret"

    with pytest.raises(ValueError, match="PostgreSQL with psycopg 3"):
        get_database_url("sqlite:///local.db")


def test_engine_configures_bounded_connection_and_pool_timeouts(monkeypatch):
    captured = {}
    monkeypatch.setenv("DATABASE_CONNECT_TIMEOUT_SECONDS", "7")
    monkeypatch.setenv("DATABASE_POOL_TIMEOUT_SECONDS", "3.5")
    monkeypatch.setattr(
        database_session, "sqlalchemy_create_engine",
        lambda url, **kwargs: captured.update(url=url, **kwargs) or object(),
    )

    database_session.create_engine("postgresql://user:password@localhost/db")

    assert captured["connect_args"] == {"connect_timeout": 7}
    assert captured["pool_timeout"] == 3.5
