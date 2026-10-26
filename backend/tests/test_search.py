from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from incidentiq.models import Base, Document, DocumentChunk
from tests.auth_support import authorized_client, create_test_app


class FakeEmbedder:
    def embed(self, texts):
        return [[0.25, 0.5, 0.75] for _ in texts]


class FakeVectorStore:
    def __init__(self, matches=()):
        self.matches = list(matches)
        self.filters = []
        self.error = None

    def upsert(self, vectors, namespace):
        pass

    def delete(self, ids, namespace):
        pass

    def query(self, vector, top_k, namespace, filters):
        self.filters.append(filters)
        if self.error:
            raise RuntimeError("upstream secret details")
        return self.matches[:top_k]


@pytest.fixture
def search_app(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    vectors = FakeVectorStore()
    monkeypatch.setenv("EMBEDDING_DIMENSION", "3")
    client = authorized_client(create_test_app(factory, FakeEmbedder(), vectors))
    with factory() as session:
        documents = []
        chunks = {}
        for index, (name, service, source_type, content) in enumerate(
            [
                ("a.md", "checkout", "runbook", "pool timeout after deployment"),
                ("b.md", "checkout", "postmortem", "deployment overloaded the connection pool"),
                ("c.md", "catalog", "runbook", "catalog cache miss"),
            ]
        ):
            document = Document(
                filename=name,
                source_type=source_type,
                service=service,
                environment="production",
                content_sha256=str(index) * 64,
                status="completed",
                created_at=datetime(2026, 10, 1, tzinfo=UTC),
            )
            chunk_id = uuid4()
            document.chunks.append(
                DocumentChunk(
                    id=chunk_id,
                    chunk_index=0,
                    content=content,
                    pinecone_vector_id=str(chunk_id),
                    chunk_metadata={},
                )
            )
            session.add(document)
            documents.append(document)
            chunks[name] = chunk_id
        session.commit()
        incomplete = Document(
            filename="failed.md",
            source_type="runbook",
            service="checkout",
            environment="production",
            content_sha256="f" * 64,
            status="failed",
        )
        failed_chunk_id = uuid4()
        incomplete.chunks.append(
            DocumentChunk(
                id=failed_chunk_id,
                chunk_index=0,
                content="connection pool failed indexing",
                pinecone_vector_id=str(failed_chunk_id),
                chunk_metadata={},
            )
        )
        session.add(incomplete)
        session.commit()
        chunks["failed.md"] = failed_chunk_id
    yield client, vectors, chunks
    client.close()
    engine.dispose()


def test_semantic_search_returns_only_canonical_chunks_and_applies_filters(search_app):
    client, vectors, chunks = search_app
    vectors.matches = [
        (str(chunks["a.md"]), 0.92),
        (str(chunks["failed.md"]), 0.91),
        (str(uuid4()), 0.81),
    ]
    response = client.post(
        "/api/v1/search",
        json={
            "query": "connection pool timeout",
            "use_hybrid_search": False,
            "top_k": 5,
            "filters": {
                "service": "checkout",
                "source_types": ["runbook"],
                "created_after": "2026-10-01T00:00:00Z",
            },
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert [result["source"] for result in body["results"]] == ["a.md"]
    assert body["results"][0]["chunk_id"] == str(chunks["a.md"])
    assert body["results"][0]["excerpt"] == "pool timeout after deployment"
    assert vectors.filters == [
        {
            "service": {"$eq": "checkout"},
            "source_type": {"$in": ["runbook"]},
        }
    ]


def test_keyword_search_and_hybrid_rrf(search_app):
    client, vectors, chunks = search_app
    keyword = client.post(
        "/api/v1/search", json={"query": "connection pool", "mode": "keyword", "top_k": 3}
    )
    assert keyword.status_code == 200
    assert {result["source"] for result in keyword.json()["results"]} == {"a.md", "b.md"}
    assert keyword.json()["retrieval"]["mode"] == "keyword"

    vectors.matches = [(str(chunks["a.md"]), 0.9), (str(chunks["b.md"]), 0.8)]
    hybrid = client.post("/api/v1/search", json={"query": "overloaded", "top_k": 3})
    assert hybrid.status_code == 200
    assert hybrid.json()["results"][0]["source"] == "b.md"
    assert hybrid.json()["retrieval"]["candidate_count"] == 2


def test_empty_results_and_request_validation(search_app):
    client, _, _ = search_app
    empty = client.post("/api/v1/search", json={"query": "not present", "mode": "keyword"})
    assert empty.status_code == 200
    assert empty.json()["results"] == []
    assert client.post("/api/v1/search", json={"query": "x", "top_k": 0}).status_code == 422
    assert client.post("/api/v1/search", json={"query": "   ", "mode": "keyword"}).status_code == 422


def test_date_filter_requires_timezone_and_order(search_app):
    client, _, _ = search_app
    naive = client.post(
        "/api/v1/search",
        json={"query": "pool", "mode": "keyword", "filters": {"created_after": "2026-10-01T00:00:00"}},
    )
    reversed_range = client.post(
        "/api/v1/search",
        json={
            "query": "pool",
            "mode": "keyword",
            "filters": {
                "created_after": "2026-10-02T00:00:00Z",
                "created_before": "2026-10-01T00:00:00Z",
            },
        },
    )
    assert naive.status_code == 422
    assert reversed_range.status_code == 422

    client, vectors, chunks = search_app
    vectors.matches = [(str(chunks["a.md"]), 0.9)]
    outside = client.post(
        "/api/v1/search",
        json={
            "query": "pool",
            "mode": "semantic",
            "filters": {"created_after": "2026-10-02T00:00:00Z"},
        },
    )
    assert outside.status_code == 200
    assert outside.json()["results"] == []


def test_provider_failure_is_sanitized(search_app):
    client, vectors, _ = search_app
    vectors.error = True
    response = client.post("/api/v1/search", json={"query": "pool", "mode": "semantic"})
    assert response.status_code == 502
    assert "secret" not in response.text


def test_keyword_search_does_not_require_external_providers(search_app):
    client, _, _ = search_app
    client.app.state.embedding_provider = None
    client.app.state.vector_store = None
    keyword = client.post("/api/v1/search", json={"query": "pool", "mode": "keyword"})
    semantic = client.post("/api/v1/search", json={"query": "pool", "mode": "semantic"})
    assert keyword.status_code == 200
    assert semantic.status_code == 503
