"""Synchronous document ingestion and metadata endpoints."""

import json
import os
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Annotated, Literal
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from incidentiq.api.dependencies import get_db_session
from incidentiq.ingestion.parsers import (
    InvalidDocument,
    UnsupportedDocument,
    extract_text,
)
from incidentiq.models import Document, DocumentChunk, Job
from incidentiq.services.ingestion import ingest_document

router = APIRouter(tags=["documents"])
SourceType = Literal["runbook", "postmortem", "service_doc", "log", "other"]


def document_result(document: Document, chunk_count: int) -> dict:
    return {
        "document_id": str(document.id),
        "filename": document.filename,
        "source_type": document.source_type,
        "service": document.service,
        "environment": document.environment,
        "status": document.status,
        "chunk_count": chunk_count,
        "content_sha256": document.content_sha256,
        "error": None,
        "created_at": document.created_at,
        "updated_at": document.updated_at,
    }


@router.post("/documents", status_code=202)
async def upload_document(
    file: Annotated[UploadFile, File()],
    source_type: Annotated[SourceType, Form()],
    request: Request,
    response: Response,
    service: Annotated[str | None, Form(max_length=128)] = None,
    environment: Annotated[str | None, Form(max_length=64)] = None,
    metadata: Annotated[str | None, Form(max_length=10_000)] = None,
    session: Session = Depends(get_db_session),
):
    filename = PurePosixPath((file.filename or "").replace("\\", "/")).name
    if not filename or "\x00" in filename or len(filename) > 255:
        raise HTTPException(status_code=400, detail="Invalid filename")

    try:
        max_bytes = int(os.getenv("MAX_UPLOAD_MB", "10")) * 1024 * 1024
    except ValueError as error:
        raise RuntimeError("MAX_UPLOAD_MB must be an integer") from error
    if max_bytes <= 0:
        raise RuntimeError("MAX_UPLOAD_MB must be greater than zero")

    if file.size is not None and file.size > max_bytes:
        raise HTTPException(status_code=413, detail="Upload exceeds the configured size limit")
    raw_content = await file.read(max_bytes + 1)
    if len(raw_content) > max_bytes:
        raise HTTPException(status_code=413, detail="Upload exceeds the configured size limit")
    try:
        text = extract_text(filename, file.content_type, raw_content)
    except UnsupportedDocument as error:
        raise HTTPException(status_code=415, detail=str(error)) from error
    except InvalidDocument as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    try:
        document_metadata = json.loads(metadata) if metadata else {}
    except json.JSONDecodeError as error:
        raise HTTPException(status_code=422, detail="Metadata must be valid JSON") from error
    if not isinstance(document_metadata, dict):
        raise HTTPException(status_code=422, detail="Metadata must be a JSON object")

    queue = request.app.state.job_queue
    if queue is None:
        raise HTTPException(status_code=503, detail="Document queue is not configured")

    try:
        chunk_size = int(os.getenv("CHUNK_SIZE", "800"))
        chunk_overlap = int(os.getenv("CHUNK_OVERLAP", "120"))
        document, duplicate = ingest_document(
            session,
            filename=filename,
            raw_content=raw_content,
            text=text,
            source_type=source_type,
            service=service,
            environment=environment,
            metadata=document_metadata,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    if duplicate:
        if document.status == "completed":
            response.status_code = 200
            return {**document_result(document, len(document.chunks)), "duplicate": True}
        existing_job = session.scalar(
            select(Job)
            .where(
                Job.job_type == "document_ingestion",
                Job.resource_id == document.id,
                Job.status.in_(["queued", "processing"]),
            )
            .order_by(Job.created_at.desc())
        )
        if existing_job is not None:
            response.status_code = 202
            return {
                "document_id": str(document.id), "job_id": str(existing_job.id),
                "filename": document.filename, "status": existing_job.status,
                "message": "Document ingestion is already queued.", "duplicate": True,
            }

    document.status = "queued"
    job = Job(
        job_type="document_ingestion",
        resource_id=document.id,
        status="queued",
        progress={"stage": "queued", "document_id": str(document.id)},
    )
    session.add(job)
    session.commit()
    try:
        await queue.enqueue_job(
            "process_document_job", str(document.id), str(job.id), _job_id=str(job.id)
        )
    except Exception:  # noqa: BLE001 — any queue failure must mark the persisted job failed.
        job.status = "failed"
        job.error_code = "QUEUE_UNAVAILABLE"
        job.finished_at = datetime.now(UTC)
        job.progress = {**job.progress, "stage": "failed"}
        document.status = "failed"
        session.commit()
        raise HTTPException(status_code=503, detail="Document could not be queued") from None
    return {
        "document_id": str(document.id), "job_id": str(job.id),
        "filename": document.filename, "status": "queued",
        "message": "Document accepted for ingestion.", "duplicate": duplicate,
    }


@router.get("/documents")
def list_documents(
    session: Session = Depends(get_db_session),
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: UUID | None = None,
    service: str | None = None,
    source_type: SourceType | None = None,
    status: Literal["queued", "processing", "completed", "failed"] | None = None,
):
    statement = (
        select(Document, func.count(DocumentChunk.id))
        .outerjoin(DocumentChunk)
        .group_by(Document.id)
    )
    if service is not None:
        statement = statement.where(Document.service == service)
    if source_type is not None:
        statement = statement.where(Document.source_type == source_type)
    if status is not None:
        statement = statement.where(Document.status == status)
    if cursor is not None:
        current = session.get(Document, cursor)
        if current is None:
            raise HTTPException(status_code=400, detail="Cursor document does not exist")
        statement = statement.where(
            or_(
                Document.created_at < current.created_at,
                and_(Document.created_at == current.created_at, Document.id < current.id),
            )
        )
    rows = session.execute(
        statement.order_by(Document.created_at.desc(), Document.id.desc()).limit(limit + 1)
    ).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    return {
        "items": [document_result(document, count) for document, count in rows],
        "next_cursor": str(rows[-1][0].id) if has_more and rows else None,
    }


@router.get("/documents/{document_id}")
def get_document(document_id: UUID, session: Session = Depends(get_db_session)):
    row = session.execute(
        select(Document, func.count(DocumentChunk.id))
        .outerjoin(DocumentChunk)
        .where(Document.id == document_id)
        .group_by(Document.id)
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return document_result(*row)


@router.delete("/documents/{document_id}")
def delete_document(
    document_id: UUID,
    request: Request,
    session: Session = Depends(get_db_session),
):
    document = session.get(Document, document_id)
    if document is not None:
        vector_ids = list(session.scalars(
            select(DocumentChunk.pinecone_vector_id).where(
                DocumentChunk.document_id == document_id,
                DocumentChunk.pinecone_vector_id.is_not(None),
            )
        ))
        if vector_ids:
            vector_store = request.app.state.vector_store
            if vector_store is None:
                raise HTTPException(status_code=503, detail="Vector cleanup is not configured")
            try:
                vector_store.delete(vector_ids, os.getenv("PINECONE_NAMESPACE", "incidentiq"))
            except Exception as error:
                raise HTTPException(status_code=502, detail="Vector cleanup failed; retry deletion") from error
        session.delete(document)
        session.commit()
    return {"document_id": str(document_id), "deleted": True}
