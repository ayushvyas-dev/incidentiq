import json
from uuid import UUID

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from incidentiq.ingestion.chunking import chunk_text
from incidentiq.ingestion.parsers import (
    InvalidDocument,
    extract_text,
)
from incidentiq.models import Base, Document, DocumentChunk, Job
from incidentiq.services.jobs import run_document_job
from incidentiq.services.vector_index import PineconeVectorStore
from tests.auth_support import authorized_client, create_test_app


class FakeQueue:
    def __init__(self):
        self.jobs = []

    async def enqueue_job(self, function, *args, **kwargs):
        self.jobs.append((function, args, kwargs))
        return object()


@pytest.mark.parametrize(
    ("text", "size", "overlap", "expected"),
    [
        ("abcdefghij", 6, 2, ["abcdef", "efghij"]),
        ("short", 8, 2, ["short"]),
        ("   ", 8, 2, []),
    ],
)
def test_chunk_text(text, size, overlap, expected):
    assert chunk_text(text, size, overlap) == expected


def test_chunk_text_rejects_invalid_size():
    with pytest.raises(ValueError):
        chunk_text("text", 4, 4)


def test_pinecone_delete_batches_ids_at_api_limit():
    class FakeIndex:
        def __init__(self):
            self.deleted = []

        def delete(self, ids, namespace):
            self.deleted.append((ids, namespace))

    store = PineconeVectorStore.__new__(PineconeVectorStore)
    store._index = FakeIndex()
    store.delete([str(index) for index in range(2001)], "test")
    assert [len(ids) for ids, _ in store.index.deleted] == [1000, 1000, 1]


def test_text_and_jsonl_parsing():
    assert extract_text("guide.md", "text/markdown", b"\xef\xbb\xbfGuide") == "Guide"
    assert (
        extract_text("events.jsonl", "application/x-ndjson", b'{"b":2,"a":1}\n')
        == '{"a":1,"b":2}'
    )
    with pytest.raises(InvalidDocument, match="line 1"):
        extract_text("events.jsonl", "application/json", b"not-json\n")


def test_pdf_extraction():
    import pymupdf

    source = pymupdf.open()
    page = source.new_page()
    page.insert_text((72, 72), "Runbook text")
    data = source.tobytes()
    source.close()
    assert "Runbook text" in extract_text("guide.pdf", "application/pdf", data)


def test_upload_duplicate_list_detail_delete_and_vector_safety():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)

    class FakeEmbedder:
        def embed(self, texts):
            return [[0.1] * 1536 for _ in texts]

    class FakeVectorStore:
        def __init__(self):
            self.upserts = []
            self.deletes = []
            self.fail_delete = False

        def upsert(self, vectors, namespace):
            self.upserts.append((vectors, namespace))

        def delete(self, ids, namespace):
            if self.fail_delete:
                raise RuntimeError("provider details must not escape")
            self.deletes.append((ids, namespace))

    vectors = FakeVectorStore()
    queue = FakeQueue()
    client = authorized_client(
        create_test_app(factory, FakeEmbedder(), vectors, job_queue=queue)
    )

    data = {
        "source_type": "runbook",
        "service": "checkout",
        "metadata": json.dumps({"team": "platform"}),
    }
    files = {"file": ("../../runbook.md", b"Pool checks", "text/markdown")}
    first = client.post("/api/v1/documents", data=data, files=files)
    assert first.status_code == 202
    first_document = first.json()
    assert first_document["filename"] == "runbook.md"
    assert first_document["status"] == "queued"
    assert len(queue.jobs) == 1
    assert queue.jobs[0][0] == "process_document_job"
    assert (
        client.get(f"/api/v1/jobs/{first_document['job_id']}").json()["status"]
        == "queued"
    )
    assert vectors.upserts == []

    result = run_document_job(
        factory,
        UUID(first_document["document_id"]),
        UUID(first_document["job_id"]),
        FakeEmbedder(),
        vectors,
        "incidentiq",
        1536,
        sleeper=lambda _: None,
    )
    assert result == {"status": "completed", "attempts": 1}
    assert (
        client.get(f"/api/v1/jobs/{first_document['job_id']}").json()["status"]
        == "completed"
    )
    stored_vector = vectors.upserts[0][0][0]
    assert stored_vector["id"] == stored_vector["metadata"]["chunk_id"]
    assert stored_vector["metadata"]["service"] == "checkout"
    rerun = run_document_job(
        factory,
        UUID(first_document["document_id"]),
        UUID(first_document["job_id"]),
        FakeEmbedder(),
        vectors,
        "incidentiq",
        1536,
        sleeper=lambda _: None,
    )
    assert rerun == {"status": "completed"}
    assert len(vectors.upserts) == 1

    duplicate = client.post("/api/v1/documents", data=data, files=files)
    assert duplicate.status_code == 200
    assert duplicate.json()["duplicate"] is True

    document_id = first_document["document_id"]
    assert (
        client.get("/api/v1/documents/" + document_id).json()["service"] == "checkout"
    )
    assert (
        client.get("/api/v1/documents").json()["items"][0]["document_id"] == document_id
    )
    with factory() as session:
        stored = session.get(Document, UUID(document_id))
        assert stored is not None
        assert stored.document_metadata == {"team": "platform"}
        assert stored.chunks[0].chunk_metadata["source_name"] == "runbook.md"
    assert (
        client.delete(
            "/api/v1/documents/" + document_id,
            headers={"Authorization": "Bearer invalid"},
        ).status_code
        == 401
    )
    assert client.delete("/api/v1/documents/" + document_id).json()["deleted"]
    assert client.delete("/api/v1/documents/" + document_id).json()["deleted"]

    with factory() as session:
        document = Document(
            filename="stored", source_type="other", content_sha256="b" * 64
        )
        document.chunks.append(
            DocumentChunk(chunk_index=0, content="vector", pinecone_vector_id="vec-1")
        )
        session.add(document)
        session.commit()
        vector_document_id = document.id
    deleted = client.delete(f"/api/v1/documents/{vector_document_id}")
    assert deleted.status_code == 200
    assert vectors.deletes[-1] == (["vec-1"], "incidentiq-test")

    with factory() as session:
        document = Document(
            filename="failed-delete", source_type="other", content_sha256="c" * 64
        )
        document.chunks.append(
            DocumentChunk(chunk_index=0, content="keep", pinecone_vector_id="vec-2")
        )
        session.add(document)
        session.commit()
        retained_document_id = document.id
    vectors.fail_delete = True
    failed_delete = client.delete(f"/api/v1/documents/{retained_document_id}")
    assert failed_delete.status_code == 502
    with factory() as session:
        assert session.get(Document, retained_document_id) is not None
    client.close()
    engine.dispose()


def test_terminal_worker_failure_is_safe_and_same_upload_can_be_requeued():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    queue = FakeQueue()
    client = authorized_client(create_test_app(factory, job_queue=queue))
    data = {"source_type": "runbook"}
    files = {"file": ("failure.md", b"retry me", "text/markdown")}
    accepted = client.post("/api/v1/documents", data=data, files=files)
    body = accepted.json()

    def fail(*args):
        raise RuntimeError("private provider response")

    result = run_document_job(
        factory,
        UUID(body["document_id"]),
        UUID(body["job_id"]),
        object(),
        object(),
        "test",
        1,
        max_attempts=2,
        indexer=fail,
        sleeper=lambda _: None,
    )
    assert result == {
        "status": "failed",
        "error_code": "INDEXING_FAILED",
        "attempts": 2,
    }
    status = client.get(f"/api/v1/jobs/{body['job_id']}")
    assert status.json()["status"] == "failed"
    assert status.json()["error"] == {"code": "INDEXING_FAILED"}
    assert "private provider response" not in status.text

    retry = client.post("/api/v1/documents", data=data, files=files)
    assert retry.status_code == 202
    assert retry.json()["job_id"] != body["job_id"]
    assert len(queue.jobs) == 2
    client.close()
    engine.dispose()


def test_background_index_retry_keeps_stable_ids_and_duplicate_upload_is_idempotent(
    monkeypatch,
):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)

    class FakeEmbedder:
        def embed(self, texts):
            return [[0.1] * 3 for _ in texts]

    class FlakyVectorStore:
        def __init__(self):
            self.ids = []
            self.fail = True

        def upsert(self, vectors, namespace):
            self.ids.extend(vector["id"] for vector in vectors)
            if self.fail:
                self.fail = False
                raise RuntimeError("provider details must not escape")

        def delete(self, ids, namespace):
            pass

    vectors = FlakyVectorStore()
    monkeypatch.setenv("EMBEDDING_DIMENSION", "3")
    queue = FakeQueue()
    client = authorized_client(
        create_test_app(factory, FakeEmbedder(), vectors, job_queue=queue)
    )
    data = {"source_type": "runbook"}
    files = {"file": ("retry.md", b"Retry indexing", "text/markdown")}

    accepted = client.post("/api/v1/documents", data=data, files=files)
    assert accepted.status_code == 202
    body = accepted.json()
    with factory() as session:
        document = session.query(Document).one()
        chunk_id = document.chunks[0].pinecone_vector_id
        assert document.status == "queued"

    result = run_document_job(
        factory,
        UUID(body["document_id"]),
        UUID(body["job_id"]),
        FakeEmbedder(),
        vectors,
        "incidentiq",
        3,
        sleeper=lambda _: None,
    )
    assert result == {"status": "completed", "attempts": 2}
    assert vectors.ids == [chunk_id, chunk_id]
    with factory() as session:
        assert session.query(Job).one().status == "completed"
        assert session.query(Document).one().status == "completed"
    duplicate = client.post("/api/v1/documents", data=data, files=files)
    assert duplicate.status_code == 200
    assert duplicate.json()["duplicate"] is True
    assert len(queue.jobs) == 1
    client.close()
    engine.dispose()


@pytest.mark.parametrize(
    ("filename", "content_type", "body", "status"),
    [
        ("bad.exe", "application/octet-stream", b"no", 415),
        ("bad.pdf", "text/plain", b"not pdf", 415),
        ("bad.txt", "text/plain", b"\xff", 422),
    ],
)
def test_upload_rejects_bad_type_or_encoding(filename, content_type, body, status):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    client = authorized_client(
        create_test_app(sessionmaker(engine, expire_on_commit=False))
    )
    response = client.post(
        "/api/v1/documents",
        data={"source_type": "other"},
        files={"file": (filename, body, content_type)},
    )
    assert response.status_code == status
    client.close()
    engine.dispose()


def test_upload_enforces_size_limit(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    client = authorized_client(
        create_test_app(sessionmaker(engine, expire_on_commit=False))
    )
    monkeypatch.setenv("MAX_UPLOAD_MB", "1")
    response = client.post(
        "/api/v1/documents",
        data={"source_type": "other"},
        files={"file": ("large.txt", b"x" * (1024 * 1024 + 1), "text/plain")},
    )
    assert response.status_code == 413
    client.close()
    engine.dispose()
