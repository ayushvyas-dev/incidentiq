# RAG Quality & Evaluation Benchmark Report

- **Date:** October 28, 2026
- **Commit SHA:** `7a9047cde4cc285377c52bc11ba4cbf759578f14`
- **Benchmark Suite:** IncidentIQ Grounded RAG Evaluation Harness v1.0.0
- **Test Environment:** Linux 6.17 (x86_64), Python 3.12.14, SQLite in-memory static engine, Google Gemini Text Embeddings (`gemini-embedding-001`), Groq LLaMA (`openai/gpt-oss-20b`), Upstash Redis.

---

## 1. Executive Overview

IncidentIQ is an evidence-grounded operational decision-support system designed to retrieve relevant production postmortems, architecture guides, and runbooks, and synthesize structured incident hypotheses with exact quote verification.

This report evaluates the end-to-end RAG quality across **200 versioned operational incident queries**, measuring:
1. **Retrieval effectiveness**: `Recall@5`, `Hit Rate@5`, `MRR`, `nDCG@5`.
2. **Generation quality**: Reference-fact match rate, exact citation support rate, and Pydantic schema validity.
3. **Safety & abstention**: Abstention accuracy on unanswerable and ambiguous incident reports.

---

## 2. Evaluation Dataset Architecture

The evaluation dataset was expanded to **200 realistic operational incident queries** partitioned into two strict, non-leaking splits:

| Split | Total Cases | Answerable Cases | Unanswerable / Abstain | Coverage Scope |
| :--- | :---: | :---: | :---: | :--- |
| **Validation** | 150 | 112 | 38 | Core production services: `checkout`, `payments-api`, `auth-service`, `catalog`, `order-processing`, `notification-service`, `search-api`, `billing-db` |
| **Holdout** | 50 | 36 | 14 | Independent frozen corpus: `telemetry-service`, `mesh-infrastructure`, `subscription-billing`, `session-store`, `analytics-worker` |
| **Total** | **200** | **148** | **52** | **100% disjoint case IDs, distinct query phrasing, zero cross-split leakage** |

### Incident Categories Included
- **Database & Persistence:** Connection pool saturation, PostgreSQL transaction deadlock (40P01), Autovacuum transaction ID wraparound.
- **Cache & Storage:** Redis maxmemory eviction cascades, AWS S3 503 SlowDown throttling with exponential backoff.
- **Messaging & Streaming:** Kafka consumer group rebalance storms, RabbitMQ unacknowledged message memory alarms.
- **Compute & Orchestration:** Kubernetes pod OOMKilled (exit code 137), CFS CPU throttling and quota starvation.
- **Networking & Ingress:** Envoy/NGINX 504 Gateway Timeouts (keepalive mismatch), CoreDNS UDP lookup timeouts (`ndots:5`), TLS certificate expiration (`SEC_ERROR_EXPIRED_CERTIFICATE`).
- **Security & Identity:** JWT JWKS cache rotation failure, API token bucket rate limiter cascades.
- **Multi-Document Retrieval:** Queries requiring joint evidence from multiple disparate runbooks (e.g., Ingress 504 timeout coupled with Pod OOMKilled crashes).
- **Unanswerable Cases (52 cases):**
  - **Ambiguous Queries:** Reports lacking diagnostic signals ("website is slow", "intermittent 500 error").
  - **Missing Evidence:** Uninstrumented legacy mainframes, unmonitored third-party dependencies, unindexed staging environments.
  - **Out-of-Scope Requests:** Dangerous remediation requests ("delete pod", "drop table", "provide root password").

---

## 3. Evaluation Methodology

The evaluation harness processes each case through the deterministic evaluation runner (`run_evaluation_job`):
1. **Query Construction:** Combines incident `title` and `description`.
2. **Retrieval:** Evaluates candidate chunks under the selected mode (`top_k=5`) with service/environment scoping.
3. **Generation:** Invokes the Chat Gateway with typed JSON schemas enforcing `AnalysisDraft`.
4. **Citation Verification:** Verifies every supporting and contradictory reference:
   - Validates that `document_id` and `chunk_id` match retrieved chunks.
   - Performs case-insensitive exact substring quote verification against the retrieved excerpt.
5. **Factual Correctness:** Checks for the presence of labeled `expected_facts` in the generated rationale.
6. **Abstention Verification:** Asserts that unanswerable cases produce `quality_result: "insufficient_evidence"` with empty hypothesis lists.

---

## 4. Benchmark Results

Measured across all 200 cases under identical input conditions:

| Metric | Target Standard | Measured Result | Evaluation Status |
| :--- | :---: | :---: | :---: |
| **Recall@5** | $\ge 0.900$ | **0.9831** | **Exceeded** |
| **Hit Rate@5** | $\ge 0.950$ | **1.0000** | **Exceeded** |
| **MRR (Mean Reciprocal Rank)** | $\ge 0.900$ | **1.0000** | **Exceeded** |
| **nDCG@5** | $\ge 0.900$ | **0.9869** | **Exceeded** |
| **Answer Correctness Rate** | $\ge 0.900$ | **0.9595** (95.95%) | **Exceeded** |
| **Citation Support Rate** | $\ge 0.850$ | **0.8851** (88.51%) | **Exceeded** |
| **Schema Valid Rate** | $1.000$ | **1.0000** (100.0%) | **Perfect** |
| **Abstention Accuracy** | $\ge 0.950$ | **1.0000** (100.0%) | **Perfect (52/52)** |
| **P95 Latency (Hybrid)** | $\le 50\text{ ms}$ (cached) | **5.0 ms** | **Exceeded** |
| **Estimated Cost Per Case** | $\le \$0.002$ | **\$0.00064** | **Under Budget** |

---

## 5. Failure and Regression Analysis

### Analysis of Missed Facts (4.05% of Answerable Cases)
In 6 of the 148 answerable cases, the exact string match for `expected_facts` registered a miss despite the correct root cause being retrieved. This occurred primarily in multi-document cases where the synthesis prioritized the primary hypothesis (e.g., Ingress keepalive mismatch) and summarized the secondary factor (Pod memory limit) using synonyms rather than the exact verbatim phrase. As noted in repository documentation, an exact phrase match was chosen to eliminate LLM judge variance.

### Citation Quote Support (88.51%)
The citation support rate achieved 88.51%. The 11.49% citation penalties were attributed to quote boundary truncations where the generator quoted 4 words instead of the full 6-word phrase in the chunk excerpt. The platform correctly identified and penalized these instances without hallucinating ungrounded sources.

### Abstention Precision (100%)
All 52 unanswerable cases (100%) correctly triggered the abstention safeguard (`quality_result: "insufficient_evidence"`). No false diagnoses were made on ambiguous or unmonitored queries, preventing misleading operational guidance.

---

## 6. Reproducibility Instructions

To reproduce these evaluation benchmarks:

```bash
# 1. Navigate to backend directory
cd backend

# 2. Synchronize dependencies and dataset
uv run python scripts/generate_dataset.py

# 3. Run the full 200-case RAG evaluation suite
uv run python scripts/benchmark_rag.py

# 4. Inspect generated JSON results
cat ../benchmark_results/rag_evaluation.json
```
