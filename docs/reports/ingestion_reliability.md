# Document Ingestion Reliability & Stress Benchmark Report

- **Date:** October 28, 2026
- **Commit SHA:** `7a9047cde4cc285377c52bc11ba4cbf759578f14`
- **Benchmark Suite:** IncidentIQ Document Ingestion Pipeline Benchmark
- **Test Corpus:** 100 Document Ingestion Jobs across all supported MIME types and intentional failure edge cases.

---

## 1. Executive Summary

IncidentIQ indexes mission-critical operational documentation across heterogeneous formats: Markdown (`.md`), Plain Text (`.txt`), Adobe PDF (`.pdf`), and JSON Lines (`.jsonl`).

This benchmark evaluated the document parsing, chunking, sanitization, and error-handling pipeline across **100 document ingestion jobs**, comprising **90 valid documents** across all four supported formats and **10 expected failure edge cases** (corrupted binaries, malformed JSONL, oversized uploads, empty files, and unsupported MIME types).

### Key Empirical Findings
- **Overall Pipeline Accuracy:** **100.0%** (90/90 valid documents completed successfully; 10/10 invalid documents accurately flagged and safely rejected).
- **Zero Unhandled Server Exceptions:** All failure cases were intercepted at the input validation layer with safe, standardized error codes.
- **Mean Processing Latency:** **0.56 ms** across all 100 jobs (p50: 0.01 ms, p95: 2.63 ms, p99: 7.83 ms).

---

## 2. Ingestion Job Breakdown & Results

| Ingestion Category | Sample Size | Expected Outcome | Actual Outcome | Status Code / Error Code | Pass Rate | Mean Latency |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Markdown (.md)** | 30 | Parse, chunk, extract headers | 30 Completed | HTTP 202 / Completed | **100.0%** | 0.02 ms |
| **Plain Text (.txt)** | 25 | Extract lines, sentence chunking | 25 Completed | HTTP 202 / Completed | **100.0%** | 0.01 ms |
| **PDF Documents (.pdf)** | 20 | PyMuPDF text & page extraction | 20 Completed | HTTP 202 / Completed | **100.0%** | 2.58 ms |
| **JSON Lines (.jsonl)** | 15 | Structured line-by-line event parsing | 15 Completed | HTTP 202 / Completed | **100.0%** | 0.03 ms |
| **Corrupted PDF Binary** | 2 | Reject unparseable xref / invalid header | 2 Failed | `INVALID_DOCUMENT` | **100.0%** | 0.04 ms |
| **Malformed JSONL** | 2 | Catch syntax error with line number | 2 Failed | `INVALID_DOCUMENT` | **100.0%** | 0.02 ms |
| **Oversized Upload ($>10\text{MB}$)** | 2 | Enforce `MAX_UPLOAD_MB` limit | 2 Failed | `FILE_TOO_LARGE` (413) | **100.0%** | 0.01 ms |
| **Empty / Whitespace-Only** | 2 | Reject zero-token payloads | 2 Failed | `EMPTY_DOCUMENT` (422) | **100.0%** | 0.01 ms |
| **Unsupported MIME Type** | 2 | Reject `.exe`, `.zip` binaries | 2 Failed | `UNSUPPORTED_MEDIA_TYPE` (415) | **100.0%** | 0.01 ms |
| **Total Benchmark** | **100** | — | — | — | **100.0%** | **0.56 ms** |

---

## 3. Ingestion Latency Distribution

Processing latency (parsing, chunking, sanitization, and SHA-256 deduplication) across the 100 document jobs:

```
Latency Percentiles (ms):
  Min:  0.01 ms
  p50:  0.01 ms
  p90:  1.45 ms
  p95:  2.63 ms
  p99:  7.83 ms
  Max:  9.42 ms
  Mean: 0.56 ms
```

PDF extraction via PyMuPDF represented the primary contributor to higher-percentile latencies (p95: 2.63 ms, max: 9.42 ms for multi-page documents), while text, markdown, and JSONL processing completed in $< 0.1\text{ ms}$.

---

## 4. Resilience and Error Handling Characteristics

### Safe Error Classification
In compliance with production security standards, raw Python exception tracebacks and client-supplied content are never persisted to stored job details or exposed in API error responses. The pipeline classifies all failures into safe, enumerated codes:
- `INVALID_DOCUMENT`: Malformed JSONL lines, corrupted PDF byte headers.
- `FILE_TOO_LARGE`: Upload payloads exceeding `MAX_UPLOAD_MB=10`.
- `EMPTY_DOCUMENT`: Zero-byte uploads or documents consisting solely of whitespace.
- `UNSUPPORTED_MEDIA_TYPE`: Disallowed MIME extensions.
- `RATE_LIMITED`: Upstream embedding API 429 quota exhaustion.
- `PROVIDER_TIMEOUT`: Upstream connection timeouts during vector upsert.

### Eventual Consistency & Recovery
NeonDB and Pinecone do not share distributed transactions. Eventual consistency is maintained via:
1. **Deterministic Vector IDs:** Chunks reuse stable relational UUIDs as Pinecone vector IDs.
2. **Crash Recovery on Startup (`requeue_pending_jobs`):** Worker restarts scan NeonDB for jobs committed before an API/Redis interruption and re-enqueue them automatically.
3. **Idempotent Re-Uploads:** Uploading duplicate content (`content_sha256`) reuses the existing canonical document and any active job.

---

## 5. Reproducibility Instructions

```bash
cd backend
uv run python scripts/benchmark_reliability.py
```
Output results are written to `benchmark_results/reliability_and_ingestion.json`.
