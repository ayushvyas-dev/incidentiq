"""Index canonical NeonDB chunks into Pinecone with replay-safe IDs."""

import math

from sqlalchemy.orm import Session

from incidentiq.models import Document
from incidentiq.services.vector_index import EmbeddingProvider, VectorStore

BATCH_SIZE = 64


def index_document(
    session: Session,
    document: Document,
    embedder: EmbeddingProvider,
    vector_store: VectorStore,
    namespace: str,
    dimension: int,
) -> None:
    if document.status == "completed":
        return
    document.status = "processing"
    session.commit()  # Persist vector IDs before external writes so partial upserts can be retried or deleted.
    try:
        chunks = sorted(document.chunks, key=lambda chunk: chunk.chunk_index)
        for offset in range(0, len(chunks), BATCH_SIZE):
            batch = chunks[offset : offset + BATCH_SIZE]
            embeddings = embedder.embed([chunk.content for chunk in batch])
            if len(embeddings) != len(batch):
                raise ValueError("Embedding provider returned an unexpected number of vectors")
            vectors = []
            for chunk, values in zip(batch, embeddings, strict=True):
                if len(values) != dimension or not all(math.isfinite(value) for value in values):
                    raise ValueError("Embedding provider returned an invalid vector")
                metadata = {
                    "document_id": str(document.id),
                    "chunk_id": str(chunk.id),
                    "chunk_index": chunk.chunk_index,
                    "source_name": document.filename,
                    "source_type": document.source_type,
                }
                if document.created_at is not None:
                    metadata["created_at"] = document.created_at.timestamp()
                if document.service is not None:
                    metadata["service"] = document.service
                if document.environment is not None:
                    metadata["environment"] = document.environment
                vectors.append({"id": chunk.pinecone_vector_id, "values": values, "metadata": metadata})
            vector_store.upsert(vectors, namespace)
        document.status = "completed"
        session.commit()
    except Exception:
        session.rollback()
        document = session.get(Document, document.id)
        if document is not None:
            document.status = "failed"
            session.commit()
        raise
