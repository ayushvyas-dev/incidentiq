"""ARQ worker for document indexing jobs."""

import asyncio
import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar
from uuid import UUID

from arq.connections import RedisSettings
from dotenv import load_dotenv
from sqlalchemy import select

from incidentiq.db.session import create_engine, create_session_factory
from incidentiq.models import Document, EvaluationRun, Job
from incidentiq.services.evaluation_runner import run_evaluation_job
from incidentiq.services.gemini import GeminiEmbeddings
from incidentiq.services.jobs import run_document_job, safe_job_error_code
from incidentiq.services.routing import configured_gateway
from incidentiq.services.vector_index import PineconeVectorStore

load_dotenv()


async def worker_startup(ctx: dict) -> None:
    database_url = os.getenv("DATABASE_URL")
    gemini_key = os.getenv("GEMINI_API_KEY")
    embedding_model = os.getenv("GEMINI_EMBEDDING_MODEL")
    pinecone_key = os.getenv("PINECONE_API_KEY")
    pinecone_index = os.getenv("PINECONE_INDEX")
    if not database_url:
        raise RuntimeError("Worker database configuration is required")
    if bool(gemini_key) != bool(embedding_model):
        raise RuntimeError("Gemini API key and embedding model must be configured together")
    if bool(pinecone_key) != bool(pinecone_index):
        raise RuntimeError("Pinecone API key and index must be configured together")
    dimension = int(os.getenv("EMBEDDING_DIMENSION", "768"))
    if dimension < 1:
        raise RuntimeError("EMBEDDING_DIMENSION must be positive")
    engine = create_engine(database_url)
    factory = create_session_factory(engine)
    ctx.update(
        engine=engine,
        session_factory=factory,
        embedding_provider=(GeminiEmbeddings(
            gemini_key, embedding_model, dimension,
            float(os.getenv("CHAT_TIMEOUT_SECONDS", "20")),
        ) if gemini_key and embedding_model else None),
        vector_store=(PineconeVectorStore(pinecone_key, pinecone_index) if pinecone_key else None),
        chat_gateway=configured_gateway(),
        dataset_dir=os.getenv("EVALUATION_DATASET_DIR", str(Path(__file__).resolve().parents[3] / "datasets")),
        namespace=os.getenv("PINECONE_NAMESPACE", "incidentiq"),
        dimension=dimension,
    )
    await requeue_pending_jobs(ctx)


async def worker_shutdown(ctx: dict) -> None:
    engine = ctx.get("engine")
    if engine is not None:
        engine.dispose()


async def requeue_pending_jobs(ctx: dict) -> int:
    """Recover jobs committed to NeonDB before an API/Redis interruption."""
    factory = ctx["session_factory"]
    with factory() as session:
        jobs = list(session.scalars(
            select(Job)
            .where(Job.job_type.in_(["document_ingestion", "evaluation"]), Job.status.in_(["queued", "processing"]))
            .order_by(Job.created_at)
        ))
        for job in jobs:
            if job.resource_id is None:
                job.status = "failed"
                job.error_code = "INVALID_RESOURCE_ID"
                job.finished_at = datetime.now(UTC)
                continue
            if job.status == "processing":
                job.status = "queued"
                job.progress = {**(job.progress or {}), "stage": "queued"}
                model = Document if job.job_type == "document_ingestion" else EvaluationRun
                resource = session.get(model, job.resource_id)
                if resource is not None and resource.status == "processing":
                    resource.status = "queued"
        session.commit()
    count = 0
    for job in jobs:
        if job.resource_id is None:
            continue
        function = "process_document_job" if job.job_type == "document_ingestion" else "process_evaluation_job"
        await ctx["redis"].enqueue_job(function, str(job.resource_id), str(job.id), _job_id=str(job.id))
        count += 1
    return count


async def process_document_job(ctx: dict, document_id: str, job_id: str) -> dict | None:
    return await asyncio.to_thread(
        run_document_job,
        ctx["session_factory"],
        UUID(document_id),
        UUID(job_id),
        ctx["embedding_provider"],
        ctx["vector_store"],
        ctx["namespace"],
        ctx["dimension"],
        max_attempts=int(os.getenv("INGESTION_JOB_MAX_ATTEMPTS", "3")),
    )


async def process_evaluation_job(ctx: dict, evaluation_run_id: str, job_id: str) -> dict | None:
    try:
        return await asyncio.to_thread(
            run_evaluation_job,
            ctx["session_factory"],
            UUID(evaluation_run_id),
            UUID(job_id),
            dataset_dir=Path(ctx["dataset_dir"]),
            embedding_provider=ctx["embedding_provider"],
            vector_store=ctx["vector_store"],
            chat_gateway=ctx["chat_gateway"],
            namespace=ctx["namespace"],
            dimension=ctx["dimension"],
        )
    except Exception as error:  # noqa: BLE001 — persist any unhandled job failure before ARQ retries it.
        with ctx["session_factory"]() as session:
            job = session.get(Job, UUID(job_id))
            run = session.get(EvaluationRun, UUID(evaluation_run_id))
            if job is not None:
                job.status = "failed"
                job.error_code = "DATASET_INVALID" if isinstance(error, ValueError) else safe_job_error_code(error)
                job.finished_at = datetime.now(UTC)
            if run is not None:
                run.status = "failed"
                run.finished_at = datetime.now(UTC)
            session.commit()
        return {"status": "failed"}


class WorkerSettings:
    functions: ClassVar[list[Callable[..., Any]]] = [process_document_job, process_evaluation_job]
    redis_settings = RedisSettings.from_dsn(os.getenv("REDIS_URL") or "redis://localhost:6379/0")
    on_startup = worker_startup
    on_shutdown = worker_shutdown
    max_jobs = 5
    max_tries = 1
    job_timeout = 600
    keep_result = 3600
