"""Idempotent synchronous work performed by the ARQ document worker."""

import time
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from incidentiq.models import Document, Job
from incidentiq.observability import METRICS, span
from incidentiq.services.indexing import index_document
from incidentiq.services.vector_index import EmbeddingProvider, VectorStore


def safe_job_error_code(error: Exception) -> str:
    status_code = getattr(error, "status_code", getattr(error, "code", None))
    name = type(error).__name__.casefold()
    if status_code == 429 or "ratelimit" in name:
        return "RATE_LIMITED"
    if isinstance(error, TimeoutError) or "timeout" in name:
        return "PROVIDER_TIMEOUT"
    if isinstance(status_code, int) and status_code >= 500:
        return "PROVIDER_UNAVAILABLE"
    return "INDEXING_FAILED"


def run_document_job(
    session_factory: sessionmaker[Session],
    document_id: UUID,
    job_id: UUID,
    embedding_provider: EmbeddingProvider,
    vector_store: VectorStore,
    namespace: str,
    dimension: int,
    *,
    max_attempts: int = 3,
    indexer: Callable = index_document,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict | None:
    if max_attempts < 1 or max_attempts > 5:
        raise ValueError("max_attempts must be between 1 and 5")
    for attempt in range(1, max_attempts + 1):
        with session_factory() as session:
            job = session.get(Job, job_id)
            if job is None:
                return None
            document = session.get(Document, document_id)
            if document is None:
                job.status = "failed"
                job.error_code = "DOCUMENT_NOT_FOUND"
                job.finished_at = datetime.now(UTC)
                session.commit()
                return {"status": job.status, "error_code": job.error_code}
            if job.status == "completed" or document.status == "completed":
                job.status = "completed"
                job.error_code = None
                job.progress = {**(job.progress or {}), "stage": "completed"}
                job.finished_at = job.finished_at or datetime.now(UTC)
                session.commit()
                return {"status": "completed"}

            job.status = "processing"
            job.progress = {
                **(job.progress or {}), "stage": "indexing",
                "attempt": attempt, "max_attempts": max_attempts,
            }
            document.status = "processing"
            session.commit()
            ingestion_started = time.perf_counter()
            try:
                with span("ingestion.index_document"):
                    indexer(session, document, embedding_provider, vector_store, namespace, dimension)
                METRICS.observe_stage("ingestion", (time.perf_counter() - ingestion_started) * 1000)
            except Exception as error:  # noqa: BLE001 — persist ingestion failures and their safe error codes.
                METRICS.observe_stage("ingestion", (time.perf_counter() - ingestion_started) * 1000)
                METRICS.increment("ingestion_errors", safe_job_error_code(error))
                session.rollback()
                job = session.get(Job, job_id)
                document = session.get(Document, document_id)
                if job is None:
                    return None
                code = safe_job_error_code(error)
                job.error_code = code
                job.progress = {
                    **(job.progress or {}), "stage": "retrying" if attempt < max_attempts else "failed",
                    "attempt": attempt, "max_attempts": max_attempts,
                }
                if attempt == max_attempts:
                    job.status = "failed"
                    job.finished_at = datetime.now(UTC)
                    if document is not None:
                        document.status = "failed"
                else:
                    job.status = "processing"
                    if document is not None:
                        document.status = "processing"
                session.commit()
                error_code = code
            else:
                job = session.get(Job, job_id)
                document = session.get(Document, document_id)
                if job is None:
                    return None
                job.status = "completed"
                job.error_code = None
                job.progress = {
                    **(job.progress or {}), "stage": "completed",
                    "attempt": attempt, "max_attempts": max_attempts,
                }
                job.finished_at = datetime.now(UTC)
                if document is not None:
                    document.status = "completed"
                session.commit()
                return {"status": "completed", "attempts": attempt}
        if attempt < max_attempts:
            sleeper(min(0.25 * 2 ** (attempt - 1), 1.0))
    return {"status": "failed", "error_code": error_code, "attempts": max_attempts}
