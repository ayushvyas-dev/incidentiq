# IncidentIQ --- Requirements & Technical Specification

**Document status:** Initial implementation specification\
**Project type:** Production-oriented AI incident investigation
platform\
**Primary language:** Python 3.12+\
**Package and environment manager:** `uv`\
**API framework:** FastAPI

------------------------------------------------------------------------

## 1. Project Overview

IncidentIQ helps software engineers investigate production incidents by
searching application logs, runbooks, service documentation, and
historical incident reports. It returns evidence-backed hypotheses,
cites the sources used, and recommends safe diagnostic next steps.

IncidentIQ is a decision-support system, not an autonomous production
operator. It must never execute remediation commands against real
infrastructure in the initial release.

### 1.1 Problem

During an incident, engineers lose time correlating logs, documentation,
service dependencies, and previous incidents. A general-purpose LLM may
produce plausible but unsupported explanations. IncidentIQ combines
retrieval, structured analysis, evaluation, observability, and model
routing to make investigations faster and more auditable.

### 1.2 Goals

-   Ingest operational documents and incident data.
-   Support keyword and semantic retrieval.
-   Return source-grounded hypotheses with citations.
-   State uncertainty and abstain when evidence is insufficient.
-   Measure retrieval and answer quality using a repeatable evaluation
    dataset.
-   Track latency, token usage, model/provider failures, and estimated
    cost.
-   Route requests between configured LLM providers using explicit,
    testable policies.
-   Provide an API suitable for a future web dashboard.
-   Ship with tests, Docker support, CI, health checks, and operational
    documentation.

### 1.3 Non-goals for the first release

-   Automatically running shell commands or changing production
    infrastructure.
-   Replacing an incident commander or on-call engineer.
-   Guaranteeing a single definitive root cause from incomplete
    evidence.
-   Training a foundation model from scratch.
-   Supporting every log vendor or observability provider from day one.

------------------------------------------------------------------------

## 2. Users and Core Use Cases

### Primary users

-   On-call software engineers
-   Site reliability engineers (SREs)
-   Backend/platform engineers
-   Engineering teams reviewing past incidents

### Core use cases

1.  Upload or register runbooks, service docs, postmortems, and log
    files.
2.  Search the indexed knowledge base using natural-language questions.
3.  Submit an incident summary and receive ranked evidence and likely
    causes.
4.  Inspect citations and supporting excerpts for every material claim.
5.  Compare retrieval or model configurations on a fixed evaluation set.
6.  Inspect operational metrics and request traces.
7.  Compare model routing policies on cost, latency, and quality.
8.  Re-run failed or low-quality investigations after improving the
    system.

------------------------------------------------------------------------

## 3. Functional Requirements

### FR-01: Knowledge ingestion

-   Accept Markdown, plain text, PDF, and JSONL files.
-   Validate file type and size.
-   Extract text and metadata.
-   Split documents into overlapping chunks.
-   Attach metadata: document ID, source name, source type, service,
    environment, timestamp, and chunk index.
-   Generate embeddings, persist chunk text and metadata in NeonDB, and upsert vectors into Pinecone.
-   Track ingestion status: `queued`, `processing`, `completed`, or
    `failed`.
-   Make ingestion idempotent when the same document/version is
    submitted again.
-   Record errors without exposing secrets or raw sensitive content in
    logs.

### FR-02: Retrieval

-   Support semantic vector search.
-   Support PostgreSQL full-text keyword search.
-   Combine result sets using Reciprocal Rank Fusion (RRF) or another
    documented fusion method.
-   Apply metadata filters such as service, environment, source type,
    and date range.
-   Optionally rerank the candidate set with a cross-encoder.
-   Return scores, source metadata, and excerpts.
-   Never claim a document supports an answer if it was not actually
    retrieved.

### FR-03: Incident analysis

-   Accept an incident summary, symptoms, affected service, environment,
    severity, and optional log excerpts.
-   Retrieve relevant runbooks, service documentation, and prior
    incidents.
-   Generate a structured response with:
    -   incident summary
    -   ranked hypotheses
    -   supporting evidence
    -   contradictory or missing evidence
    -   confidence label and rationale
    -   safe diagnostic next steps
    -   citations
    -   explicit limitations
-   Use confidence labels such as `low`, `medium`, and `high`; these are
    model-assessed labels, not calibrated probabilities.
-   Return `insufficient_evidence` when retrieval or answer quality
    gates fail.
-   Never invent citations, source IDs, log entries, or completed
    actions.

### FR-04: Model gateway and routing

-   Expose a provider-neutral interface for chat and embedding models.
-   Configure at least two providers when credentials and model access
    are available.
-   Support a static default policy and a rule-based policy based on
    task type, context size, latency/cost budget, and provider health.
-   Apply timeouts, bounded retries, rate-limit handling, and
    circuit-breaker behavior.
-   Record the selected provider, model, policy, fallback reason,
    latency, token usage when available, and estimated cost.
-   Do not silently switch providers if the request's data-handling
    policy prohibits it.
-   Keep routing decisions deterministic and testable where possible.
-   Treat learned routing as a later experiment; compare it against
    static and rule-based baselines on a held-out dataset.

### FR-05: Evaluation

-   Maintain versioned test cases containing question/incident input,
    expected relevant documents, reference answer or expected facts, and
    labels.
-   Measure retrieval hit rate/recall@k, MRR, and nDCG where labels
    support them.
-   Measure answer correctness, groundedness/citation support,
    abstention behavior, schema validity, and latency/cost.
-   Store experiment metadata: dataset version, prompt version,
    embedding model, retrieval settings, reranker, LLM, routing policy,
    and timestamp.
-   Compare candidate runs to a baseline.
-   Allow CI to fail on defined quality regressions.
-   Keep a frozen holdout set separate from prompt and retrieval tuning.
-   Treat LLM-as-judge scores as noisy signals; validate judge behavior
    against human-labelled examples.

### FR-06: Observability

-   Emit structured logs with request and trace IDs.
-   Record duration for ingestion, retrieval, reranking, generation, and
    total request.
-   Record provider errors, retry counts, fallback events, token usage,
    and estimated cost when available.
-   Never log API keys, authorization headers, or unrestricted raw
    uploaded content.
-   Expose liveness and readiness endpoints.
-   Provide metrics suitable for Prometheus and dashboards in Grafana.
-   Support OpenTelemetry tracing and an optional Langfuse integration.

### FR-07: Security and reliability

-   Validate request bodies and uploaded files.
-   Enforce configurable upload limits and rate limits.
-   Use environment variables or a secrets manager for credentials.
-   Use parameterized database access through SQLAlchemy/SQLModel or a
    repository layer.
-   Apply authentication to non-public ingestion, evaluation, and
    operational endpoints before public deployment.
-   Enforce authorization at the API boundary.
-   Treat retrieved documents and log text as untrusted data; they may
    contain prompt-injection instructions.
-   Do not allow retrieved text to override system instructions or
    trigger tools.
-   Add bounded retries, timeouts, idempotency where needed, and
    graceful provider failure handling.
-   Use database migrations and automated tests.
-   Avoid storing secrets and unnecessary personal data in incident
    records.

------------------------------------------------------------------------

## 4. API Conventions

Base path: `/api/v1`

Content type: `application/json`, except file uploads which use
`multipart/form-data`.

### Common error response

``` json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "The request body is invalid.",
    "details": [
      {
        "field": "service",
        "message": "Field is required."
      }
    ],
    "request_id": "req_01J9EXAMPLE"
  }
}
```

Use appropriate HTTP status codes: - `200 OK`: successful read or
completed operation - `201 Created`: resource created - `202 Accepted`:
asynchronous ingestion/evaluation job accepted - `400 Bad Request`:
invalid request semantics - `401 Unauthorized`: missing/invalid
authentication - `403 Forbidden`: authenticated but not authorized -
`404 Not Found`: resource not found - `409 Conflict`:
duplicate/conflicting operation - `413 Payload Too Large`: upload
exceeds configured limit - `422 Unprocessable Entity`: schema validation
failure - `429 Too Many Requests`: rate limit exceeded -
`502 Bad Gateway`: upstream model/provider failure -
`503 Service Unavailable`: service/dependency unavailable -
`500 Internal Server Error`: unexpected server failure

All response examples below are illustrative contracts. Exact
timestamps, IDs, costs, and scores will be generated at runtime.

------------------------------------------------------------------------

## 5. API Endpoints

### 5.1 Health and service status

#### `GET /health/live`

Purpose: liveness probe; confirms the process is running without
checking every dependency.

**Example response --- `200 OK`**

``` json
{
  "status": "alive"
}
```

#### `GET /health/ready`

Purpose: readiness probe; checks required dependencies such as
PostgreSQL and configured queue infrastructure.

**Example response --- `200 OK`**

``` json
{
  "status": "ready",
  "dependencies": {
    "postgres": "ok",
    "redis": "ok"
  }
}
```

If a required dependency is unavailable, return
`503 Service Unavailable` with status `not_ready`. Optional providers
should not make the entire service unready.

#### `GET /api/v1/system/info`

Purpose: expose safe service/version information. Do not return secrets,
connection strings, or sensitive environment values.

**Example response**

``` json
{
  "service": "incidentiq",
  "version": "0.1.0",
  "api_version": "v1",
  "features": {
    "hybrid_search": true,
    "reranking": true,
    "model_routing": true,
    "evaluations": true
  }
}
```

### 5.2 Document ingestion

#### `POST /api/v1/documents`

Purpose: upload a supported file and create an ingestion job.

**Request:** `multipart/form-data`

Fields: - `file` (required): `.md`, `.txt`, `.pdf`, or `.jsonl` -
`service` (optional): e.g. `checkout` - `environment` (optional):
e.g. `production` - `source_type` (required): `runbook`, `postmortem`,
`service_doc`, `log`, or `other` - `metadata` (optional): JSON string
containing non-sensitive metadata

**Example response --- `202 Accepted`**

``` json
{
  "document_id": "doc_01J9ABCDEF",
  "job_id": "job_01J9ABCDEF",
  "filename": "checkout-db-runbook.md",
  "status": "queued",
  "message": "Document accepted for ingestion."
}
```

Validation requirements: - Reject unsupported extensions and mismatched
file content types. - Enforce a configurable size limit (initial
default: 10 MB). - Never trust the client-supplied filename as a
filesystem path. - Compute a content hash to support deduplication.

#### `GET /api/v1/documents`

Purpose: list documents with pagination and filters.

Query parameters: - `limit` (default `20`, max `100`) - `cursor`
(optional) - `service` (optional) - `source_type` (optional) - `status`
(optional)

**Example response**

``` json
{
  "items": [
    {
      "document_id": "doc_01J9ABCDEF",
      "filename": "checkout-db-runbook.md",
      "source_type": "runbook",
      "service": "checkout",
      "environment": "production",
      "status": "completed",
      "chunk_count": 18,
      "created_at": "2026-10-14T12:00:00Z"
    }
  ],
  "next_cursor": null
}
```

#### `GET /api/v1/documents/{document_id}`

Purpose: fetch document metadata and ingestion status.

**Example response**

``` json
{
  "document_id": "doc_01J9ABCDEF",
  "filename": "checkout-db-runbook.md",
  "source_type": "runbook",
  "service": "checkout",
  "environment": "production",
  "status": "completed",
  "chunk_count": 18,
  "content_sha256": "9a7f...example",
  "error": null,
  "created_at": "2026-10-14T12:00:00Z",
  "updated_at": "2026-10-14T12:00:12Z"
}
```

#### `DELETE /api/v1/documents/{document_id}`

Purpose: delete document metadata and associated chunks in NeonDB, plus all corresponding vector IDs in Pinecone. Because deletion spans two systems, make it idempotent, track partial failures, and retry cleanup. This should be authenticated and authorized.

**Example response --- `200 OK`**

``` json
{
  "document_id": "doc_01J9ABCDEF",
  "deleted": true
}
```

#### `GET /api/v1/jobs/{job_id}`

Purpose: inspect asynchronous ingestion status.

**Example response**

``` json
{
  "job_id": "job_01J9ABCDEF",
  "job_type": "document_ingestion",
  "status": "completed",
  "progress": {
    "stage": "indexing",
    "completed_units": 18,
    "total_units": 18
  },
  "error": null,
  "created_at": "2026-10-14T12:00:00Z",
  "finished_at": "2026-10-14T12:00:12Z"
}
```

Statuses: `queued`, `processing`, `completed`, `failed`.

### 5.3 Search and retrieval

#### `POST /api/v1/search`

Purpose: retrieve relevant chunks without generating an answer. This
endpoint is important for debugging retrieval quality.

**Example request**

``` json
{
  "query": "Why are checkout database connections timing out after deployment?",
  "top_k": 8,
  "filters": {
    "service": "checkout",
    "environment": "production",
    "source_types": ["runbook", "postmortem"]
  },
  "use_hybrid_search": true,
  "use_reranker": true
}
```

Input fields: - `query` (required, 1--4000 characters) - `top_k`
(optional, default `8`, max `50`) - `filters` (optional): `service`,
`environment`, `source_types`, `created_after`, `created_before` -
`use_hybrid_search` (optional, default `true`) - `use_reranker`
(optional, default `true`)

**Example response**

``` json
{
  "query": "Why are checkout database connections timing out after deployment?",
  "results": [
    {
      "chunk_id": "chk_01J9XYZ",
      "document_id": "doc_01J9ABCDEF",
      "source": "checkout-db-runbook.md",
      "source_type": "runbook",
      "service": "checkout",
      "excerpt": "If connection acquisition timeouts rise after a deployment, inspect pool saturation and connection leaks.",
      "score": 0.91,
      "rank": 1
    }
  ],
  "retrieval": {
    "mode": "hybrid",
    "reranker_used": true,
    "candidate_count": 24
  },
  "latency_ms": 184
}
```

Scores are implementation-specific ranking values, not probabilities. Do
not compare scores across unrelated models unless calibrated.

### 5.4 Incident investigation

#### `POST /api/v1/incidents/analyze`

Purpose: analyze an incident using retrieved evidence and an LLM.

**Example request**

``` json
{
  "title": "Checkout API returns 500 errors",
  "description": "After release 2026.10.14.2, checkout requests started failing.",
  "service": "checkout",
  "environment": "production",
  "severity": "SEV-2",
  "symptoms": [
    "HTTP 500 rate increased",
    "Database connection acquisition timeout",
    "p95 latency increased from 250 ms to 2400 ms"
  ],
  "log_excerpt": "TimeoutError: connection acquisition exceeded 5 seconds",
  "time_window": {
    "start": "2026-10-14T10:00:00Z",
    "end": "2026-10-14T10:30:00Z"
  },
  "options": {
    "top_k": 8,
    "include_diagnostic_steps": true,
    "max_output_tokens": 1500
  }
}
```

Input fields: - `title` (required) - `description` (required) -
`service` (required) - `environment` (required) - `severity` (required):
`SEV-1`, `SEV-2`, `SEV-3`, `SEV-4`, or `unknown` - `symptoms` (optional
list of strings) - `log_excerpt` (optional; length-limited and treated
as untrusted input) - `time_window` (optional start/end ISO-8601
timestamps) - `options` (optional configuration bounded by server
policy)

**Example response**

``` json
{
  "incident_id": "inc_01J9INCIDENT",
  "status": "completed",
  "summary": "Checkout failures began after a deployment and coincide with database connection acquisition timeouts.",
  "hypotheses": [
    {
      "rank": 1,
      "title": "Database connection pool saturation",
      "confidence": "medium",
      "reasoning": "The timeout message and elevated latency are consistent with connection pool saturation. The retrieved runbook describes this failure pattern.",
      "supporting_evidence": [
        {
          "document_id": "doc_01J9ABCDEF",
          "chunk_id": "chk_01J9XYZ",
          "source": "checkout-db-runbook.md",
          "quote": "inspect pool saturation and connection leaks"
        }
      ],
      "missing_evidence": [
        "Connection pool utilization metrics for the incident window",
        "Comparison of pool settings before and after the release"
      ]
    }
  ],
  "diagnostic_steps": [
    {
      "step": 1,
      "action": "Inspect database pool utilization and connection acquisition latency.",
      "reason": "This can confirm or weaken the leading hypothesis.",
      "risk": "read_only"
    },
    {
      "step": 2,
      "action": "Compare connection-pool configuration between the previous and current release.",
      "reason": "A configuration change may explain the timing.",
      "risk": "read_only"
    }
  ],
  "citations": [
    {
      "document_id": "doc_01J9ABCDEF",
      "chunk_id": "chk_01J9XYZ",
      "source": "checkout-db-runbook.md"
    }
  ],
  "limitations": [
    "The available evidence does not prove the root cause."
  ],
  "quality": {
    "result": "evidence_found",
    "abstained": false
  },
  "run": {
    "run_id": "run_01J9RUN",
    "provider": "configured-provider",
    "model": "configured-model",
    "routing_policy": "balanced",
    "latency_ms": 1320,
    "input_tokens": 2100,
    "output_tokens": 620,
    "estimated_cost_usd": 0.004
  }
}
```

Implementation requirements: - Persist the incident and investigation
run. - Validate citation IDs against the retrieved evidence set. - Never
represent a hypothesis as a confirmed root cause unless the system has
explicit supporting verification. - Return
`quality.result = "insufficient_evidence"` and `abstained = true` if
evidence is inadequate. - Keep provider/model/cost fields nullable if
the provider does not expose them. - Treat the example's cost and
metrics as illustrative only.

#### `GET /api/v1/incidents`

Purpose: list incident investigations.

Query parameters: - `limit` (default `20`, max `100`) - `cursor`
(optional) - `service` (optional) - `severity` (optional) - `status`
(optional)

**Example response**

``` json
{
  "items": [
    {
      "incident_id": "inc_01J9INCIDENT",
      "title": "Checkout API returns 500 errors",
      "service": "checkout",
      "environment": "production",
      "severity": "SEV-2",
      "status": "completed",
      "created_at": "2026-10-14T10:35:00Z"
    }
  ],
  "next_cursor": null
}
```

#### `GET /api/v1/incidents/{incident_id}`

Purpose: fetch the incident, latest analysis summary, and status.

**Example response**

``` json
{
  "incident_id": "inc_01J9INCIDENT",
  "title": "Checkout API returns 500 errors",
  "service": "checkout",
  "environment": "production",
  "severity": "SEV-2",
  "status": "completed",
  "latest_run_id": "run_01J9RUN",
  "created_at": "2026-10-14T10:35:00Z"
}
```

#### `GET /api/v1/incidents/{incident_id}/runs`

Purpose: list analysis runs for an incident to support comparisons and
auditing.

**Example response**

``` json
{
  "incident_id": "inc_01J9INCIDENT",
  "items": [
    {
      "run_id": "run_01J9RUN",
      "status": "completed",
      "prompt_version": "incident-analysis-v1",
      "retrieval_config_version": "hybrid-v1",
      "routing_policy": "balanced",
      "created_at": "2026-10-14T10:35:10Z"
    }
  ]
}
```

#### `GET /api/v1/runs/{run_id}`

Purpose: inspect a single analysis run and its metadata.

**Example response**

``` json
{
  "run_id": "run_01J9RUN",
  "incident_id": "inc_01J9INCIDENT",
  "status": "completed",
  "provider": "configured-provider",
  "model": "configured-model",
  "prompt_version": "incident-analysis-v1",
  "retrieval_config_version": "hybrid-v1",
  "routing_policy": "balanced",
  "latency_ms": 1320,
  "input_tokens": 2100,
  "output_tokens": 620,
  "estimated_cost_usd": 0.004,
  "error_code": null
}
```

### 5.5 Model routing and configuration

#### `GET /api/v1/routing/policies`

Purpose: list supported routing policies.

**Example response**

``` json
{
  "policies": [
    {
      "name": "static",
      "description": "Use the configured default model."
    },
    {
      "name": "rule_based",
      "description": "Choose from configured models using task, budget, latency, and provider health."
    },
    {
      "name": "quality_first",
      "description": "Prefer the highest-quality eligible configured model within policy constraints."
    }
  ],
  "active_policy": "rule_based"
}
```

#### `GET /api/v1/routing/decisions/{run_id}`

Purpose: explain the routing decision for a run.

**Example response**

``` json
{
  "run_id": "run_01J9RUN",
  "policy": "rule_based",
  "selected_provider": "provider-a",
  "selected_model": "model-a",
  "reason_codes": [
    "provider_healthy",
    "within_latency_budget",
    "eligible_for_task"
  ],
  "fallback_used": false
}
```

#### `POST /api/v1/routing/simulate`

Purpose: compare candidate routing decisions without executing the model
request.

**Example request**

``` json
{
  "task_type": "incident_analysis",
  "input_tokens_estimate": 2200,
  "output_tokens_budget": 1200,
  "max_latency_ms": 3000,
  "max_cost_usd": 0.02,
  "policy": "rule_based"
}
```

**Example response**

``` json
{
  "policy": "rule_based",
  "eligible_models": [
    {
      "provider": "provider-a",
      "model": "model-a",
      "estimated_cost_usd": 0.004,
      "estimated_latency_ms": 1400
    }
  ],
  "selected": {
    "provider": "provider-a",
    "model": "model-a"
  },
  "excluded": []
}
```

Estimates are based on configured price/latency data and should be
marked stale or unavailable when the data is missing. Do not pretend
estimates are live provider quotes.

### 5.6 Evaluation and experiments

#### `POST /api/v1/evaluations`

Purpose: start an evaluation job for a dataset and configuration.

**Example request**

``` json
{
  "dataset_id": "ds_incidents_v1",
  "split": "validation",
  "experiment_name": "hybrid-reranker-v2",
  "config": {
    "retrieval_mode": "hybrid",
    "top_k": 8,
    "reranker": "configured-reranker",
    "prompt_version": "incident-analysis-v2",
    "routing_policy": "rule_based"
  },
  "baseline_run_id": "evalrun_baseline_001"
}
```

**Example response --- `202 Accepted`**

``` json
{
  "evaluation_run_id": "evalrun_01J9EVAL",
  "status": "queued",
  "dataset_id": "ds_incidents_v1",
  "split": "validation"
}
```

#### `GET /api/v1/evaluations/{evaluation_run_id}`

Purpose: inspect evaluation progress and metrics.

**Example response**

``` json
{
  "evaluation_run_id": "evalrun_01J9EVAL",
  "status": "completed",
  "dataset_id": "ds_incidents_v1",
  "split": "validation",
  "metrics": {
    "recall_at_5": 0.84,
    "mrr": 0.72,
    "citation_support_rate": 0.91,
    "schema_valid_rate": 0.99,
    "abstention_precision": 0.88,
    "p95_latency_ms": 2100,
    "estimated_cost_per_case_usd": 0.006
  },
  "baseline_comparison": {
    "recall_at_5_delta": 0.07,
    "citation_support_rate_delta": 0.04
  },
  "dataset_version": "1.0.0",
  "config_hash": "cfg_4e91..."
}
```

These metric values are examples only, not promised results.

#### `GET /api/v1/evaluations`

Purpose: list evaluation runs.

Query parameters: - `dataset_id` (optional) - `status` (optional) -
`limit` (default `20`, max `100`)

**Example response**

``` json
{
  "items": [
    {
      "evaluation_run_id": "evalrun_01J9EVAL",
      "experiment_name": "hybrid-reranker-v2",
      "dataset_id": "ds_incidents_v1",
      "status": "completed",
      "created_at": "2026-10-14T14:00:00Z"
    }
  ]
}
```

#### `GET /api/v1/evaluations/{evaluation_run_id}/cases`

Purpose: inspect per-case evaluation results and failures.

**Example response**

``` json
{
  "evaluation_run_id": "evalrun_01J9EVAL",
  "items": [
    {
      "case_id": "case_0042",
      "passed": false,
      "failure_categories": [
        "missing_citation",
        "incorrect_top_hypothesis"
      ],
      "expected_document_ids": ["doc_01J9ABCDEF"],
      "retrieved_document_ids": ["doc_01J9OTHER"],
      "notes": "Relevant runbook was not present in the top five results."
    }
  ]
}
```

### 5.7 Operational metrics

#### `GET /api/v1/metrics/summary`

Purpose: return a compact, authenticated operational summary for a
dashboard.

Query parameters: - `window`: `1h`, `24h`, or `7d` (default `24h`)

**Example response**

``` json
{
  "window": "24h",
  "requests": {
    "total": 842,
    "success_rate": 0.982,
    "error_rate": 0.018
  },
  "latency_ms": {
    "p50": 980,
    "p95": 2450,
    "p99": 4100
  },
  "llm": {
    "input_tokens": 1520000,
    "output_tokens": 410000,
    "estimated_cost_usd": 12.45,
    "fallback_count": 7
  },
  "retrieval": {
    "average_candidates": 19.2,
    "reranker_usage_rate": 0.91
  }
}
```

Use aggregated data only. Do not expose unrestricted traces or incident
content from this endpoint.

------------------------------------------------------------------------

## 6. Architecture

### 6.1 High-level architecture diagram

``` mermaid
flowchart TD
    U[Engineer / API Client] --> API[FastAPI API Layer]
    API --> AUTH[Authentication and Request Validation]
    AUTH --> APP[Application Services]

    APP --> ING[Ingestion Service]
    ING --> Q[Redis Queue]
    Q --> WORKER[Ingestion Worker]
    WORKER --> PARSE[Parser and Chunker]
    PARSE --> EMB[Embedding Provider]
    EMB --> PC[(Pinecone Vector Index)]
    PARSE --> DB[(NeonDB PostgreSQL: chunks and metadata)]

    APP --> RET[Retrieval Service]
    RET --> FTS[NeonDB PostgreSQL Full-text Search]
    RET --> VEC[Pinecone Vector Search]
    VEC --> FETCH[Fetch chunk text and metadata from NeonDB]
    FETCH --> FUSE[Rank Fusion]
    FTS --> FUSE
    FUSE --> RERANK[Optional Reranker]
    RERANK --> CTX[Evidence Context]

    APP --> ANALYZE[Incident Analysis Service]
    CTX --> ANALYZE
    ANALYZE --> ROUTER[LLM Gateway and Router]
    ROUTER --> LLM1[Provider A]
    ROUTER --> LLM2[Provider B]
    ANALYZE --> DB

    APP --> EVAL[Evaluation Service]
    EVAL --> DATASET[(Versioned Evaluation Dataset)]
    EVAL --> METRICS[Evaluation Metrics and Baselines]

    API --> OBS[OpenTelemetry / Structured Logs]
    ING --> OBS
    RET --> OBS
    ROUTER --> OBS
    ANALYZE --> OBS
    OBS --> LF[Langfuse]
    OBS --> PROM[Prometheus / Grafana]
```

### 6.2 Main components

-   **FastAPI layer:** request validation, auth dependencies, response
    schemas, status codes.
-   **Application services:** orchestrate ingestion, search, analysis,
    evaluation, and routing.
-   **Ingestion worker:** parses, chunks, embeds, and indexes documents
    outside the request lifecycle.
-   **NeonDB PostgreSQL:** stores document metadata, chunk text, incidents, analysis runs, jobs, evaluation data, and PostgreSQL full-text search vectors.
-   **Pinecone:** stores embedding vectors and searchable chunk metadata for semantic retrieval; vector IDs map back to chunk IDs in NeonDB.
-   **Retrieval service:** keyword search, vector search, fusion,
    filters, and optional reranking.
-   **LLM gateway:** provider-neutral calls, routing, timeouts, retries,
    fallback, and usage metadata.
-   **Evaluation service:** runs datasets and compares metrics to
    baselines.
-   **Observability:** logs, traces, metrics, cost, latency, and errors.

### 6.3 Request flow: incident analysis

1.  Client sends `POST /api/v1/incidents/analyze`.
2.  FastAPI validates the payload and enforces authentication/rate
    limits.
3.  The service creates an incident record and a trace/request ID.
4.  The retrieval service embeds the query and performs semantic search in Pinecone plus keyword search in NeonDB PostgreSQL.
5.  Pinecone returns matching vector IDs and scores; the service fetches canonical chunk text and metadata from NeonDB.
6.  Results are fused, filtered, and optionally reranked.
7.  A quality gate checks whether enough relevant evidence is available.
8.  If evidence is inadequate, return an explicit abstention rather than
    fabricating a diagnosis.
9.  Otherwise, the LLM gateway selects an eligible model under the
    active routing policy.
10. The analysis prompt contains the incident and retrieved evidence,
    clearly marked as untrusted source material.
11. The model returns structured hypotheses, evidence references,
    missing evidence, and diagnostic steps.
12. The server validates the output schema and verifies that citation
    IDs belong to the retrieved result set.
13. The service persists the run, selected model, prompt/config
    versions, latency, usage, and result.
14. The API returns the structured analysis.
15. Traces and metrics are emitted without logging secrets or
    unrestricted raw content.

### 6.4 Request flow: document ingestion

1.  Client uploads a document.
2.  API checks authorization, size, extension, content type, and
    metadata.
3.  API computes a content hash and creates a document/job record.
4.  Worker extracts text and normalizes metadata.
5.  Text is split into chunks with configurable size and overlap.
6.  Worker generates embeddings in bounded batches.
7.  Worker stores canonical chunk text and metadata in NeonDB and upserts vectors into Pinecone with stable IDs derived from chunk IDs. These two systems do not share a transaction, so make ingestion idempotent and record/retry partial failures.
8.  Job status changes to `completed` only after both stores are updated; errors set status to `failed` with a safe error code.
9.  The client polls `GET /api/v1/jobs/{job_id}` or
    `GET /api/v1/documents/{document_id}`.

------------------------------------------------------------------------

## 7. Recommended Tech Stack

Use a small, coherent stack. Add optional infrastructure only when the
corresponding feature works end-to-end.

  -----------------------------------------------------------------------
  Area                    Recommended technology  Reason
  ----------------------- ----------------------- -----------------------
  Language                Python 3.12+            Broad AI/ML ecosystem

  Project and dependency  `uv`                    Fast environment and
  manager                                         lockfile management

  API                     FastAPI                 Typed REST API and
                                                  OpenAPI docs

  Validation/settings     Pydantic v2,            Request schemas and
                          pydantic-settings       environment
                                                  configuration

  Database                NeonDB (PostgreSQL)     Managed PostgreSQL
                                                  database; avoid running
                                                  a local PostgreSQL server

  Vector search           Pinecone                Managed vector index;
                                                  keep vectors separate
                                                  from relational records

  Database layer          SQLAlchemy 2.x +        Async-capable ORM and
                          Alembic                 migrations

  PostgreSQL driver       psycopg 3               Use SQLAlchemy with the
                                                  psycopg driver; configure
                                                  connection pooling

  PDF parsing             PyMuPDF                 Text extraction from
                                                  PDFs

  Markdown/text           Standard library and    Lightweight document
                          Markdown parser         ingestion

  Embeddings              Sentence Transformers   Start with one
                          or a hosted embedding   provider; benchmark
                          API                     before changing

  Reranking               Cross-encoder from      Improve ranking of
                          Sentence Transformers   retrieved candidates

  Keyword retrieval       NeonDB PostgreSQL       Keep keyword search in
                          full-text search         the relational database

  LLM access              LiteLLM                 Unified provider
                                                  interface, routing, and
                                                  usage metadata

  LLM providers           Gemini and/or Groq,     Provider diversity;
                          plus a second eligible  availability depends on
                          provider                current model access

  Background jobs         Redis + ARQ             Python-native async job
                                                  queue

  Testing                 pytest, pytest-asyncio, Unit, async, and API
                          HTTPX                   tests

  Evaluation              Custom evaluation       Explicit reproducible
                          harness; optionally     metrics
                          RAGAS                   

  Tracing                 OpenTelemetry +         End-to-end request and
                          optional Langfuse       LLM tracing

  Metrics                 Prometheus + Grafana    Operational dashboards

  Logging                 structlog or standard   Correlated JSON logs
                          structured logging      

  Retry/circuit breaker   Tenacity plus a small   Bounded retries and
                          explicit                predictable failure
                          circuit-breaker         handling
                          implementation          

  Rate limiting           SlowAPI or a            API protection
                          Redis-backed limiter    

  Auth                    JWT/OAuth2 or an        Protect ingestion and
                          API-key scheme for      operational routes
                          initial private         
                          deployment              

  Packaging               Docker + Docker Compose Run Redis locally; NeonDB
                                                  hosts PostgreSQL

  CI/CD                   GitHub Actions          Lint, test, evaluation
                                                  gates, and image build

  Lint/format             Ruff                    Fast Python linting and
                                                  formatting

  Type checking           Pyright or mypy         Catch interface errors
                                                  early
  -----------------------------------------------------------------------

### Recommended initial choices

-   Use Pinecone for semantic vector search and NeonDB PostgreSQL full-text search for keyword retrieval; combine results with rank fusion. Do not add Elasticsearch for the MVP.
-   Use Redis + ARQ for ingestion jobs. Do not add Kafka or Kubernetes
    for a portfolio MVP.
-   Use LiteLLM behind your own `LLMGateway` interface so provider
    details do not leak through application services.
-   Use one embedding model first. Evaluate quality and latency before
    adding a second.
-   Keep the first release as a modular monolith with a separate
    background worker process, not a fleet of microservices.
-   Use NeonDB for PostgreSQL rather than running PostgreSQL locally. Keep
    the connection string in environment configuration, use TLS, and keep
    application and migration connection settings separately configurable.

------------------------------------------------------------------------

## 8. Project Folder Structure

``` text
incidentiq/
├── pyproject.toml
├── uv.lock
├── .python-version
├── .env.example
├── .gitignore
├── README.md
├── Dockerfile
├── compose.yaml
├── alembic.ini
├── Makefile
├── docs/
│   ├── architecture.md
│   ├── api-examples.md
│   ├── evaluation.md
│   ├── security.md
│   └── runbooks/
│       ├── provider-failure.md
│       └── ingestion-failure.md
├── migrations/
│   ├── env.py
│   └── versions/
├── datasets/
│   ├── README.md
│   ├── development/
│   ├── validation/
│   └── holdout/
├── scripts/
│   ├── seed_demo_data.py
│   ├── run_evaluation.py
│   └── benchmark_routing.py
├── src/
│   └── incidentiq/
│       ├── __init__.py
│       ├── main.py
│       ├── config.py
│       ├── logging.py
│       ├── api/
│       │   ├── dependencies.py
│       │   ├── errors.py
│       │   └── v1/
│       │       ├── router.py
│       │       └── endpoints/
│       │           ├── health.py
│       │           ├── documents.py
│       │           ├── jobs.py
│       │           ├── search.py
│       │           ├── incidents.py
│       │           ├── runs.py
│       │           ├── routing.py
│       │           ├── evaluations.py
│       │           └── metrics.py
│       ├── schemas/
│       │   ├── common.py
│       │   ├── documents.py
│       │   ├── search.py
│       │   ├── incidents.py
│       │   ├── routing.py
│       │   └── evaluations.py
│       ├── models/
│       │   ├── document.py
│       │   ├── chunk.py
│       │   ├── incident.py
│       │   ├── analysis_run.py
│       │   ├── job.py
│       │   └── evaluation.py
│       ├── db/
│       │   ├── session.py
│       │   └── repositories/
│       ├── services/
│       │   ├── ingestion.py
│       │   ├── retrieval.py
│       │   ├── incident_analysis.py
│       │   ├── citation_validation.py
│       │   ├── evaluations.py
│       │   ├── metrics.py
│       │   └── jobs.py
│       ├── ingestion/
│       │   ├── parsers.py
│       │   ├── chunking.py
│       │   └── pipeline.py
│       ├── retrieval/
│       │   ├── embeddings.py
│       │   ├── vector_search.py
│       │   ├── keyword_search.py
│       │   ├── fusion.py
│       │   └── reranking.py
│       ├── llm/
│       │   ├── gateway.py
│       │   ├── providers.py
│       │   ├── routing.py
│       │   ├── prompts/
│       │   │   └── incident_analysis_v1.md
│       │   └── schemas.py
│       ├── workers/
│       │   ├── queue.py
│       │   └── ingestion_worker.py
│       ├── evaluation/
│       │   ├── dataset.py
│       │   ├── retrieval_metrics.py
│       │   ├── answer_metrics.py
│       │   ├── judge.py
│       │   └── regression.py
│       └── observability/
│           ├── tracing.py
│           └── metrics.py
└── tests/
    ├── conftest.py
    ├── unit/
    │   ├── test_chunking.py
    │   ├── test_fusion.py
    │   ├── test_citation_validation.py
    │   └── test_routing.py
    ├── integration/
    │   ├── test_ingestion_pipeline.py
    │   ├── test_retrieval.py
    │   └── test_provider_fallback.py
    ├── api/
    │   ├── test_health.py
    │   ├── test_documents.py
    │   ├── test_search.py
    │   └── test_incidents.py
    └── evaluation/
        └── test_quality_regression.py
```

Keep this structure as the target layout. Create modules as you
implement them rather than generating empty files for every component at
the beginning.

------------------------------------------------------------------------

## 9. Data Model Requirements

Minimum entities:

### `documents`

-   `id` (UUID or prefixed ID)
-   `filename`
-   `source_type`
-   `service`
-   `environment`
-   `content_sha256`
-   `status`
-   `metadata` (JSONB)
-   `created_at`, `updated_at`

### `document_chunks`

-   `id`
-   `document_id` (foreign key)
-   `chunk_index`
-   `content`
-   `pinecone_vector_id` (stable ID used to locate the vector in Pinecone)
-   `search_vector` (PostgreSQL full-text search vector, if used)
-   `metadata` (JSONB)
-   `created_at`

### `incidents`

-   `id`
-   `title`
-   `description`
-   `service`
-   `environment`
-   `severity`
-   `status`
-   `created_at`, `updated_at`

### `analysis_runs`

-   `id`
-   `incident_id`
-   `status`
-   `prompt_version`
-   `retrieval_config_version`
-   `routing_policy`
-   `provider`, `model`
-   `input_tokens`, `output_tokens`
-   `latency_ms`
-   `estimated_cost_usd`
-   `result` (JSONB)
-   `error_code`
-   `created_at`, `finished_at`

### `jobs`

-   `id`
-   `job_type`
-   `status`
-   `progress` (JSONB)
-   `error_code`
-   `created_at`, `finished_at`

### `evaluation_runs`

-   `id`
-   `dataset_id`
-   `dataset_version`
-   `experiment_name`
-   `config` (JSONB)
-   `metrics` (JSONB)
-   `baseline_run_id`
-   `status`
-   `created_at`, `finished_at`

Use foreign keys and indexes for common relational filters. Configure the Pinecone index dimension and similarity metric to match the chosen embedding model. Use migrations for NeonDB schema changes; manage Pinecone index configuration separately. Keep chunk IDs stable so Pinecone results can be resolved to canonical chunk records in NeonDB.

------------------------------------------------------------------------

## 10. Project Setup Using `uv`

### 10.1 Prerequisites

Install: - Python 3.12 or a compatible version supported by selected
dependencies - `uv` - Docker Engine and Docker Compose plugin (for Redis) - Git - a NeonDB project with a PostgreSQL database

Check versions:

``` bash
python --version
uv --version
docker --version
docker compose version
```

Install `uv` using the official instructions at
https://docs.astral.sh/uv/getting-started/installation/ rather than
copying an unverified installation command.

### 10.2 Create the project

``` bash
mkdir incidentiq
cd incidentiq

uv init --package
uv python pin 3.12
```

Add runtime dependencies:

``` bash
uv add fastapi "uvicorn[standard]" pydantic pydantic-settings
uv add sqlalchemy alembic "psycopg[binary,pool]" pinecone
uv add pymupdf python-multipart
uv add litellm tenacity
uv add redis arq
uv add sentence-transformers
uv add structlog prometheus-client opentelemetry-api opentelemetry-sdk
```

Add development dependencies:

``` bash
uv add --dev pytest pytest-asyncio httpx ruff pyright
```

Notes: - `sentence-transformers` may install large ML dependencies. If
local memory or disk is limited, begin with a hosted embedding API and
add local embeddings after the baseline works. - Choose either
synchronous SQLAlchemy or SQLAlchemy's async interface deliberately. Do
not mix database session styles in the same repository layer without a
clear reason. - If the selected provider SDK or LiteLLM model identifier
changes, update configuration and test the provider adapter. - Commit
`uv.lock` so local development and CI use reproducible dependency
versions.

### 10.3 Configure environment variables

Create `.env.example`:

``` dotenv
APP_NAME=IncidentIQ
APP_ENV=development
LOG_LEVEL=INFO
API_V1_PREFIX=/api/v1

# Use the Neon connection string. Convert the scheme to
# postgresql+psycopg:// for SQLAlchemy if Neon supplies postgresql://.
# Prefer Neon pooled connection for application traffic.
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@YOUR-NEON-HOST/DBNAME?sslmode=require
# Optional separate direct URL for Alembic migrations, if needed.
DIRECT_DATABASE_URL=postgresql+psycopg://USER:PASSWORD@YOUR-DIRECT-NEON-HOST/DBNAME?sslmode=require
REDIS_URL=redis://localhost:6379/0

# Groq is primary for chat; Gemini is fallback chat and the only embedder.
# Choose models available under the account's free API tier.
GEMINI_API_KEY=
GROQ_API_KEY=
GROQ_CHAT_MODEL=
GEMINI_CHAT_MODEL=
GEMINI_EMBEDDING_MODEL=gemini-embedding-001
EMBEDDING_DIMENSION=768
PINECONE_API_KEY=
PINECONE_INDEX=incidentiq-vectors
PINECONE_NAMESPACE=incidentiq-dev
ROUTING_POLICY=static
CHAT_TIMEOUT_SECONDS=20
CHAT_MAX_ATTEMPTS=2
INGESTION_JOB_MAX_ATTEMPTS=3

MAX_UPLOAD_MB=10
CHUNK_SIZE=800
CHUNK_OVERLAP=120
DEFAULT_TOP_K=8
MAX_TOP_K=50

OTEL_SERVICE_NAME=incidentiq
OTEL_EXPORTER_OTLP_ENDPOINT=
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
LANGFUSE_HOST=

# Set a strong random value before exposing the service.
API_KEY=
```

Copy it locally:

``` bash
cp .env.example .env
```

Populate only the credentials for the providers you have access to.
Ensure `.env` is ignored by Git. In production, use the hosting
platform's secret manager.

### 10.4 Local infrastructure with Docker Compose

NeonDB provides the PostgreSQL database, so do not run a local
PostgreSQL container. Use Docker Compose only for Redis during local
development. Create `compose.yaml`:

``` yaml
services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - incidentiq_redisdata:/data
    command: ["redis-server", "--appendonly", "yes"]
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 10

volumes:
  incidentiq_redisdata:
```

Start Redis:

``` bash
docker compose up -d
docker compose ps
```

In the Neon Console, copy the connection string for your project and
store it in `.env` as `DATABASE_URL`. Use the pooled connection string
for application traffic where appropriate. Keep a direct connection URL
in `DIRECT_DATABASE_URL` for Alembic migrations if your Neon setup or
migration workflow requires it. Both URLs must use TLS (`sslmode=require`)
and the SQLAlchemy-compatible `postgresql+psycopg://` scheme. Never commit
real credentials.

Create a Pinecone index in the Pinecone console (or via a controlled setup script) with a dimension matching the selected embedding model and a compatible similarity metric. Configure `PINECONE_API_KEY`, `PINECONE_INDEX`, and `PINECONE_NAMESPACE` in `.env`. No `pgvector` extension is required in NeonDB. Store chunk text and canonical metadata in NeonDB; store embeddings and retrieval metadata in Pinecone. Keep metadata payloads small and include the NeonDB `chunk_id` and `document_id` so retrieval can fetch authoritative content from PostgreSQL.

### 10.5 Initialize migrations and database

After implementing the SQLAlchemy models and Alembic configuration,
configure Alembic to read `DIRECT_DATABASE_URL` when it is set, otherwise
fall back to `DATABASE_URL`. Run migrations against the Neon database:

``` bash
uv run alembic upgrade head
```

If creating a new migration after model changes:

``` bash
uv run alembic revision --autogenerate -m "add initial incidentiq schema"
uv run alembic upgrade head
```

Review autogenerated migrations before applying them. Never blindly
accept a migration that drops or alters data unexpectedly.

### 10.6 Run the API

With `src/incidentiq/main.py` exposing `app`:

``` bash
uv run uvicorn incidentiq.main:app --reload --host 127.0.0.1 --port 8000
```

If package discovery needs configuration, ensure `pyproject.toml`
declares the `src` package layout and that `uv init --package` has
created the corresponding build configuration.

Open: - Swagger UI: http://127.0.0.1:8000/docs - ReDoc:
http://127.0.0.1:8000/redoc - Liveness:
http://127.0.0.1:8000/health/live - Readiness:
http://127.0.0.1:8000/health/ready

### 10.7 Run the background worker

Implement the ARQ worker settings in `incidentiq/workers/queue.py`, then
run the worker using the import path configured for the ARQ version
selected by the project. For example, if `WorkerSettings` is defined in
that module:

``` bash
uv run arq incidentiq.workers.queue.WorkerSettings
```

Confirm the exact CLI syntax against the installed ARQ version during
implementation.

### 10.8 Run tests and quality checks

``` bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest
```

Run the evaluation harness after the core ingestion and retrieval
pipeline is implemented:

``` bash
uv run python scripts/run_evaluation.py --dataset datasets/validation
```

The script's CLI options should be implemented and documented in
`scripts/run_evaluation.py`.

### 10.9 Stop local infrastructure

Stop the local Redis container with:

``` bash
docker compose down
```

To delete the local Redis volume as well (destructive; does not delete your Neon database):

``` bash
docker compose down -v
```

------------------------------------------------------------------------

## 11. Implementation Phases

### Phase 1 --- Working API skeleton

-   Initialize the `uv` project and package layout.
-   Add settings, structured logging, error handling, and health
    endpoints.
-   Configure NeonDB PostgreSQL and set up SQLAlchemy and Alembic. Configure Pinecone credentials and the vector index during the retrieval phase.
-   Add initial CI checks and tests.

**Exit criteria:** app starts locally, database migrations run, health
endpoints pass, and CI is green.

### Phase 2 --- Ingestion and retrieval

-   Parse Markdown, text, PDF, and JSONL.
-   Implement chunking and metadata.
-   Store canonical chunks and metadata in NeonDB; store their embeddings in Pinecone.
-   Implement Pinecone vector search and NeonDB PostgreSQL full-text search, then fuse the ranked results.
-   Add rank fusion and optional reranking.
-   Add ingestion jobs and status endpoints.

**Exit criteria:** a user can ingest a sample runbook and retrieve
relevant passages with source metadata.

### Phase 3 --- Grounded incident analysis

-   Define Pydantic output schemas.
-   Implement provider adapters and the LLM gateway.
-   Build the incident analysis prompt.
-   Validate citations against retrieved chunks.
-   Implement evidence thresholds and abstention.
-   Persist incident and analysis-run records.

**Exit criteria:** a known test incident produces structured hypotheses
with valid citations, and an evidence-poor case abstains.

### Phase 4 --- Evaluation

-   Create a labeled dataset and documented labeling rules.
-   Implement retrieval and answer metrics.
-   Track prompt/model/retrieval configuration versions.
-   Save baseline runs and per-case failures.
-   Add a CI regression gate.

**Exit criteria:** a command reproducibly compares a candidate
configuration with a baseline and reports per-case failures.

### Phase 5 --- LLMOps and routing

-   Add provider health state, timeouts, bounded retries, and fallback.
-   Add static and rule-based routing policies.
-   Capture usage, cost estimates, and latency.
-   Add OpenTelemetry and dashboards.
-   Add failure-injection tests.

**Exit criteria:** provider failure is handled predictably, and a trace
explains each routing/fallback decision.

### Phase 6 --- Production readiness

-   Add authentication and authorization.
-   Add rate limiting and upload protection.
-   Add Docker image and CI pipeline.
-   Add deployment configuration, health checks, and runbooks.
-   Run load tests and review logs for sensitive data.
-   Document limitations and known failure modes.

**Exit criteria:** a public demo can be used safely with synthetic/demo
data, the API is documented, and all key quality metrics are
reproducible.

------------------------------------------------------------------------

## 12. Acceptance Criteria

The initial release is considered complete when:

-   [ ] Supported documents can be ingested and their job status
    queried.
-   [ ] Duplicate content is handled idempotently.
-   [ ] Hybrid search returns ranked chunks with valid source metadata.
-   [ ] Incident analysis produces schema-valid hypotheses and
    diagnostic steps.
-   [ ] Every citation references a chunk actually retrieved for that
    run.
-   [ ] The system abstains on intentionally evidence-poor evaluation
    cases.
-   [ ] At least two providers can be configured, with tested failure
    handling.
-   [ ] Routing policy decisions are logged and explainable.
-   [ ] An evaluation dataset and baseline are versioned.
-   [ ] Retrieval, groundedness, abstention, latency, and cost metrics
    can be generated.
-   [ ] CI detects a deliberately introduced quality regression.
-   [ ] Health checks, structured logs, traces, and operational metrics
    work.
-   [ ] Authentication protects ingestion, deletion, evaluation, and
    operational endpoints.
-   [ ] Tests cover core unit logic, API validation, ingestion,
    retrieval, and provider failure.
-   [ ] Docker-based local setup is documented and reproducible.
-   [ ] No credentials or sensitive incident data are committed to the
    repository.

Do not set arbitrary quality targets before creating a baseline. After
labeling a representative dataset, set explicit thresholds based on
observed performance and product requirements.

------------------------------------------------------------------------

## 13. Security, Privacy, and Operational Constraints

-   Uploaded files and retrieved chunks are untrusted input.
-   Prompt injection inside a runbook or log must not alter system
    policy.
-   Incident logs can contain credentials, tokens, email addresses, and
    customer data. Provide redaction hooks and document data retention.
-   Do not send sensitive incident content to an external model provider
    unless the deployment's data policy permits it.
-   Restrict provider routing to approved providers for each data
    classification.
-   Keep authentication and authorization outside LLM-generated
    decisions.
-   Do not allow the model to run commands or mutate infrastructure in
    the initial version.
-   Limit request size, context size, output tokens, concurrency, and
    retries.
-   Use explicit timeouts for database and provider operations.
-   Use least-privilege database credentials in production.
-   Make deletion behavior clear for documents and chunks in NeonDB, vectors in Pinecone, and associated traces. Track and retry partial failures across both stores.
-   Do not expose Prometheus metrics, traces, debug routes, or system
    configuration publicly without access controls.
-   Mark estimated token costs and provider pricing as estimates when
    exact billing data is unavailable.

------------------------------------------------------------------------

## 14. Portfolio Deliverables

The GitHub repository should contain:

1.  A concise README with problem statement, architecture, local setup,
    screenshots, and demo URL.
2.  An architecture diagram and request-flow explanation.
3.  A deployed API with Swagger documentation.
4.  A small synthetic demo corpus of runbooks and incident postmortems.
5.  A versioned evaluation dataset with documented expected evidence.
6.  A baseline-vs-candidate evaluation report.
7.  Example traces showing retrieval, generation, model routing, and
    fallback.
8.  A cost/latency/quality comparison of at least two configurations.
9.  CI badges and automated tests.
10. A short demo video showing a successful investigation and an
    abstention case.
11. A security and limitations section.
12. One example of a failed evaluation, its root cause, and the fix.

The strongest portfolio evidence is reproducible measurement: show which
configuration changed, what metric improved or regressed, and the
trade-off in latency and cost. Do not claim production scale or accuracy
that you have not measured.

------------------------------------------------------------------------

## 15. Key Engineering Decisions

-   Start with a modular monolith plus a worker process.
-   Use NeonDB PostgreSQL for relational records and full-text search, and Pinecone for semantic vector search. Keep this two-store design explicit and implement retries/idempotency for cross-store consistency.
-   Keep prompts, model settings, and retrieval settings versioned.
-   Validate all model output and citations before returning them.
-   Prefer deterministic quality gates and business logic over
    unconstrained agent behavior.
-   Treat model routing as an experiment with baselines, not as a claim
    that a router is inherently better.
-   Build an end-to-end vertical slice early: ingest one runbook,
    retrieve it, analyze one incident, and evaluate the output.
-   Add complexity only when evaluation results justify it.
