"""Evaluation dataset submission and result endpoints."""

import hashlib
import json
import math
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from incidentiq.api.dependencies import get_db_session
from incidentiq.models import EvaluationCaseResult, EvaluationRun, Job
from incidentiq.services.evaluation import load_dataset

router = APIRouter(prefix="/evaluations", tags=["evaluations"])


class EvaluationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    retrieval_mode: Literal["keyword", "semantic", "hybrid"] = "keyword"
    top_k: int = Field(default=5, ge=1, le=20)
    prompt_version: Literal["grounded-v1"] = "grounded-v1"
    routing_policy: Literal["static", "rule_based"] = "static"
    max_output_tokens: int = Field(default=1500, ge=100, le=3000)
    permitted_providers: list[Literal["groq", "gemini"]] | None = Field(default=None, max_length=2)

    @model_validator(mode="after")
    def validate_providers(self):
        if self.permitted_providers is not None and (
            not self.permitted_providers or len(set(self.permitted_providers)) != len(self.permitted_providers)
        ):
            raise ValueError("permitted_providers must contain unique provider names")
        return self


class EvaluationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dataset_id: str = Field(min_length=1, max_length=128)
    split: Literal["validation", "holdout"]
    experiment_name: str = Field(min_length=1, max_length=128)
    config: EvaluationConfig = Field(default_factory=EvaluationConfig)
    baseline_run_id: UUID | None = None
    regression_thresholds: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_request(self):
        if not self.experiment_name.strip():
            raise ValueError("experiment_name must contain non-whitespace characters")
        allowed = {
            f"recall_at_{self.config.top_k}", f"hit_rate_at_{self.config.top_k}",
            "mrr", f"ndcg_at_{self.config.top_k}", "answer_correctness_rate",
            "citation_support_rate", "schema_valid_rate", "abstention_accuracy",
            "p95_latency_ms", "estimated_cost_per_case_usd",
        }
        if set(self.regression_thresholds) - allowed:
            raise ValueError("regression_thresholds contains an unknown metric")
        if any(not math.isfinite(value) or value < 0 for value in self.regression_thresholds.values()):
            raise ValueError("regression thresholds must be finite and non-negative")
        return self


def _dataset_directory() -> Path:
    return Path(os.getenv("EVALUATION_DATASET_DIR", Path(__file__).resolve().parents[3] / "datasets"))


@router.post("", status_code=202)
async def start_evaluation(
    payload: EvaluationRequest,
    request: Request,
    session: Session = Depends(get_db_session),
):
    try:
        dataset = load_dataset(_dataset_directory(), payload.dataset_id, payload.split)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    queue = request.app.state.job_queue
    if queue is None:
        raise HTTPException(status_code=503, detail="Evaluation queue is not configured")
    baseline = None
    if payload.baseline_run_id:
        baseline = session.get(EvaluationRun, payload.baseline_run_id)
        if (
            baseline is None or baseline.status != "completed"
            or baseline.dataset_id != payload.dataset_id
            or baseline.dataset_version != dataset["version"]
            or baseline.config.get("split") != payload.split
        ):
            raise HTTPException(status_code=422, detail="Baseline run must be completed for this dataset")

    config = payload.config.model_dump()
    config.update({
        "split": payload.split,
        "regression_thresholds": payload.regression_thresholds,
        "embedding_model": getattr(request.app.state.embedding_provider, "model", None),
        "embedding_dimension": getattr(request.app.state.embedding_provider, "dimension", None),
        "vector_index": os.getenv("PINECONE_INDEX"),
        "namespace": os.getenv("PINECONE_NAMESPACE", "incidentiq"),
        "routing_options": {
            "max_attempts": int(os.getenv("CHAT_MAX_ATTEMPTS", "2")),
            "timeout_seconds": float(os.getenv("CHAT_TIMEOUT_SECONDS", "20")),
            "circuit_failure_threshold": int(os.getenv("CHAT_CIRCUIT_FAILURE_THRESHOLD", "3")),
            "circuit_reset_seconds": float(os.getenv("CHAT_CIRCUIT_RESET_SECONDS", "30")),
        },
        "configured_models": [
            {"provider": provider.provider, "model": provider.model}
            for provider in request.app.state.chat_gateway.providers.values()
        ],
    })
    digest_input = json.dumps(
        {"dataset_id": payload.dataset_id, "dataset_version": dataset["version"], "config": config},
        sort_keys=True, separators=(",", ":"),
    ).encode()
    config_hash = hashlib.sha256(digest_input).hexdigest()
    config["config_hash"] = config_hash
    run = EvaluationRun(
        dataset_id=payload.dataset_id,
        dataset_version=dataset["version"],
        experiment_name=payload.experiment_name.strip(),
        config=config,
        baseline_run_id=baseline.id if baseline is not None else None,
        status="queued",
        metrics={},
    )
    session.add(run)
    session.flush()
    job = Job(
        job_type="evaluation",
        resource_id=run.id,
        status="queued",
        progress={"stage": "queued", "total_cases": len(dataset["cases"])},
    )
    session.add(job)
    session.commit()
    try:
        await queue.enqueue_job(
            "process_evaluation_job", str(run.id), str(job.id), _job_id=str(job.id)
        )
    except Exception:  # noqa: BLE001 — any queue failure must mark the persisted run failed.
        run.status = job.status = "failed"
        job.error_code = "QUEUE_UNAVAILABLE"
        job.finished_at = datetime.now(UTC)
        session.commit()
        raise HTTPException(status_code=503, detail="Evaluation could not be queued") from None
    return {
        "evaluation_run_id": str(run.id), "status": "queued",
        "dataset_id": run.dataset_id, "dataset_version": run.dataset_version,
        "split": payload.split, "job_id": str(job.id), "config_hash": config_hash,
    }


@router.get("")
def list_evaluations(
    session: Session = Depends(get_db_session),
    dataset_id: str | None = None,
    status: Literal["queued", "processing", "completed", "failed"] | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
):
    statement = select(EvaluationRun)
    if dataset_id:
        statement = statement.where(EvaluationRun.dataset_id == dataset_id)
    if status:
        statement = statement.where(EvaluationRun.status == status)
    runs = session.scalars(statement.order_by(EvaluationRun.created_at.desc()).limit(limit))
    return {"items": [_run_summary(run) for run in runs]}


@router.get("/{evaluation_run_id}/cases")
def list_evaluation_cases(evaluation_run_id: UUID, session: Session = Depends(get_db_session)):
    if session.get(EvaluationRun, evaluation_run_id) is None:
        raise HTTPException(status_code=404, detail="Evaluation run not found")
    rows = session.scalars(
        select(EvaluationCaseResult).where(
            EvaluationCaseResult.evaluation_run_id == evaluation_run_id
        ).order_by(EvaluationCaseResult.case_id)
    )
    return {"evaluation_run_id": str(evaluation_run_id), "items": [
        {"case_id": row.case_id, **row.result} for row in rows
    ]}


@router.get("/{evaluation_run_id}")
def get_evaluation(evaluation_run_id: UUID, session: Session = Depends(get_db_session)):
    run = session.get(EvaluationRun, evaluation_run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Evaluation run not found")
    job = session.scalar(
        select(Job).where(Job.job_type == "evaluation", Job.resource_id == run.id)
        .order_by(Job.created_at.desc()).limit(1)
    )
    return {
        **_run_summary(run),
        "config": run.config,
        "metrics": run.metrics,
        "baseline_comparison": run.metrics.get("baseline_comparison"),
        "error": {"code": job.error_code} if job is not None and job.error_code else None,
        "finished_at": run.finished_at,
    }


def _run_summary(run: EvaluationRun) -> dict:
    return {
        "evaluation_run_id": str(run.id),
        "experiment_name": run.experiment_name,
        "dataset_id": run.dataset_id,
        "dataset_version": run.dataset_version,
        "split": run.config.get("split"),
        "status": run.status,
        "config_hash": run.config.get("config_hash"),
        "created_at": run.created_at,
    }
