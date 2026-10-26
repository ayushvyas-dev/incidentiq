"""Read-only routing policy, run-decision, and simulation endpoints."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from incidentiq.api.dependencies import get_db_session
from incidentiq.models import AnalysisRun

router = APIRouter(prefix="/routing", tags=["routing"])


@router.get("/policies")
def list_policies(request: Request):
    return {
        "policies": [
            {"name": "static", "description": "Use the configured default model."},
            {"name": "rule_based", "description": "Choose an eligible configured model using budget, latency, and provider health."},
        ],
        "active_policy": request.app.state.routing_policy,
        "provider_health": request.app.state.chat_gateway.health_snapshot(),
    }


@router.get("/decisions/{run_id}")
def get_routing_decision(run_id: UUID, session: Session = Depends(get_db_session)):
    run = session.get(AnalysisRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Analysis run not found")
    decision = run.routing_decision or {}
    return {
        "run_id": str(run.id),
        "policy": run.routing_policy,
        "selected_provider": decision.get("selected_provider", run.provider),
        "selected_model": decision.get("selected_model", run.model),
        "reason_codes": decision.get("reason_codes", []),
        "fallback_used": decision.get("fallback_used", False),
        "attempts": decision.get("attempts", []),
        "excluded": decision.get("excluded", []),
    }


class RoutingSimulationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_type: Literal["incident_analysis"] = "incident_analysis"
    input_tokens_estimate: int = Field(ge=1, le=100000)
    output_tokens_budget: int = Field(ge=1, le=10000)
    max_latency_ms: int | None = Field(default=None, ge=1)
    max_cost_usd: float | None = Field(default=None, ge=0)
    policy: Literal["static", "rule_based"] = "rule_based"
    permitted_providers: list[Literal["groq", "gemini"]] | None = Field(default=None, max_length=2)


@router.post("/simulate")
def simulate_routing(payload: RoutingSimulationRequest, request: Request):
    return request.app.state.chat_gateway.simulate(
        policy=payload.policy,
        input_tokens=payload.input_tokens_estimate,
        output_tokens=payload.output_tokens_budget,
        max_latency_ms=payload.max_latency_ms,
        max_cost_usd=payload.max_cost_usd,
        permitted_providers=set(payload.permitted_providers)
        if payload.permitted_providers is not None else None,
    )
