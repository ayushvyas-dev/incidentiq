# IncidentIQ Frontend — Codex Implementation Guide

## Goal

Build a polished, responsive web dashboard for **IncidentIQ**, an AI-assisted incident investigation and reliability platform. Read this file together with `requirement.md` and `sequence.md` before writing code.

IncidentIQ helps engineers investigate production incidents by searching logs, runbooks, service documentation, and historical incident reports. It returns evidence-backed hypotheses, verifiable citations, uncertainty, and safe diagnostic next steps.

**This is a decision-support tool, not an autonomous production operator.** Never add features that execute remediation commands or mutate real infrastructure.

## 1. Start by understanding the existing repository

Before implementation:

1. Inspect the repository structure, `requirement.md`, `sequence.md`, backend source, tests, `.env.example` if present, and README.
2. Inspect the FastAPI routes and request/response schemas. Use the backend's actual API contract; do not invent endpoints or payload fields.
3. Check the backend OpenAPI document/schema if available. Create a concise endpoint map for the frontend.
4. Identify which features are implemented and which are not. Build UI only for supported functionality; clearly mark unavailable data instead of fabricating it.
5. Keep the existing backend, Python/`uv` configuration, migrations, tests, and lockfiles intact unless a frontend integration fix is genuinely necessary.

Create the frontend at the repository root in `frontend/`, alongside the existing backend files. Keep frontend dependencies and scripts in `frontend/package.json`.

## 2. Required stack

- **Next.js App Router**
- **TypeScript** with strict mode
- **Tailwind CSS**
- **shadcn/ui** components
- **Lucide React** icons
- **TanStack Query** for client-side server state where useful
- **React Hook Form + Zod** for forms and validation
- **Recharts** for supported metrics/evaluation visualizations
- **Sonner** for concise toast notifications
- Use the package manager and lockfile convention already present in `frontend/`; if none exists, choose one and use it consistently.

Use current stable versions compatible with each other. Read current official documentation when configuring Next.js, Tailwind, shadcn/ui, or packages. Do not add dependencies without a clear use case.

## 3. Visual direction: Vercel-inspired, not a copy

References:
- https://vercel.com/
- https://vercel.com/design/guidelines

Create an original IncidentIQ interface using the restraint and precision of Vercel's developer tooling. Do not copy Vercel branding, logo, page content, or exact layouts.

### Design principles

- Neutral, high-contrast palette: near-black text, white/near-white surfaces, subtle gray borders.
- Use Geist / Geist Mono where practical, with sensible sans-serif and monospace fallbacks.
- Clear typography hierarchy, restrained font weights, compact labels, and tabular numerals for metrics.
- Thin borders and subtle layered shadows; avoid excessive rounded cards.
- Use one primary action style. Reserve semantic colors for success, warning, error, and status indicators.
- Avoid decorative gradients, glassmorphism, giant rounded cards, excessive animations, emoji icons, and generic AI-dashboard styling.
- Use consistent spacing, alignment, and a small set of radii.
- Support light and dark themes if feasible, while ensuring both remain readable and consistent.
- Provide visible keyboard focus, accessible labels, adequate contrast, and responsive layouts.
- Include loading skeletons, empty states, error states, disabled states, and retry/recovery paths—not just the happy path.

### Suggested application shell

- Desktop: compact left sidebar, top header/breadcrumbs, main content area with clear page title and primary action.
- Mobile: collapsible navigation and layouts that work without horizontal scrolling.
- Sidebar should prioritize actual product workflows, not an oversized marketing navigation.
- Keep density appropriate for engineers investigating incidents: concise tables, readable evidence, timestamps, statuses, and trace/job identifiers.

## 4. Product navigation and pages

Use these as the proposed information architecture. Match each page to real backend capabilities and omit or label anything unsupported.

### A. Overview (`/`)

Purpose: summarize current system activity and provide fast entry points.

Potential sections, only when supported by API data:
- Quick actions: investigate an incident, upload a document, search knowledge.
- Recent investigations and ingestion jobs.
- Knowledge-base document/chunk counts.
- Recent failures or job states.
- Evaluation or operational metrics.
- Backend readiness/health indicators.

Do not hardcode fake live metrics. If there is no data endpoint, show a useful empty state or a small clearly labeled demo state only when demo mode is explicit.

### B. Incident investigation (`/investigations/new` and result/detail routes)

Provide a form for the actual supported incident fields, such as incident summary and symptoms, affected service and environment, severity, and optional log excerpts. Use the backend's actual request schema. Validate inputs and show helpful field-level errors.

Present results in a scannable structure:
- Incident summary
- Ranked hypotheses and confidence labels
- Supporting evidence
- Contradictory or missing evidence
- Safe diagnostic next steps
- Citations/source excerpts
- Limitations or `insufficient_evidence` state

Citations must link to source metadata actually returned by the backend. Never fabricate evidence, confidence probabilities, source names, or completed actions. Make uncertainty and missing evidence visible.

### C. Knowledge base (`/knowledge`)

Support available document workflows:
- Upload Markdown, text, PDF, or JSONL only if those formats are accepted by the backend.
- Show validation errors and upload limits based on backend configuration/documentation.
- Display ingestion status (`queued`, `processing`, `completed`, `failed`) if returned by the API.
- Allow users to refresh or poll job status responsibly.
- Show document metadata and errors without exposing sensitive content.
- Add search with filters only where supported by the actual retrieval API.
- Make retry/delete actions available only if corresponding backend endpoints exist and are protected.

### D. Search (`/search`)

Provide natural-language or keyword search using the actual retrieval endpoint. Show ranked results, excerpts, source, service/environment metadata, timestamps, and scores only when returned by the backend. Make filters reflect real API parameters.

### E. Evaluations (`/evaluations`)

If endpoints exist, display evaluation runs, dataset/version information, retrieval metrics (e.g. recall@k, MRR, nDCG), groundedness/citation support, abstention, latency, and cost estimates. Clearly distinguish estimates from exact billing data. If no endpoint exists, do not fabricate charts or pretend a run occurred.

### F. Operations / routing (`/operations`)

If supported by the backend, show health/readiness, provider selection/fallback events, latency, retries, circuit-breaker state, request/trace IDs, and operational metrics. Protect sensitive operational details. Do not expose raw traces, configuration secrets, or unrestricted Prometheus/debug endpoints publicly.

## 5. Backend integration and security

### API contract first

- Map each implemented UI action to an existing FastAPI endpoint and schema.
- Keep a typed API client in a focused module such as `src/lib/api/`.
- Use shared TypeScript types that accurately mirror the backend's response models.
- Handle non-2xx responses, validation errors, timeouts, empty responses, and network failures consistently.
- Avoid duplicate fetching, unbounded polling, and unnecessary client state.
- Use TanStack Query for client-side server state where it simplifies caching, invalidation, loading, and retries; do not add it everywhere automatically.

### Keep credentials server-side

The backend uses API keys. **Never put backend read/write keys in `NEXT_PUBLIC_*` variables or client-side JavaScript.**

Prefer a small Next.js server-side backend-for-frontend (BFF) using Route Handlers or Server Actions:
- Browser calls the Next.js frontend.
- Server-side handlers forward permitted requests to FastAPI and attach the appropriate API key.
- Store the backend URL and API keys in server-only environment variables.
- Use the read-only key for read-only operations and the write key only for operations that require it.
- Do not forward arbitrary user-supplied URLs or arbitrary headers.
- Do not log secrets, authorization headers, uploaded raw content, or sensitive incident details.
- Add clear user-facing authentication/configuration errors without revealing secrets.

Use an environment file such as `frontend/.env.local` for local development. Suggested names (adapt to the actual backend and deployment):

```dotenv
# Server-only: do not prefix these with NEXT_PUBLIC_
BACKEND_API_URL=http://127.0.0.1:8000
BACKEND_READONLY_API_KEY=
BACKEND_API_KEY=
```

Only expose a public base URL if the architecture genuinely requires it and it contains no secret. Ensure `.env.local` is ignored by Git. Never read or print the repository's real `.env` values into logs or generated documentation.

### Background jobs

For ingestion or evaluations that return job/run IDs:
- Show queued/running/completed/failed states based on actual API responses.
- Poll only while a job is active, with a sensible interval and cleanup.
- Stop polling when the job reaches a terminal state or the page unmounts.
- Show recoverable errors and a manual refresh option.
- Do not assume a request has completed just because it was accepted.

### Trust and safety

- Treat uploaded documents, logs, and retrieved passages as untrusted data.
- Render user/document text as text, not raw HTML. Sanitize any supported rich text/Markdown renderer.
- Never allow retrieved text or LLM output to trigger browser actions or production commands.
- Never display model-generated citations unless they resolve to sources returned by the backend.
- Clearly label model-assessed confidence as a label, not a calibrated probability.
- Keep authorization checks on the backend; frontend visibility is not authorization.

## 6. Suggested frontend structure

Adapt this structure to the Next.js version and shadcn conventions actually installed; do not create empty abstractions just to match it.

```text
frontend/
├── src/
│   ├── app/
│   │   ├── (dashboard)/
│   │   │   ├── page.tsx
│   │   │   ├── investigations/
│   │   │   ├── knowledge/
│   │   │   ├── search/
│   │   │   ├── evaluations/
│   │   │   └── operations/
│   │   ├── api/                 # BFF Route Handlers, if needed
│   │   ├── layout.tsx
│   │   └── globals.css
│   ├── components/
│   │   ├── layout/
│   │   ├── shared/
│   │   └── ui/                  # shadcn/ui generated components
│   ├── lib/
│   │   ├── api/
│   │   ├── schemas/
│   │   ├── utils.ts
│   │   └── ...
│   └── types/
├── public/
├── .env.example                 # placeholders only
├── .env.local                   # local secrets; never commit
├── package.json
└── ...
```

## 7. Implementation workflow

Work incrementally and validate each step.

1. **Reconnaissance:** inspect requirements, backend routes/schemas, health checks, existing tests, and design guidelines. Produce an endpoint-to-page mapping before coding.
2. **Scaffold:** create `frontend/` with Next.js, TypeScript, Tailwind, and shadcn/ui. Confirm the app starts.
3. **Design foundation:** establish fonts, CSS variables/tokens, layout shell, sidebar, header, typography, buttons, tables, forms, status badges, and responsive behavior.
4. **API boundary:** implement typed server-side API forwarding and safe environment-variable handling. Test error handling before wiring every page.
5. **Overview and knowledge:** build useful empty/loading/error states and connect real health, upload, and ingestion-status endpoints where available.
6. **Investigation and search:** connect the actual request/response schemas, render evidence and citations carefully, and handle insufficient evidence.
7. **Evaluations and operations:** implement only what the API exposes.
8. **Polish:** accessibility, responsive checks, consistent spacing, loading states, and error recovery.
9. **Validation:** run lint, typecheck, tests, and production build. Fix issues caused by the frontend changes.

Do not try to build every page in one giant component. Use small, readable components and straightforward data flow. Avoid premature abstractions and unnecessary state-management libraries.

## 8. Testing and completion criteria

At minimum:
- `npm run lint` (or the equivalent configured script)
- `npm run typecheck` if configured; otherwise run the project's TypeScript check
- `npm run build`
- Tests for API forwarding/auth-header selection and error handling
- Tests for forms and key state transitions where practical
- Manual responsive review at mobile and desktop widths

Completion criteria:
- The frontend starts using documented commands.
- Core pages use real backend contracts, not guessed endpoints or fake metrics.
- Loading, empty, success, validation, and error states are implemented.
- Evidence/citations remain traceable to retrieved sources.
- API keys remain server-side and secrets are not committed.
- No destructive or autonomous production actions exist.
- Lint, type checks, tests, and production build results are reported honestly.

## 9. Final instructions to Codex

- Read `frontend.md`, `requirement.md`, and `sequence.md` before implementation.
- Inspect the current code and official documentation instead of guessing.
- Build the frontend in `frontend/`; do not rewrite the backend.
- Preserve working backend behavior and existing tests.
- Use Groq as the primary chat provider, Gemini as fallback and the embedding provider only; provider calls remain on the backend, never from the browser.
- Use the Vercel-inspired visual direction without copying branding or exact pages.
- Do not invent API capabilities or data.
- After each major step, run relevant checks and summarize files changed, actual test/build results, and blockers.
