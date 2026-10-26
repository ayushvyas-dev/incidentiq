# Evaluation

Evaluation data lives under `datasets/<dataset_id>/<split>/v1.json`. Each file declares its dataset ID, semantic version, split, and cases. Validation and holdout are separate files; keep holdout cases frozen and do not use them to tune prompts or retrieval settings. The bundled `incidentiq_demo` dataset has two validation cases and one holdout case. Upload `datasets/incidentiq_demo/fixtures/connection-pool.md` as a completed `checkout` / `production` runbook before evaluating its positive retrieval case.

Start a run with `POST /api/v1/evaluations`. Runs are queued through Redis/ARQ, and `GET /api/v1/jobs/{job_id}` reports job progress. Read aggregate metrics at `GET /api/v1/evaluations/{evaluation_run_id}` and inspect failures at `/api/v1/evaluations/{evaluation_run_id}/cases`. Interrupted runs resume completed cases by stable `(run_id, case_id)` identity.

The harness reports Recall@k, hit rate, MRR, binary nDCG, exact reference-fact match rate, citation quote support, schema validity, abstention accuracy, p95 latency, and estimated cost per case when routing estimates are configured. Reference-fact correctness uses exact case-insensitive phrase matching, not an LLM judge; paraphrases can be scored as misses. Treat these scores as signals and inspect case evidence.

Optional `regression_thresholds` set the largest allowed regression per metric when a completed `baseline_run_id` is supplied. Deltas are candidate minus baseline; positive changes regress latency and cost, while negative changes regress quality metrics. Deltas are returned whenever both runs have a metric; the gate's `passed` value is `null` when thresholds or comparable metrics are unavailable. Evaluation configuration and dataset version are hashed into `config_hash` for reproducibility.

Evaluation runs use the configured retrieval mode and chat routing policy. Semantic or hybrid retrieval requires Gemini embeddings and Pinecone; answer generation uses Groq first and Gemini fallback under the configured routing policy. Configure model names available on your account's free API tiers; the harness does not silently substitute a model or provider. No live API is required for metric unit tests, but meaningful end-to-end scores require completed source documents and configured providers.

Set `config.permitted_providers` to restrict which chat providers can receive an evaluation case, for example `['groq']` when Gemini fallback is disallowed by data policy. The provider restriction is included in the run configuration hash.
