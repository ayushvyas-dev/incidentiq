# Document ingestion

`POST /api/v1/documents` validates and parses the upload, writes canonical text chunks and stable vector IDs to NeonDB, creates an ingestion job, and returns `202 Accepted`. The ARQ worker generates Gemini embeddings and upserts Pinecone vectors. `GET /api/v1/jobs/{job_id}` reports queued, processing, completed, or failed status and progress.

NeonDB and Pinecone do not share a transaction. The worker reuses stable chunk/vector IDs, retries indexing up to `INGESTION_JOB_MAX_ATTEMPTS`, and marks the document completed only after Pinecone upserts succeed. Re-uploading identical content reuses its document and any active job; after failure, another upload creates a new job. Worker startup re-enqueues pending NeonDB jobs to repair an API/Redis interruption. Error responses and stored job details use safe error codes, not exception text or uploaded content.

Run Redis locally, configure `REDIS_URL`, and start the API and worker separately:

```sh
docker run --rm --name incidentiq-redis -p 6379:6379 redis:7-alpine
uv run uvicorn incidentiq.main:app --reload
uv run arq incidentiq.workers.queue.WorkerSettings
```

Configure `GEMINI_API_KEY`, `GEMINI_EMBEDDING_MODEL`, `PINECONE_API_KEY`, and `PINECONE_INDEX`. Gemini is the exclusive embedding provider. The Pinecone index dimension must match `EMBEDDING_DIMENSION`; the example uses 768. Changing the model or dimension requires a matching Pinecone index and re-embedding existing chunks. Set `PINECONE_NAMESPACE` to choose the index namespace. Use a Gemini model enabled by the account's free API tier.

Evaluation jobs use the same Redis queue and job status endpoint; see [evaluation.md](evaluation.md) for dataset setup and API behavior.
