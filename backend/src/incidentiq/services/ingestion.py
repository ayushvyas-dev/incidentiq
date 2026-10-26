"""Persist one validated document and its canonical text chunks."""

from hashlib import sha256
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from incidentiq.ingestion.chunking import chunk_text
from incidentiq.models import Document, DocumentChunk


def ingest_document(
    session: Session,
    *,
    filename: str,
    raw_content: bytes,
    text: str,
    source_type: str,
    service: str | None,
    environment: str | None,
    metadata: dict[str, Any],
    chunk_size: int,
    chunk_overlap: int,
) -> tuple[Document, bool]:
    content_sha256 = sha256(raw_content).hexdigest()
    existing = session.scalar(select(Document).where(Document.content_sha256 == content_sha256))
    if existing is not None:
        return existing, True

    chunks = chunk_text(text, chunk_size, chunk_overlap)
    document = Document(
        filename=filename,
        source_type=source_type,
        service=service,
        environment=environment,
        content_sha256=content_sha256,
        status="processing",
        document_metadata=metadata,
    )
    session.add(document)
    try:
        session.flush()
        document.chunks = []
        for index, chunk in enumerate(chunks):
            chunk_id = uuid4()
            document.chunks.append(
                DocumentChunk(
                    id=chunk_id,
                    chunk_index=index,
                    content=chunk,
                    pinecone_vector_id=str(chunk_id),
                    chunk_metadata={
                        "document_id": str(document.id),
                        "source_name": filename,
                        "source_type": source_type,
                        "service": service,
                        "environment": environment,
                        "chunk_index": index,
                    },
                )
            )
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.scalar(select(Document).where(Document.content_sha256 == content_sha256))
        if existing is None:
            raise
        return existing, True
    return document, False
