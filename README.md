# IncidentIQ

IncidentIQ is an evidence-grounded incident investigation and operational decision-support platform. It indexes production runbooks, incident postmortems, architecture diagrams, and operational documentation, retrieves relevant evidence using hybrid search, and synthesizes root-cause hypotheses with exact quote citations and safe, read-only diagnostic steps.

IncidentIQ is strictly a **decision-support system**: it produces grounded diagnostic recommendations and never executes remediation commands in production environments.

---

## Table of Contents

- [Features](#features)
- [Architecture](#architecture)
- [Request Flows](#request-flows)
  - [1. Document Ingestion Flow](#1-document-ingestion-flow)
  - [2. Incident Analysis & Investigation Flow](#2-incident-analysis--investigation-flow)
- [Tech Stack](#tech-stack)
  - [Backend Dependencies & Packages](#backend-dependencies--packages)
  - [Frontend Dependencies & Packages](#frontend-dependencies--packages)
- [Project Folder Structure](#project-folder-structure)
- [Environment Variables](#environment-variables)
  - [Backend Configuration (`backend/.env`)](#backend-configuration-backendenv)
  - [Frontend Configuration (`frontend/.env`)](#frontend-configuration-frontendenv)
- [Setup & Run Instructions](#setup--run-instructions)
  - [Prerequisites](#prerequisites)
  - [Backend Setup & Run](#backend-setup--run)
  - [Frontend Setup & Run](#frontend-setup--run)
  - [Running with Docker Compose](#running-with-docker-compose)
  - [Running Tests & Quality Checks](#running-tests--quality-checks)
- [Demo Walkthrough](#demo-walkthrough)
- [API & Operational Endpoints](#api--operational-endpoints)
- [Benchmark & Reliability Reports](#benchmark--reliability-reports)
- [Trade-offs & Limitations](#trade-offs--limitations)

---

## Features

- **Multi-Format Document Ingestion**: Ingests and processes runbooks, incident reports, and architecture guides from Markdown, TXT, PDF, and JSONL. Documents are chunked deterministically with overlap and tracked through asynchronous background jobs.
- **Hybrid Retrieval Engine**:
  - **Full-Text Search (Keyword)**: PostgreSQL full-text search across canonical chunks.
  - **Dense Semantic Retrieval**: Pinecone vector indexing powered by Gemini text embeddings.
  - **Reciprocal Rank Fusion (Hybrid)**: Fuses lexical and semantic search results with configurable candidate scoring.
- **Evidence-Grounded Incident Analysis**:
  - Synthesizes structured incident hypotheses, confidence levels, and read-only diagnostic investigation steps.
  - Strict citation verification: every claim is linked to exact quoted text within retrieved operational chunks.
  - LLM Gateway: primary Groq generation (`gpt-oss-20b` or custom chat models) with automated Gemini fallback, retry policies, and circuit breakers.
- **Evaluation Harness**:
  - Offline and online evaluation of retrieval quality and answer fidelity across versioned `validation` and `holdout` splits.
  - Automatically calculates `Recall@k`, `Hit Rate`, `MRR`, `nDCG`, exact reference-fact matching, citation quote support rate, schema validity, abstention accuracy, latency, and estimated token costs.
- **Role-Based API Security**: Distinct random bearer tokens for full read/write access (`API_KEY`) and read-only operations (`READONLY_API_KEY`). Routes fail closed if tokens are unconfigured. Rate limits per client.
- **Observability**: Process-local metrics summaries, Prometheus exposition (`/metrics`), structured logs, and OpenTelemetry OTLP tracing hooks.
- **Modern Web Dashboard**: Next.js App Router UI providing incident investigations, document management, interactive search, evaluation inspection, and operational system health monitoring.

---

## Architecture

IncidentIQ separates relational storage, vector indexing, asynchronous workers, and presentation into decoupled layers:

```mermaid
flowchart TB
  subgraph Client Tier
    Browser[Browser / Engineer]
    CLI[cURL / API Client]
  end

  subgraph Frontend Application [Next.js App Router - Port 3000]
    UI[Web Dashboard]
    Proxy[Secure Same-Origin API Proxy\n/api/backend/*]
    UI --> Proxy
  end

  subgraph Backend Application [FastAPI - Port 8000]
    API[FastAPI Gateway\nAuth, Rate Limiting, Validation]
    Router[Model Routing & Circuit Breaker]
    Fusion[Hybrid Retrieval & Ranking Engine]
  end

  subgraph Storage & Queues
    DB[(NeonDB PostgreSQL\nCanonical Chunks, Incidents, Jobs, FTS)]
    VStore[(Pinecone Vector DB\nEmbeddings Index)]
    Queue[(Redis / ARQ Queue)]
  end

  subgraph Async Workers
    Worker[ARQ Background Worker\nDocument Chunking & Indexing]
  end

  subgraph External AI Services
    GeminiEmbed[Gemini Embedding API]
    GroqLLM[Groq Chat API - Primary]
    GeminiLLM[Gemini Chat API - Fallback]
  end

  Browser --> UI
  Proxy --> API
  CLI --> API

  API <--> DB
  API <--> VStore
  API --> Queue
  Queue --> Worker

  Worker <--> DB
  Worker --> GeminiEmbed
  GeminiEmbed --> VStore

  API --> Router
  Router --> GroqLLM
  Router -. Fallback .-> GeminiLLM
  API --> Fusion
  Fusion <--> DB
  Fusion <--> VStore
```

### Storage Model
- **PostgreSQL (NeonDB)**: Single source of truth for raw document chunks, document metadata, job state, incident records, evaluation runs, and full-text keyword indexing.
- **Pinecone**: Ephemeral vector search index storing embedding vectors tagged with canonical relational chunk IDs.
- *Note*: NeonDB and Pinecone do not share distributed transactions; background worker retries and cleanup jobs maintain eventual consistency.

---

## Request Flows

### 1. Document Ingestion Flow

```mermaid
sequenceDiagram
  autonumber
  actor User as Engineer / Client
  participant Web as Frontend / Proxy
  participant API as FastAPI
  participant DB as NeonDB PostgreSQL
  participant Queue as Redis (ARQ)
  participant Worker as ARQ Worker
  participant Gemini as Gemini Embeddings
  participant Pinecone as Pinecone Vector Store

  User->>Web: Upload document (Markdown, PDF, TXT, JSONL)
  Web->>API: POST /api/v1/documents (Bearer Auth)
  API->>API: Validate MIME type, file size, extract text & chunk
  API->>DB: Store canonical document and chunk records
  API->>DB: Create ingestion Job (status: queued)
  API->>Queue: Enqueue job ID
  API-->>User: 202 Accepted (job_id, status: queued)

  Queue->>Worker: Dispatch job
  Worker->>DB: Read chunks for document
  Worker->>Gemini: Generate text embeddings
  Worker->>Pinecone: Upsert vector embeddings with chunk IDs
  Worker->>DB: Update Job status to 'completed'
```

### 2. Incident Analysis & Investigation Flow

```mermaid
sequenceDiagram
  autonumber
  actor User as Incident Commander
  participant Web as Frontend
  participant API as FastAPI
  participant Pinecone as Pinecone Vector Store
  participant DB as NeonDB PostgreSQL
  participant LLM as Groq / Gemini Gateway

  User->>Web: Submit incident details & observed symptoms
  Web->>API: POST /api/v1/incidents/analyze
  API->>API: Validate input schema & token limits

  par Retrieve Semantic Candidates
    API->>Pinecone: Vector similarity query (if enabled)
    Pinecone-->>API: Vector candidate chunk IDs
  and Retrieve Keyword Candidates
    API->>DB: Full-text search (tsvector/tsquery)
    DB-->>API: Lexical candidate chunks
  end

  API->>API: Reciprocal Rank Fusion & top-k pruning
  API->>DB: Fetch full text for top ranked chunks
  API->>LLM: Generate hypotheses & diagnostic steps with evidence
  LLM-->>API: Structured response
  API->>API: Validate citation quotes exist in source evidence
  API->>DB: Persist Incident and AnalysisRun records
  API-->>User: Structured hypotheses, exact citations, diagnostic steps
```

---

## Tech Stack

### Backend Dependencies & Packages

| Package | Purpose |
| --- | --- |
| **Python 3.12+** | Core runtime environment |
| **uv** | Ultra-fast Python package and project manager |
| **FastAPI (`>=0.115`)** | Asynchronous web framework for high-performance API endpoints |
| **Uvicorn (`>=0.30`)** | ASGI web server implementation |
| **SQLAlchemy (`>=2.0`)** | Async-ready Python SQL toolkit and Object Relational Mapper |
| **Alembic (`>=1.13`)** | Database schema migration management |
| **psycopg (`>=3.2`)** | Modern PostgreSQL driver for NeonDB connection pooling |
| **ARQ (`>=0.26`)** | High-performance Redis-based asynchronous task queue |
| **Pinecone (`>=5.0`)** | Cloud-native vector database client for semantic retrieval |
| **OpenAI (`>=1.0`)** | SDK used for Groq-compatible chat completions API |
| **PyMuPDF (`>=1.24`)** | Fast extraction of text from operational PDF documents |
| **python-multipart** | Streaming multipart form-data parser for file uploads |
| **OpenTelemetry SDK (`>=1.25`)** | Distributed tracing and performance instrumentation |
| **Pytest (`>=8.0`)** & **HTTPX** | Test runner, fixtures, and asynchronous HTTP client for testing |
| **Ruff (`>=0.11`)** & **Mypy** | High-performance Python linter, formatter, and static type checker |

### Frontend Dependencies & Packages

| Package | Purpose |
| --- | --- |
| **Next.js (`^16.3.7`)** | React framework utilizing App Router and Turbopack |
| **React (`^19.3.0`)** | Modern React with Server and Client Components |
| **TypeScript (`^5.9.3`)** | Strict type safety across the UI layer |
| **Tailwind CSS (`^4.3.3`)** | Utility-first CSS styling engine |
| **@tanstack/react-query (`^5.104.3`)** | Asynchronous state management, caching, and polling |
| **React Hook Form (`^7.90.0`) & Zod (`^4.6.5`)** | Type-safe form validation for investigations and simulations |
| **Lucide React (`^1.57.0`)** | Comprehensive icon system |
| **Recharts (`^3.10.1`)** | Visualization library for latency, cost, and evaluation metric charts |
| **Sonner (`^2.0.8`)** | Toast notification system |
| **Playwright (`^1.64.1`)** | End-to-end browser integration testing |

---

## Project Folder Structure

```
incident-iq/
├── .github/
│   └── workflows/
│       └── ci.yml             # GitHub Actions CI matrix for backend & frontend
├── backend/                   # Python backend service
│   ├── alembic/               # Database migrations
│   │   ├── versions/          # Migration revisions (0001 to 0004)
│   │   └── env.py             # Alembic migration runner configuration
│   ├── datasets/              # Versioned evaluation datasets & fixtures
│   │   └── incidentiq_demo/   # Smoke-test cases (validation, holdout, fixtures)
│   ├── src/
│   │   └── incidentiq/
│   │       ├── api/           # FastAPI routers (documents, incidents, evaluations, jobs, search)
│   │       ├── db/            # SQLAlchemy session management and repositories
│   │       ├── ingestion/     # PDF, Markdown, text parsers and chunking logic
│   │       ├── services/      # Analysis, evaluation runner, vector index, and ranking
│   │       ├── workers/       # ARQ background queue settings and job processors
│   │       ├── main.py        # Core FastAPI application instance & lifespan handlers
│   │       ├── models.py      # SQLAlchemy relational schema models
│   │       ├── observability.py# Prometheus metrics and OpenTelemetry trace exporter
│   │       └── security.py    # Bearer token authentication & rate limiting
│   ├── tests/                 # Unit, mocked API, evaluation, and security tests
│   │   ├── conftest.py        # Test configuration and isolated test env loader
│   │   └── .env.test          # Test credentials and isolated settings
│   ├── alembic.ini            # Migration tool configuration
│   ├── Dockerfile             # Production multi-stage Docker build
│   ├── main.py                # Convenience entrypoint proxy (uvicorn main:app)
│   ├── pyproject.toml         # Python project configuration and dependencies
│   └── uv.lock                # Pinned dependency lockfile
├── frontend/                  # Next.js web application
│   ├── src/
│   │   ├── app/               # App Router pages
│   │   │   ├── api/backend/   # Secure server-side proxy route to FastAPI
│   │   │   ├── evaluations/   # Evaluation run list, triggers, and case details
│   │   │   ├── investigations/# Incident investigation dashboard & submission form
│   │   │   ├── knowledge/     # Document upload, parsing status, and chunk management
│   │   │   ├── operations/    # System readiness, provider health, and metrics
│   │   │   ├── search/        # Interactive keyword, semantic, and hybrid search
│   │   │   ├── layout.tsx     # Root shell and navigation layout
│   │   │   └── page.tsx       # System overview dashboard
│   │   └── components/        # Reusable UI widgets, panels, and metric cards
│   ├── package.json           # Node.js dependencies and script commands
│   ├── package-lock.json      # Pinned npm lockfile
│   └── tsconfig.json          # TypeScript compiler options
├── datasets -> backend/datasets # Symlink to backend datasets for root accessibility
├── compose.yaml               # Docker Compose file (Redis, Backend API, ARQ Worker)
├── requirement.md             # Functional and technical specification requirements
└── README.md                  # Project documentation
```

---

## Environment Variables

### Backend Configuration (`backend/.env`)

Copy `backend/.env.example` to `backend/.env`:

```sh
cp backend/.env.example backend/.env
```

| Variable | Description | Example / Default |
| --- | --- | --- |
| `DATABASE_URL` | NeonDB pooled connection string for application traffic | `postgresql+psycopg://user:pass@ep-xyz-pooler.aws.neon.tech/neondb?sslmode=require` |
| `DIRECT_DATABASE_URL` | Direct (non-pooled) NeonDB connection string for migrations | `postgresql+psycopg://user:pass@ep-xyz.aws.neon.tech/neondb?sslmode=require` |
| `DATABASE_CONNECT_TIMEOUT_SECONDS`| Connection establishment timeout | `10` |
| `DATABASE_POOL_TIMEOUT_SECONDS`   | Queue wait timeout for connection from pool | `10` |
| `API_KEY` | Admin token granting read, write, and delete permissions | Random string (min 32 characters) |
| `READONLY_API_KEY` | Restricted token granting GET and HEAD requests only | Random string (min 32 characters) |
| `API_RATE_LIMIT_PER_MINUTE` | Per-client rate limit for general endpoints | `120` |
| `UPLOAD_RATE_LIMIT_PER_MINUTE` | Per-client upload rate limit | `10` |
| `MAX_UPLOAD_MB` | Maximum allowed document upload file size | `10` |
| `CHUNK_SIZE` | Target character size for text chunks | `800` |
| `CHUNK_OVERLAP` | Overlapping characters between consecutive chunks | `120` |
| `REDIS_URL` | Redis connection URL for task queue | `redis://localhost:6379/0` (or `rediss://...` for Upstash) |
| `COMPOSE_REDIS_URL` | Internal Compose Redis connection URL | `redis://redis:6379/0` |
| `GROQ_API_KEY` | Groq API key for primary LLM generation | `gsk_...` |
| `GROQ_CHAT_MODEL` | Groq model identifier | `openai/gpt-oss-20b` |
| `GEMINI_API_KEY` | Google Gemini API key for embeddings & fallback chat | `AQ....` |
| `GEMINI_CHAT_MODEL` | Gemini fallback model identifier | `gemini-3.5-flash-lite` |
| `GEMINI_EMBEDDING_MODEL` | Gemini embedding model identifier | `gemini-embedding-001` |
| `EMBEDDING_DIMENSION` | Dimension produced by the embedding model | `768` |
| `PINECONE_API_KEY` | Pinecone API key | `pcsk_...` |
| `PINECONE_INDEX` | Pinecone index name | `incidentiq-index` |
| `PINECONE_NAMESPACE` | Logical namespace for vector records | `incidentiq` |
| `ROUTING_POLICY` | Model routing policy (`static` or `rule_based`) | `static` |
| `CHAT_TIMEOUT_SECONDS` | Provider timeout for generation requests | `20` |
| `CHAT_MAX_ATTEMPTS` | Maximum retry attempts per provider | `2` |
| `CHAT_CIRCUIT_FAILURE_THRESHOLD`| Consecutive failures before tripping provider circuit | `3` |
| `CHAT_CIRCUIT_RESET_SECONDS` | Cooldown period before half-opening a circuit | `30` |
| `INGESTION_JOB_MAX_ATTEMPTS` | Maximum worker retry attempts for failed jobs | `3` |
| `EVALUATION_DATASET_DIR` | Relative or absolute path to dataset directory | `datasets` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Optional OpenTelemetry collector endpoint | `http://localhost:4318/v1/traces` |

### Frontend Configuration (`frontend/.env`)

Copy `frontend/.env.example` to `frontend/.env`:

```sh
cp frontend/.env.example frontend/.env
```

| Variable | Description | Default |
| --- | --- | --- |
| `INCIDENTIQ_API_URL` | Base URL of the running FastAPI backend | `http://127.0.0.1:8000` |
| `INCIDENTIQ_API_KEY` | Backend write token used by server proxy for POST/DELETE | Matches backend `API_KEY` |
| `INCIDENTIQ_READONLY_API_KEY` | Backend read token used by server proxy for GET queries | Matches backend `READONLY_API_KEY` |
| `FRONTEND_MAX_UPLOAD_MB` | Frontend payload size enforcement cap | `4` |

---

## Setup & Run Instructions

### Prerequisites
- Python 3.12+ and [uv](https://docs.astral.sh/uv/) (`>=0.13.1`)
- Node.js 22+ and npm
- PostgreSQL database instance (such as NeonDB)
- Redis server (local `redis-server` or cloud TCP Redis such as Upstash)
- Docker & Docker Compose (optional for containerized execution)

---

### Backend Setup & Run

1. **Install dependencies**:
   ```sh
   cd backend
   uv sync --dev
   ```

2. **Configure environment**:
   ```sh
   cp .env.example .env
   # Edit .env and supply your DATABASE_URL, API_KEY, REDIS_URL, etc.
   ```

3. **Apply database migrations**:
   ```sh
   uv run alembic upgrade head
   ```

4. **Start the API server**:
   ```sh
   uv run uvicorn main:app --host 127.0.0.1 --port 8000 --reload
   ```

5. **Start the background worker** (in a separate terminal):
   ```sh
   cd backend
   uv run arq incidentiq.workers.queue.WorkerSettings
   ```

Verify backend health:
```sh
curl http://127.0.0.1:8000/health/ready
# Output: {"status":"ready","dependencies":{"api_auth":"ok","postgres":"ok","redis":"ok"}}
```

---

### Frontend Setup & Run

1. **Install dependencies**:
   ```sh
   cd frontend
   npm install
   ```

2. **Configure environment**:
   ```sh
   cp .env.example .env
   # Ensure INCIDENTIQ_API_URL=http://127.0.0.1:8000 and matching API keys
   ```

3. **Start the development server**:
   ```sh
   npm run dev
   ```

Open [http://localhost:3000](http://localhost:3000) in your browser.

---

### Running with Docker Compose

To launch Redis, the API server, and the ARQ background worker together in containers:

1. Populate `backend/.env` with your NeonDB, Pinecone, and model credentials.
2. Build and start the services:
   ```sh
   docker compose build
   docker compose run --rm api alembic upgrade head
   docker compose up
   ```
3. The API will be accessible on `http://localhost:8000`.

---

### Running Tests & Quality Checks

#### Backend Quality Checks
Run from the `backend/` directory:

```sh
cd backend

# Run full test suite (74 unit and integration tests)
uv run pytest -q

# Run code style and lint checks
uv run ruff check src tests

# Run type checker on critical boundary modules
uv run mypy src/incidentiq/security.py src/incidentiq/db/session.py --ignore-missing-imports

# Check Python bytecode compilation
uv run python -m compileall -q src tests
```

#### Frontend Quality Checks
Run from the `frontend/` directory:

```sh
cd frontend

# Run TypeScript static type check
npm run typecheck

# Run ESLint rules
npm run lint

# Run Node unit tests (proxy route & security tests)
npm run test

# Validate production build bundle
npm run build
```

---

## Demo Walkthrough

1. **Set your local authorization token**:
   ```sh
   export API_TOKEN='<your backend API_KEY>'
   ```

2. **Upload a sample operational runbook**:
   ```sh
   curl -X POST http://localhost:8000/api/v1/documents \
     -H "Authorization: Bearer ${API_TOKEN}" \
     -F 'source_type=runbook' \
     -F 'service=checkout' \
     -F 'environment=production' \
     -F 'file=@backend/datasets/incidentiq_demo/fixtures/connection-pool.md;type=text/markdown'
   ```
   *(Returns `{"job_id": "...", "status": "queued"}`)*

3. **Check ingestion job progress**:
   ```sh
   curl -H "Authorization: Bearer ${API_TOKEN}" http://localhost:8000/api/v1/jobs/<job_id>
   ```

4. **Perform keyword or hybrid search**:
   ```sh
   curl -X POST http://localhost:8000/api/v1/search \
     -H "Authorization: Bearer ${API_TOKEN}" \
     -H 'Content-Type: application/json' \
     -d '{
       "query": "connection pool acquisition timeouts",
       "mode": "keyword",
       "top_k": 5
     }'
   ```

5. **Trigger an evidence-grounded incident analysis**:
   ```sh
   curl -X POST http://localhost:8000/api/v1/incidents/analyze \
     -H "Authorization: Bearer ${API_TOKEN}" \
     -H 'Content-Type: application/json' \
     --data-binary @examples/demo-incident.json
   ```

---

## API & Operational Endpoints

All `/api/v1/*` routes and `/metrics` require `Authorization: Bearer <token>`. The read-only token permits GET/HEAD requests; mutating endpoints require the full `API_KEY`.

| Method | Endpoint | Description | Auth Required |
| --- | --- | --- | --- |
| `GET` | `/health/live` | Process liveness probe | No |
| `GET` | `/health/ready` | Verifies PostgreSQL, Redis, and Auth readiness | No |
| `GET` | `/api/v1/system/info` | Service metadata and version | Bearer |
| `POST`| `/api/v1/documents` | Multipart document upload and background indexing | Bearer (Write) |
| `GET` | `/api/v1/documents` | List uploaded documents with pagination | Bearer (Read) |
| `GET` | `/api/v1/documents/{id}` | Retrieve document chunks and ingestion status | Bearer (Read) |
| `DELETE`| `/api/v1/documents/{id}` | Delete document and corresponding vectors | Bearer (Write) |
| `GET` | `/api/v1/jobs/{id}` | Inspect progress of background indexing jobs | Bearer (Read) |
| `POST`| `/api/v1/search` | Search indexed documents (keyword, semantic, hybrid)| Bearer (Read) |
| `POST`| `/api/v1/incidents/analyze`| Perform grounded analysis on incident symptoms | Bearer (Write) |
| `GET` | `/api/v1/incidents` | List analyzed incident records | Bearer (Read) |
| `GET` | `/api/v1/incidents/{id}` | Retrieve incident details and analysis history | Bearer (Read) |
| `POST`| `/api/v1/evaluations` | Enqueue a dataset evaluation run | Bearer (Write) |
| `GET` | `/api/v1/evaluations` | List historical evaluation runs | Bearer (Read) |
| `GET` | `/api/v1/evaluations/{id}` | Detailed metrics and regression comparison | Bearer (Read) |
| `POST`| `/api/v1/routing/simulate` | Simulate model routing without calling LLM | Bearer (Read) |
| `GET` | `/api/v1/metrics/summary` | Aggregated operational metrics (`1h`, `24h`, `7d`) | Bearer (Read) |
| `GET` | `/metrics` | Prometheus exposition endpoint | Bearer (Read) |

---

## Benchmark & Reliability Reports

Comprehensive, reproducible benchmark reports evaluated across a versioned 200-case dataset, high-concurrency traffic, chaos fault injection, and ingestion stress tests:

| Report | Focus Area | Key Measured Result |
| :--- | :--- | :--- |
| **[Executive Summary](docs/reports/executive_summary.md)** | Overall System Scorecard | Complete synthesis of quality, latency, capacity, and resilience |
| **[RAG Quality Evaluation](docs/reports/rag_evaluation.md)** | Retrieval & Answer Grounding | **Recall@5: 0.9831**, HitRate: 1.0, MRR: 1.0, **100% Abstention Accuracy** |
| **[Retrieval Comparison](docs/reports/retrieval_comparison.md)** | Keyword vs Semantic vs Hybrid | RRF $k=60$ hybrid search provides zero-regression ranking resilience |
| **[Load, Latency & Capacity](docs/reports/load_and_latency.md)** | Concurrency & Sustained Stress | **68.89 RPS** sustained over 10 min (41,350 reqs), **0 errors**, +7.67 MB RSS |
| **[Failure Injection & Chaos](docs/reports/failure_injection.md)** | Fault Tolerance & Fallbacks | **100% safe pass** across 50 trials (timeouts, dual outages, DB/vector faults) |
| **[Ingestion Reliability](docs/reports/ingestion_reliability.md)** | Multi-format Stress Pipeline | **100/100 jobs verified** across MD, TXT, PDF, JSONL and failure cases |

*Raw benchmark artifacts and reproduction scripts live in `backend/benchmark_results/` and `backend/scripts/`.*

---

## Trade-offs & Limitations

- **Decoupled Relational & Vector Storage**: NeonDB holds canonical text and keyword search indices while Pinecone holds vector embeddings. Because distributed two-phase commits are not used, partial failures require asynchronous background reconciliation.
- **Decision-Support Only**: IncidentIQ deliberately generates diagnostic investigation steps and verified hypotheses. It is strictly forbidden from executing remediation actions directly against infrastructure.
- **Citation Precision**: Verification asserts that quoted text exists verbatim in retrieved operational evidence chunks. It confirms grounding, but does not guarantee that the operational runbook itself was accurate or up to date.
- **Process-Local Metrics**: Application metrics (`/metrics/summary`) are collected in-process. In a multi-replica deployment, metrics should be aggregated via Prometheus using the `/metrics` exposition endpoint.
