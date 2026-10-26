"""Incident analysis and persisted investigation read endpoints."""

import os
from datetime import UTC, datetime
from time import perf_counter
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

from incidentiq.api.dependencies import get_db_session
from incidentiq.models import AnalysisRun, Incident
from incidentiq.observability import METRICS, span
from incidentiq.services.analysis import analysis_messages
from incidentiq.services.retrieval import SearchProviderError, search_chunks
from incidentiq.services.routing import RoutingError

router = APIRouter(prefix="/incidents", tags=["incidents"])
Severity = Literal["SEV-1", "SEV-2", "SEV-3", "SEV-4", "unknown"]
Confidence = Literal["low", "medium", "high"]


class TimeWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start: datetime
    end: datetime

    @model_validator(mode="after")
    def validate_window(self):
        if self.start.utcoffset() is None or self.end.utcoffset() is None:
            raise ValueError("time window timestamps must include a timezone")
        if self.start > self.end:
            raise ValueError("time window start must be before end")
        return self


class AnalysisOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    top_k: int = Field(default=8, ge=1, le=20)
    include_diagnostic_steps: bool = True
    max_output_tokens: int = Field(default=1500, ge=100, le=3000)
    routing_policy: Literal["static", "rule_based"] | None = None
    max_latency_ms: int | None = Field(default=None, ge=1)
    max_cost_usd: float | None = Field(default=None, ge=0)
    permitted_providers: list[Literal["groq", "gemini"]] | None = Field(
        default=None, max_length=2
    )


class IncidentAnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1, max_length=10000)
    service: str = Field(min_length=1, max_length=128)
    environment: str = Field(min_length=1, max_length=64)
    severity: Severity
    symptoms: list[str] = Field(default_factory=list, max_length=30)
    log_excerpt: str | None = Field(default=None, max_length=4000)
    time_window: TimeWindow | None = None
    options: AnalysisOptions = Field(default_factory=AnalysisOptions)

    @model_validator(mode="after")
    def validate_text(self):
        if not self.title.strip() or not self.description.strip():
            raise ValueError(
                "title and description must contain non-whitespace characters"
            )
        if any(not symptom.strip() or len(symptom) > 1000 for symptom in self.symptoms):
            raise ValueError("symptoms must be non-empty and at most 1000 characters")
        return self


class EvidenceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: str
    chunk_id: str
    quote: str = Field(min_length=1, max_length=1000)


class HypothesisDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=255)
    confidence: Confidence
    rationale: str = Field(min_length=1, max_length=2000)
    supporting_evidence: list[EvidenceRef] = Field(min_length=1, max_length=10)
    contradictory_evidence: list[EvidenceRef] = Field(
        default_factory=list, max_length=10
    )
    missing_evidence: list[str] = Field(default_factory=list, max_length=10)


class DiagnosticStepDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: str = Field(min_length=1, max_length=500)
    rationale: str = Field(min_length=1, max_length=1000)


class AnalysisDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str = Field(min_length=1, max_length=3000)
    quality_result: Literal["evidence_found", "insufficient_evidence"]
    hypotheses: list[HypothesisDraft] = Field(max_length=5)
    diagnostic_steps: list[DiagnosticStepDraft] = Field(max_length=8)

    @model_validator(mode="after")
    def validate_quality(self):
        if self.quality_result == "evidence_found" and not self.hypotheses:
            raise ValueError("evidence_found requires a supported hypothesis")
        if self.quality_result == "insufficient_evidence" and (
            self.hypotheses or self.diagnostic_steps
        ):
            raise ValueError(
                "insufficient_evidence must not include hypotheses or diagnostic steps"
            )
        return self


class EvidenceResponse(BaseModel):
    document_id: str
    chunk_id: str
    source: str
    quote: str


class HypothesisResponse(BaseModel):
    rank: int
    title: str
    confidence: Confidence
    reasoning: str
    supporting_evidence: list[EvidenceResponse]
    contradictory_evidence: list[EvidenceResponse]
    missing_evidence: list[str]


class DiagnosticStepResponse(BaseModel):
    step: int
    action: str
    reason: str
    risk: Literal["read_only"]


class CitationResponse(BaseModel):
    document_id: str
    chunk_id: str
    source: str


class RunResponse(BaseModel):
    run_id: str
    provider: str | None
    model: str | None
    routing_policy: str | None
    latency_ms: int | None
    input_tokens: int | None
    output_tokens: int | None
    estimated_cost_usd: float | None
    routing_decision: dict | None


class AnalysisQualityResponse(BaseModel):
    result: Literal["evidence_found", "insufficient_evidence"]
    abstained: bool


class IncidentAnalysisResponse(BaseModel):
    incident_id: str
    status: Literal["completed"]
    summary: str
    hypotheses: list[HypothesisResponse]
    diagnostic_steps: list[DiagnosticStepResponse]
    citations: list[CitationResponse]
    limitations: list[str]
    quality: AnalysisQualityResponse
    run: RunResponse


def _failure(run: AnalysisRun, incident: Incident, code: str) -> None:
    run.status = "failed"
    run.error_code = code
    run.finished_at = datetime.now(UTC)
    incident.status = "failed"


def _validated_evidence(
    refs: list[EvidenceRef], by_chunk: dict[str, dict]
) -> list[dict]:
    output = []
    for ref in refs:
        chunk = by_chunk.get(ref.chunk_id)
        if (
            chunk is None
            or chunk["document_id"] != ref.document_id
            or ref.quote.casefold() not in chunk["excerpt"].casefold()
        ):
            raise ValueError("model evidence does not match retrieved content")
        output.append(
            {
                "document_id": ref.document_id,
                "chunk_id": ref.chunk_id,
                "source": chunk["source"],
                "quote": ref.quote,
            }
        )
    return output


@router.post("/analyze", response_model=IncidentAnalysisResponse)
def analyze_incident(
    payload: IncidentAnalysisRequest,
    request: Request,
    session: Session = Depends(get_db_session),
):
    incident = Incident(
        title=payload.title,
        description=payload.description,
        service=payload.service,
        environment=payload.environment,
        severity=payload.severity,
        status="processing",
    )
    session.add(incident)
    session.flush()
    run = AnalysisRun(
        incident_id=incident.id,
        status="processing",
        prompt_version="grounded-v1",
        routing_policy=payload.options.routing_policy
        or request.app.state.routing_policy,
    )
    session.add(run)
    session.commit()
    session.refresh(incident)
    session.refresh(run)

    embedder = request.app.state.embedding_provider
    vector_store = request.app.state.vector_store
    mode = "hybrid" if embedder is not None and vector_store is not None else "keyword"
    filters = {"service": payload.service, "environment": payload.environment}
    if payload.time_window:
        filters.update(
            created_after=payload.time_window.start,
            created_before=payload.time_window.end,
        )
    retrieval_started = perf_counter()
    try:
        with span("retrieval.incident_search"):
            results, candidate_count = search_chunks(
                session,
                " ".join(
                    [payload.title, payload.description, *payload.symptoms]
                    + ([payload.log_excerpt] if payload.log_excerpt else [])
                ),
                top_k=payload.options.top_k,
                mode=mode,
                filters=filters,
                embedding_provider=embedder,
                vector_store=vector_store,
                namespace=os.getenv("PINECONE_NAMESPACE", "incidentiq"),
                dimension=int(os.getenv("EMBEDDING_DIMENSION", "1536"))
                if mode == "hybrid"
                else 0,
            )
    except (SearchProviderError, ValueError, RuntimeError):
        _failure(run, incident, "RETRIEVAL_FAILED")
        session.commit()
        raise HTTPException(
            status_code=502, detail="Incident evidence retrieval failed"
        ) from None
    METRICS.observe_stage("retrieval", (perf_counter() - retrieval_started) * 1000)
    METRICS.retrieval(candidate_count, False)

    run.retrieval_config_version = "hybrid-rrf-v1" if mode == "hybrid" else "keyword-v1"
    if not results:
        run.routing_decision = {
            "policy": run.routing_policy,
            "selected_provider": None,
            "selected_model": None,
            "reason_codes": ["generation_skipped_no_evidence"],
            "fallback_used": False,
            "attempts": [],
            "excluded": [],
        }
        result = {
            "incident_id": str(incident.id),
            "status": "completed",
            "summary": "Available records do not contain enough evidence to assess this incident.",
            "hypotheses": [],
            "diagnostic_steps": [],
            "citations": [],
            "limitations": ["No relevant completed documents were retrieved."],
            "quality": {"result": "insufficient_evidence", "abstained": True},
        }
        run.status = "completed"
        run.result = result
        run.finished_at = datetime.now(UTC)
        incident.status = "completed"
        session.commit()
        return {**result, "run": _run_data(run)}

    gateway = request.app.state.chat_gateway
    if not gateway.providers:
        _failure(run, incident, "CHAT_PROVIDER_UNAVAILABLE")
        run.routing_decision = {
            "policy": run.routing_policy,
            "selected_provider": None,
            "selected_model": None,
            "reason_codes": ["no_configured_provider"],
            "fallback_used": False,
            "attempts": [],
            "excluded": [],
        }
        session.commit()
        raise HTTPException(
            status_code=503, detail="Analysis provider is not configured"
        )

    evidence = [
        {
            key: row[key]
            for key in ("document_id", "chunk_id", "source", "source_type", "excerpt")
        }
        for row in results
    ]
    incident_data = payload.model_dump(mode="json", exclude={"options"})
    started = perf_counter()
    try:
        policy = run.routing_policy
        input_tokens_estimate = max(
            1,
            sum(
                len(value) for value in incident_data.values() if isinstance(value, str)
            )
            // 4,
        )
        generation_started = perf_counter()
        try:
            with span("incident.generation"):
                generated = gateway.generate(
                    analysis_messages(incident_data, evidence),
                    payload.options.max_output_tokens,
                    policy=policy,
                    input_tokens_estimate=input_tokens_estimate,
                    max_latency_ms=payload.options.max_latency_ms,
                    max_cost_usd=payload.options.max_cost_usd,
                    permitted_providers=set(payload.options.permitted_providers)
                    if payload.options.permitted_providers is not None
                    else None,
                )
        finally:
            METRICS.observe_stage(
                "generation", (perf_counter() - generation_started) * 1000
            )
        run.provider = generated.provider
        run.model = generated.model
        run.input_tokens = generated.input_tokens
        run.output_tokens = generated.output_tokens
        run.estimated_cost_usd = generated.estimated_cost_usd
        run.routing_decision = generated.decision
        draft = AnalysisDraft.model_validate_json(generated.content)
        by_chunk = {row["chunk_id"]: row for row in results}
        hypotheses = []
        citation_map: dict[tuple[str, str], dict] = {}
        for rank, hypothesis in enumerate(draft.hypotheses, 1):
            support = _validated_evidence(hypothesis.supporting_evidence, by_chunk)
            contradictory = _validated_evidence(
                hypothesis.contradictory_evidence, by_chunk
            )
            for citation in support + contradictory:
                citation_map[(citation["document_id"], citation["chunk_id"])] = {
                    key: citation[key] for key in ("document_id", "chunk_id", "source")
                }
            hypotheses.append(
                {
                    "rank": rank,
                    "title": hypothesis.title,
                    "confidence": hypothesis.confidence,
                    "reasoning": hypothesis.rationale,
                    "supporting_evidence": support,
                    "contradictory_evidence": contradictory,
                    "missing_evidence": hypothesis.missing_evidence,
                }
            )
        steps = (
            [
                {
                    "step": index,
                    "action": step.action,
                    "reason": step.rationale,
                    "risk": "read_only",
                }
                for index, step in enumerate(draft.diagnostic_steps, 1)
            ]
            if payload.options.include_diagnostic_steps
            else []
        )
        insufficient = draft.quality_result == "insufficient_evidence"
        result = {
            "incident_id": str(incident.id),
            "status": "completed",
            "summary": draft.summary,
            "hypotheses": hypotheses,
            "diagnostic_steps": steps,
            "citations": list(citation_map.values()),
            "limitations": [
                "Hypotheses are not confirmed root causes; verify with operational evidence."
            ],
            "quality": {"result": draft.quality_result, "abstained": insufficient},
        }
        run.status = "completed"
        run.latency_ms = round((perf_counter() - started) * 1000)
        run.result = result
        run.finished_at = datetime.now(UTC)
        incident.status = "completed"
        session.commit()
        return {**result, "run": _run_data(run)}
    except Exception as error:  # noqa: BLE001 — persist a failed run for provider and validation failures.
        _failure(
            run,
            incident,
            "PROVIDER_FAILURE"
            if isinstance(error, (RoutingError, ValueError))
            else "ANALYSIS_FAILED",
        )
        if hasattr(error, "decision"):
            run.routing_decision = error.decision
        run.latency_ms = round((perf_counter() - started) * 1000)
        session.commit()
        raise HTTPException(
            status_code=502,
            detail="Incident analysis provider returned an invalid response",
        ) from None


def _run_data(run: AnalysisRun) -> dict:
    return {
        "run_id": str(run.id),
        "provider": run.provider,
        "model": run.model,
        "routing_policy": run.routing_policy,
        "latency_ms": run.latency_ms,
        "input_tokens": run.input_tokens,
        "output_tokens": run.output_tokens,
        "estimated_cost_usd": run.estimated_cost_usd,
        "routing_decision": run.routing_decision,
    }


def _incident_data(incident: Incident, latest: AnalysisRun | None = None) -> dict:
    return {
        "incident_id": str(incident.id),
        "title": incident.title,
        "description": incident.description,
        "service": incident.service,
        "environment": incident.environment,
        "severity": incident.severity,
        "status": incident.status,
        "latest_run_id": str(latest.id) if latest else None,
        "latest_result": latest.result if latest else None,
        "created_at": incident.created_at,
    }


@router.get("")
def list_incidents(
    session: Session = Depends(get_db_session),
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: UUID | None = None,
    service: str | None = None,
    severity: Severity | None = None,
    status: Literal["open", "processing", "completed", "failed"] | None = None,
):
    statement = select(Incident)
    if service is not None:
        statement = statement.where(Incident.service == service)
    if severity is not None:
        statement = statement.where(Incident.severity == severity)
    if status is not None:
        statement = statement.where(Incident.status == status)
    if cursor is not None:
        cursor_incident = session.get(Incident, cursor)
        if cursor_incident is None:
            raise HTTPException(status_code=422, detail="Invalid incident cursor")
        statement = statement.where(
            tuple_(Incident.created_at, Incident.id)
            < tuple_(cursor_incident.created_at, cursor_incident.id)
        )
    items = list(
        session.scalars(
            statement.order_by(Incident.created_at.desc(), Incident.id.desc()).limit(
                limit + 1
            )
        )
    )
    has_more = len(items) > limit
    items = items[:limit]
    return {
        "items": [_incident_data(item) for item in items],
        "next_cursor": str(items[-1].id) if has_more and items else None,
    }


@router.get("/{incident_id}/runs")
def list_incident_runs(incident_id: UUID, session: Session = Depends(get_db_session)):
    if session.get(Incident, incident_id) is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    runs = session.scalars(
        select(AnalysisRun)
        .where(AnalysisRun.incident_id == incident_id)
        .order_by(AnalysisRun.created_at.desc(), AnalysisRun.id.desc())
    )
    return {
        "items": [
            {
                **_run_data(run),
                "status": run.status,
                "result": run.result,
                "error_code": run.error_code,
                "created_at": run.created_at,
                "finished_at": run.finished_at,
            }
            for run in runs
        ]
    }


@router.get("/{incident_id}")
def get_incident(incident_id: UUID, session: Session = Depends(get_db_session)):
    incident = session.get(Incident, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    latest = session.scalar(
        select(AnalysisRun)
        .where(AnalysisRun.incident_id == incident_id)
        .order_by(AnalysisRun.created_at.desc(), AnalysisRun.id.desc())
        .limit(1)
    )
    return _incident_data(incident, latest)
