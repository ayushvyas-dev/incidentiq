# IncidentIQ frontend

Next.js App Router frontend for the existing IncidentIQ API. Start the backend and frontend separately; the browser only talks to the same-origin `/api/backend/*` proxy.

## Setup

Copy `.env.example` to `.env.local` and provide the backend URL and server-side API keys. `INCIDENTIQ_READONLY_API_KEY` is used for GET requests; `INCIDENTIQ_API_KEY` is used for upload, analysis, evaluation, routing simulation, and delete requests. Health checks are public. Keys are never sent to the browser. The frontend upload cap defaults to 4 MB to stay under Vercel's 4.5 MB function request-body limit; keep it at or below the backend `MAX_UPLOAD_MB` too.

Run `npm install`, then `npm run dev`. `npm run build`, `npm run typecheck`, `npm run lint`, and `npm test` are the configured checks.

## API-backed screens

| Screen | Backend data/actions |
| --- | --- |
| Overview | `/health/ready`, documents, incidents, evaluations, and process-local metrics summary |
| Investigations | incident list, synchronous `/incidents/analyze`, incident detail and runs |
| Knowledge base | document list, multipart upload, ingestion job status, document delete |
| Search | `/search` with keyword, semantic, or hybrid mode and service/environment filters |
| Evaluations | evaluation list/start, run detail, case results, and job polling |
| Operations | readiness, provider policy health, metrics summary, and routing simulation |

The API proxy permits only the endpoints and HTTP methods used in those views. It is not an open proxy. The search screen defaults to keyword mode because semantic and hybrid search require configured vector services. Unsupported reranking controls and nonexistent run/retry endpoints are omitted.

Incident content, retrieved document text, and model outputs are untrusted display data. The frontend displays only records and evidence returned by the backend and does not execute diagnostic steps.
