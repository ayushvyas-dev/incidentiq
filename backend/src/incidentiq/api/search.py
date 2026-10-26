"""Search endpoint for retrieved document chunks."""

import os
from datetime import datetime
from time import perf_counter
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from incidentiq.api.dependencies import get_db_session
from incidentiq.observability import METRICS, span
from incidentiq.services.retrieval import SearchProviderError, search_chunks

router = APIRouter(tags=["search"])
SourceType = Literal["runbook", "postmortem", "service_doc", "log", "other"]
SearchMode = Literal["hybrid", "semantic", "keyword"]


class SearchFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service: str | None = Field(default=None, max_length=128)
    environment: str | None = Field(default=None, max_length=64)
    source_types: list[SourceType] | None = Field(default=None, max_length=5)
    created_after: datetime | None = None
    created_before: datetime | None = None

    @model_validator(mode="after")
    def validate_dates(self):
        for value in (self.created_after, self.created_before):
            if value is not None and value.utcoffset() is None:
                raise ValueError("date filters must include a timezone")
        if (
            self.created_after is not None
            and self.created_before is not None
            and self.created_after > self.created_before
        ):
            raise ValueError("created_after must be before created_before")
        return self


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=4000)
    top_k: int = Field(default=8, ge=1, le=50)
    filters: SearchFilters | None = None
    use_hybrid_search: bool = True
    use_reranker: bool = False
    mode: SearchMode | None = None

    @property
    def search_mode(self) -> SearchMode:
        if self.mode is not None:
            return self.mode
        return "hybrid" if self.use_hybrid_search else "semantic"


@router.post("/search")
def search_documents(
    payload: SearchRequest,
    request: Request,
    session: Session = Depends(get_db_session),
):
    mode = payload.search_mode
    if payload.use_reranker:
        raise HTTPException(status_code=503, detail="Reranking is not configured")
    embedder = request.app.state.embedding_provider
    vector_store = request.app.state.vector_store
    if mode in {"hybrid", "semantic"} and (embedder is None or vector_store is None):
        raise HTTPException(status_code=503, detail="Semantic search is not configured")
    dimension = 0
    if mode != "keyword":
        try:
            dimension = int(os.getenv("EMBEDDING_DIMENSION", "768"))
            if dimension <= 0:
                raise ValueError
        except ValueError as error:
            raise RuntimeError("EMBEDDING_DIMENSION must be a positive integer") from error

    started = perf_counter()
    try:
        with span("retrieval.search"):
            results, candidate_count = search_chunks(
                session,
                payload.query,
                top_k=payload.top_k,
                mode=mode,
                filters=payload.filters.model_dump(exclude_none=True) if payload.filters else {},
                embedding_provider=embedder,
                vector_store=vector_store,
                namespace=os.getenv("PINECONE_NAMESPACE", "incidentiq"),
                dimension=dimension,
            )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except SearchProviderError as error:
        raise HTTPException(status_code=502, detail="Search provider failed") from error

    METRICS.observe_stage("retrieval", (perf_counter() - started) * 1000)
    METRICS.retrieval(candidate_count, False)

    return {
        "query": payload.query,
        "results": [
            {**result, "rank": rank}
            for rank, result in enumerate(results, start=1)
        ],
        "retrieval": {
            "mode": mode,
            "reranker_used": False,
            "candidate_count": candidate_count,
        },
        "latency_ms": round((perf_counter() - started) * 1000),
    }
