# IncidentIQ --- Build Sequence for Codex

This sequence follows `requirement.md`. Build one phase at a time, test
it, and commit it before moving on. Do not implement the whole project
in one prompt.

## Ground rules

-   Treat `requirement.md` as the source of truth. If this file and the
    code disagree, flag the difference before making architectural
    changes.
-   Stack: Python 3.12+, `uv`, FastAPI, SQLAlchemy, Alembic, NeonDB
    PostgreSQL, Pinecone, Redis, and ARQ.
-   Store canonical documents/chunks and relational records in NeonDB.
    Store embeddings in Pinecone. Do not add `pgvector`.
-   Keep the first version as a decision-support tool: never execute
    production remediation commands.
-   Prefer small, readable implementations over abstractions that do not
    solve a current requirement.
-   For each phase: inspect the existing repo, implement only the phase,
    run relevant checks, fix failures, and summarize changed files and
    commands/results.
-   Do not invent successful test results. If a service or secret is
    unavailable, state what could not be tested and provide the exact
    next step.
-   Keep secrets in `.env`; commit only `.env.example` with
    placeholders.

## Phase 0 --- Inspect and plan

**Build** 1. Read `requirement.md` fully. 2. Inspect the repository,
existing code, configuration, and available tests. 3. Check which Codex
skills are actually installed and read their `SKILL.md` instructions
before using them. 4. Identify conflicts, missing requirements, and the
smallest useful implementation plan. 5. Create or update a concise
`IMPLEMENTATION_PLAN.md` only if useful; do not generate application
code yet.

**Done when:** Codex has described the current repo, proposed phase
order, identified applicable skills, and listed any blocking questions.
No unrelated files are changed.

## Phase 1 --- Project foundation and API skeleton

**Build** - Set up the `uv` project and Python version. - Add FastAPI
app, settings/configuration, structured logging, and a consistent error
response. - Add `GET /health/live`, `GET /health/ready`, and
`GET /api/v1/system/info`. - Add `.env.example`, basic tests,
lint/type-check configuration, and a useful README. - Keep readiness
honest: report dependencies as unavailable until they are actually
configured.

**Verify:** install/sync dependencies, run the app, and run tests and
configured quality checks.

## Phase 2 --- NeonDB, SQLAlchemy, and migrations

**Build** - Configure SQLAlchemy with NeonDB PostgreSQL and
environment-based connection settings. - Create models and Alembic
migrations for documents, document chunks, incidents, analysis runs,
jobs, and evaluation runs as specified. - Add a database
session/repository layer and basic persistence tests. - Include
PostgreSQL full-text search support where required. - Do not store
embedding arrays in PostgreSQL; store Pinecone vector IDs/metadata as
appropriate.

**Verify:** migrations can be generated and applied; database tests pass
when NeonDB credentials are available.

## Phase 3 --- Document ingestion, synchronous first

**Build** - Implement file validation and text extraction for Markdown,
TXT, PDF, and JSONL. - Implement deterministic chunking with overlap and
source metadata. - Add `POST /api/v1/documents`, document listing/detail
endpoints, and deletion behavior. - Persist document metadata and
canonical chunk text in NeonDB. - Make re-submitting the same
document/version idempotent. - Start with a clear synchronous ingestion
path; introduce background jobs in Phase 8.

**Verify:** tests cover supported formats, invalid files, size limits,
chunk metadata, duplicate submissions, and deletion.

## Phase 4 --- Embeddings and Pinecone indexing

**Build** - Add a provider-neutral embedding interface and configure a
real embedding provider through environment settings. - Create/configure
Pinecone client and namespace/index settings. - Generate embeddings for
stored chunks and upsert vectors with stable IDs and useful filter
metadata. - Persist each Pinecone vector ID in NeonDB. - Handle retries
and partial failures so ingestion can be safely retried. - Document that
NeonDB and Pinecone do not share a transaction; make repair/retry
behavior explicit.

**Verify:** mock-provider tests pass; live integration tests run only
when valid provider and Pinecone credentials are configured.

## Phase 5 --- Search and hybrid retrieval

**Build** - Implement `POST /api/v1/search`. - Add Pinecone semantic
search and NeonDB PostgreSQL full-text search. - Fuse ranked results
with Reciprocal Rank Fusion (RRF), unless `requirement.md` documents
another choice. - Support metadata filters and return snippets, source
metadata, and scores. - Fetch canonical chunk text from NeonDB after
Pinecone returns matching vector IDs. - Ensure citations refer only to
chunks actually retrieved.

**Verify:** tests cover vector-only, keyword-only, hybrid ranking,
filters, empty results, missing vector records, and stable citation
metadata.

## Phase 6 --- Grounded incident analysis

**Build** - Implement `POST /api/v1/incidents/analyze` and incident/run
read endpoints. - Retrieve relevant chunks before generation. - Define a
typed response schema for summary, ranked hypotheses, supporting
evidence, contradictory/missing evidence, confidence label and
rationale, safe diagnostic steps, citations, and limitations. - Require
the model to distinguish evidence from hypotheses and abstain with
`insufficient_evidence` when appropriate. - Treat retrieved
documents/logs as untrusted input; never let them override system
instructions. - Save incidents and analysis runs in NeonDB.

**Verify:** tests check schema validity, evidence/citation linkage,
insufficient-evidence behavior, prompt-injection resistance, and
provider failure paths.

## Phase 7 --- LLM gateway and routing policies

**Build** - Add a provider-neutral chat interface and configure at least
two providers when credentials are available. - Implement a static
default policy first, then deterministic rule-based routing. - Add
timeouts, bounded retries, rate-limit handling, provider health state,
and circuit-breaker behavior. - Record provider/model, policy, fallback
reason, latency, token usage when available, and estimated cost. -
Implement routing policy/decision endpoints and routing simulation. - Do
not add learned routing until a reliable baseline and evaluation dataset
exist.

**Verify:** unit tests cover policy choices, provider failures, retries,
fallback restrictions, and recorded routing decisions.

## Phase 8 --- Background jobs

**Build** - Add Redis and ARQ worker setup. - Move ingestion and
evaluation workloads to background jobs while keeping API responses
consistent with `requirement.md`. - Implement job status endpoint, retry
policy, idempotency, failure details, and safe logging. - Make the
worker independently runnable and document local development commands.

**Verify:** tests cover queued, processing, completed, and failed jobs,
plus retry/idempotency behavior.

## Phase 9 --- Evaluation framework

**Build** - Create a versioned evaluation dataset format and a small
initial dataset. - Measure retrieval recall@k/hit rate, MRR, and nDCG
where labels permit. - Measure answer schema validity, citation
support/groundedness, correctness, abstention behavior, latency, and
cost. - Store evaluation runs and per-case results. - Add baseline
comparison and configurable regression thresholds. - Keep a holdout set
separate from tuning data.

**Verify:** evaluation runs are reproducible and report
dataset/prompt/model/retrieval configuration. Tests cover metric
calculations and regression gates.

## Phase 10 --- Observability and operational metrics

**Build** - Add request IDs, structured logs, and timing for ingestion,
retrieval, generation, and total request. - Capture retries, provider
errors, fallback events, tokens, and estimated cost when available. -
Add Prometheus-compatible metrics and OpenTelemetry tracing. - Add
optional Langfuse integration only if it is useful and credentials are
configured. - Implement `GET /api/v1/metrics/summary` and readiness
checks.

**Verify:** tests check metric updates and ensure secrets, authorization
headers, and unrestricted uploaded content are not logged.

## Phase 11 --- Security and reliability hardening

**Build** - Add authentication and authorization for ingestion,
evaluation, and operational endpoints before public deployment. - Add
rate limits, upload limits, input validation, safe error handling, and
dependency timeouts. - Review prompt-injection boundaries and
data-handling restrictions for provider fallback. - Ensure document
deletion attempts cleanup in both NeonDB and Pinecone; handle and report
partial failures. - Add tests for unauthorized access, invalid inputs,
oversized files, provider outages, and partial vector-store failures.

**Verify:** security/reliability tests pass and remaining limitations
are documented.

## Phase 12 --- Deployment, CI, and documentation

**Build** - Add Docker support and a production-oriented start
command. - Add CI for dependency installation, linting, type checks,
tests, migrations, and evaluation regression gates where practical. -
Document environment variables, NeonDB/Pinecone/Redis setup, migrations,
API examples, worker startup, and troubleshooting. - Add architecture
and request-flow diagrams. - Provide sample incident data and a demo
walkthrough that uses no real secrets or production systems.

**Verify:** a clean setup can follow the README; CI passes;
health/readiness behavior is documented; no secrets are committed.

## Phase 13 --- Portfolio polish

**Build** - Add a concise architecture overview, feature list, API
examples, screenshots only if a UI exists, trade-offs, limitations, and
demo instructions. - Include sample evaluation results with the dataset
and methodology clearly stated. - Add a roadmap for future work rather
than implementing speculative features prematurely.

**Done when:** another developer can understand the system, run it, test
it, and see evidence for its key claims.

## How to work with Codex

Use this loop for every phase:

1.  Send the master prompt from the project notes or your own Codex
    instruction file.
2.  Ask Codex to implement **only one phase** from this sequence.
3.  Review the plan before allowing broad edits or destructive commands.
4.  Ask Codex to run relevant tests and quality checks.
5.  Review the diff and confirm the acceptance criteria.
6.  Commit the completed phase.
7.  Move to the next phase only after the current one is stable.

**Recommended first task:** Phase 0 only. After reviewing its plan,
start Phase 1.
