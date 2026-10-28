# IncidentIQ AI Systems Engineering Benchmark: Executive Summary

- **Date:** October 28, 2026
- **Commit SHA:** `7a9047cde4cc285377c52bc11ba4cbf759578f14`
- **System:** IncidentIQ Grounded Operational Decision Support & Incident Analysis Platform
- **Audience:** Senior Engineering Leadership, AI Platform Architects, Site Reliability Engineers

---

## 1. System Mission & Operational Mandate

IncidentIQ is an evidence-grounded operational decision-support platform designed to accelerate incident response during mission-critical production outages. It indexes production runbooks, postmortems, architecture documentation, and system topology guides across multiple formats, retrieves relevant evidence using Reciprocal Rank Fusion (hybrid lexical + dense semantic search), and synthesizes structured incident hypotheses with exact, verifiable quote citations and safe, read-only diagnostic steps.

IncidentIQ operates strictly under a **decision-support model**: it produces verified hypotheses and read-only diagnostic commands, and is architecturally barred from executing destructive remediation commands against production infrastructure.

---

## 2. Key Benchmark Findings at a Glance

```
========================================================================================
                               BENCHMARK SCORECARD
========================================================================================
  Evaluation Dataset:           200 Versioned Incident Queries (Zero Cross-Split Leakage)
  Unanswerable Safeguard:       52 Unanswerable Cases Evaluated -> 100.0% Abstention Accuracy
  Retrieval Recall@5:           0.9831 (Hit Rate@5: 1.000, MRR: 1.000, nDCG@5: 0.9869)
  Answer Correctness:           95.95% (Exact reference-fact verification)
  Citation Support Rate:        88.51% (Exact quote match in retrieved operational chunks)
  Pydantic Schema Validity:     100.00% across all evaluated incident analyses
  API Sustained Throughput:     68.89 RPS sustained over 10 Minutes (41,350 total requests)
  Sustained Test Error Rate:    0.000% (Zero dropped requests, zero 500 errors)
  Memory RSS Stability:         185.49 MB -> 193.16 MB (+7.67 MB over 41,350 requests)
  Fault Injection Resilience:   100.0% safe pass across 50 chaos trials (5 scenarios x 10 reps)
  Document Ingestion Pipeline:  100/100 Jobs Verified (90 completed, 10 expected failures caught)
========================================================================================
```

---

## 3. High-Level Summary of Benchmark Reports

### Report 1: Grounded RAG Quality Evaluation ([`rag_evaluation.md`](rag_evaluation.md))
- **Scope:** Evaluated across the expanded **200-case versioned dataset** (150 validation, 50 holdout) with zero data leakage.
- **Results:** Achieved `Recall@5` of **0.9831**, `Hit Rate@5` of **1.000**, `MRR` of **1.000**, and `nDCG@5` of **0.9869**.
- **Fidelity:** Answer correctness achieved **95.95%** on deterministic reference-fact matching; citation support reached **88.51%** with verified verbatim quotes.
- **Safety:** **100.0% abstention accuracy** across all 52 unanswerable, ambiguous, and out-of-scope queries (`quality_result: "insufficient_evidence"`).

### Report 2: Retrieval Mode Comparison ([`retrieval_comparison.md`](retrieval_comparison.md))
- **Scope:** Compared Keyword-Only, Semantic-Only (Gemini Embeddings), and Hybrid (Reciprocal Rank Fusion, $k=60$) on identical queries.
- **Findings:**
  - Keyword search provides sub-millisecond execution ($< 6\text{ ms}$ p95) and excels on exact alphanumeric tokens (`40P01`, `exit code 137`, `ndots:5`, `SlowDown`).
  - Semantic search bridges vocabulary gaps and natural language symptom descriptions.
  - Hybrid RRF fuses both rank signals, passing the regression gate with **zero quality regressions** against the baseline and providing resilience against third-party API outages.

### Report 3: Load, Latency & Capacity ([`load_and_latency.md`](load_and_latency.md))
- **Scope:** Tested at 10, 25, and 50 concurrent users (3 runs x 1,000 requests each; 9,000 requests), plus a **10-minute continuous sustained load test** (41,350 requests) and 10 live cloud provider calls.
- **Findings:**
  - Discrete concurrency: 10 users: **75.96 RPS** (p50: 61.7 ms); 25 users: **65.90 RPS** (p50: 169.8 ms); 50 users: **66.30 RPS** (p50: 335.7 ms).
  - Sustained stress test: **68.89 RPS** sustained for 600.2 seconds (41,350 requests) with **0 errors (0.000%)** and $<4.1\%$ memory variation ($+7.67\text{ MB}$ RSS).
  - Real-provider test: Cloud LLM generation averages ~14.8–16.8 seconds, demonstrating that the internal architecture (FastAPI, SQLite/NeonDB, sliding-window limiter) contributes $< 1\%$ to total end-to-end latency.

### Report 4: Failure Injection & Chaos Engineering ([`failure_injection.md`](failure_injection.md))
- **Scope:** 50 automated fault injection trials across 5 failure scenarios (10 repetitions each).
- **Findings:**
  - **Provider Timeout:** 10/10 trials successfully failed over from Groq to Gemini in 1.14 ms average latency.
  - **Dual Provider Outage:** 10/10 trials safely caught `RoutingError`, incremented circuit breaker failures, and returned sanitized reason codes.
  - **Database Connection Failure:** 10/10 trials failed closed with transaction rollback and zero state corruption.
  - **Vector Store Outage:** 10/10 trials cleanly wrapped `SearchProviderError` without process crashes.
  - **Indexing Retries:** 10/10 trials verified exponential backoff ($0.1\text{s} \to 0.2\text{s}$) and safe `RATE_LIMITED` termination.

### Report 5: Ingestion Pipeline Reliability ([`ingestion_reliability.md`](ingestion_reliability.md))
- **Scope:** 100 document ingestion jobs tested across Markdown (.md), Plain Text (.txt), Adobe PDF (.pdf via PyMuPDF), JSON Lines (.jsonl), and 10 intentional failure edge cases.
- **Findings:**
  - **100% Pipeline Accuracy:** 90/90 valid documents completed successfully; 10/10 invalid documents accurately caught (corrupted PDF binaries, malformed JSONL, oversized uploads $>10\text{MB}$, empty documents, disallowed MIME types).
  - **Speed:** Mean processing latency of **0.56 ms** across all 100 jobs (p95: 2.63 ms).
  - **Safety:** Sanitized error codes (`INVALID_DOCUMENT`, `FILE_TOO_LARGE`, `EMPTY_DOCUMENT`, `UNSUPPORTED_MEDIA_TYPE`) ensure zero client data or stack traces are leaked.

---

## 4. Benchmark Reports Index

All detailed benchmark reports with reproducibility commands and raw data tables are available in the repository:

1. **[RAG Quality Evaluation Report](rag_evaluation.md)**
2. **[Retrieval Comparison Report: Keyword vs Semantic vs Hybrid](retrieval_comparison.md)**
3. **[Load, Latency & Capacity Benchmark Report](load_and_latency.md)**
4. **[Failure Injection & Chaos Engineering Report](failure_injection.md)**
5. **[Document Ingestion Reliability Benchmark Report](ingestion_reliability.md)**

---

## 5. Production Readiness Verdict

IncidentIQ satisfies the rigorous quality, reliability, and security bars expected of an enterprise AI engineering platform in 2026. The evaluation harness and benchmarks are 100% reproducible via single-command CLI scripts located in `backend/scripts/`.
