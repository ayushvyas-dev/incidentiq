"""Semantic, PostgreSQL full-text, and fused document retrieval."""

import math
import re
from collections.abc import Mapping
from uuid import UUID

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from incidentiq.models import Document, DocumentChunk
from incidentiq.services.ranking import reciprocal_rank_fusion
from incidentiq.services.vector_index import EmbeddingProvider, VectorStore

RRF_CONSTANT = 60


class SearchProviderError(Exception):
    """An embedding or vector search provider failed."""


def _filters(filters: Mapping, *, pinecone: bool = False) -> list | dict:
    if pinecone:
        result = {}
        for key in ("service", "environment"):
            if filters.get(key) is not None:
                result[key] = {"$eq": filters[key]}
        if filters.get("source_types"):
            result["source_type"] = {"$in": filters["source_types"]}
        return result

    expressions = []
    if filters.get("service") is not None:
        expressions.append(Document.service == filters["service"])
    if filters.get("environment") is not None:
        expressions.append(Document.environment == filters["environment"])
    if filters.get("source_types"):
        expressions.append(Document.source_type.in_(filters["source_types"]))
    if filters.get("created_after") is not None:
        expressions.append(Document.created_at >= filters["created_after"])
    if filters.get("created_before") is not None:
        expressions.append(Document.created_at <= filters["created_before"])
    return expressions


def _keyword_ranking(session: Session, query: str, limit: int, filters: Mapping) -> list[str]:
    statement = select(DocumentChunk.id).join(Document).where(
        Document.status == "completed", *_filters(filters)
    )
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        query_vector = func.websearch_to_tsquery("english", query)
        statement = statement.where(DocumentChunk.search_vector.op("@@")(query_vector))
        score = func.ts_rank_cd(DocumentChunk.search_vector, query_vector)
        statement = statement.order_by(score.desc(), DocumentChunk.id)
    elif dialect == "sqlite":
        # SQLite is used by local tests; production keyword ranking uses PostgreSQL's tsvector.
        terms = list(dict.fromkeys(re.findall(r"[\w]+", query.casefold())))[:32]
        if not terms:
            return []
        matches = [
            DocumentChunk.content.ilike(
                f"%{term.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')}%",
                escape="\\",
            )
            for term in terms
        ]
        score = sum(case((match, 1), else_=0) for match in matches)
        statement = statement.where(or_(*matches)).order_by(score.desc(), DocumentChunk.id)
    else:
        raise RuntimeError("Keyword search requires PostgreSQL")
    return [str(chunk_id) for chunk_id in session.scalars(statement.limit(limit))]


def search_chunks(
    session: Session,
    query: str,
    *,
    top_k: int,
    mode: str,
    filters: Mapping,
    embedding_provider: EmbeddingProvider | None,
    vector_store: VectorStore | None,
    namespace: str,
    dimension: int,
) -> tuple[list[dict], int]:
    if not query.strip():
        raise ValueError("query must contain non-whitespace characters")

    candidate_limit = min(top_k * 3, 150)
    semantic: list[tuple[str, float]] = []
    keyword: list[str] = []
    if mode in {"semantic", "hybrid"}:
        if embedding_provider is None or vector_store is None:
            raise RuntimeError("Semantic search is not configured")
        try:
            vectors = embedding_provider.embed([query])
        except Exception as error:
            raise SearchProviderError from error
        try:
            valid_vector = len(vectors) == 1 and len(vectors[0]) == dimension and all(
                math.isfinite(value) for value in vectors[0]
            )
        except (TypeError, ValueError):
            valid_vector = False
        if not valid_vector:
            raise SearchProviderError("Embedding provider returned an invalid query vector")
        try:
            semantic = vector_store.query(
                vectors[0], candidate_limit, namespace, _filters(filters, pinecone=True)
            )
        except Exception as error:
            raise SearchProviderError from error
    if mode in {"keyword", "hybrid"}:
        keyword = _keyword_ranking(session, query, candidate_limit, filters)

    semantic_ids = [item_id for item_id, _ in semantic]
    if mode == "hybrid":
        ranked = reciprocal_rank_fusion([semantic_ids, keyword], constant=RRF_CONSTANT)
    elif mode == "semantic":
        ranked = sorted(semantic, key=lambda item: (-item[1], item[0]))
    else:
        ranked = [
            (item_id, float(len(keyword) - rank))
            for rank, item_id in enumerate(keyword)
        ]

    candidate_count = len(set(semantic_ids) | set(keyword))
    chunk_ids = [UUID(item_id) for item_id, _ in ranked if _is_uuid(item_id)]
    if not chunk_ids:
        return [], candidate_count
    rows = session.execute(
        select(DocumentChunk, Document)
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(Document.status == "completed", DocumentChunk.id.in_(chunk_ids), *_filters(filters))
    ).all()
    chunks = {str(chunk.id): (chunk, document) for chunk, document in rows}
    results = []
    for chunk_id, score in ranked:
        row = chunks.get(chunk_id)
        if row is None:
            continue
        chunk, document = row
        results.append(
            {
                "chunk_id": str(chunk.id),
                "document_id": str(document.id),
                "source": document.filename,
                "source_type": document.source_type,
                "service": document.service,
                "environment": document.environment,
                "excerpt": chunk.content[:500],
                "score": score,
            }
        )
        if len(results) == top_k:
            break
    return results, candidate_count


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
        return True
    except ValueError:
        return False
