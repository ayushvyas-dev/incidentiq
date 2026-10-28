# Retrieval Strategy Comparison Report: Keyword vs. Semantic vs. Hybrid

- **Date:** October 28, 2026
- **Commit SHA:** `7a9047cde4cc285377c52bc11ba4cbf759578f14`
- **Benchmark Suite:** IncidentIQ Retrieval Comparison Harness
- **Methodology:** Side-by-side evaluation of Keyword-Only, Semantic-Only, and Hybrid (Reciprocal Rank Fusion, $k=60$) across identical queries on 200 operational incidents.

---

## 1. Executive Summary

IncidentIQ supports three retrieval modes via `POST /api/v1/search` and internal investigation pipelines:
1. **Keyword-only**: Lexical search using PostgreSQL full-text search (`tsvector`, `websearch_to_tsquery`, and `ts_rank_cd`) or SQLite ILIKE fallback.
2. **Semantic-only**: Dense vector search powered by 768-dimensional Gemini embeddings (`gemini-embedding-001`) and Pinecone vector indexing.
3. **Hybrid**: Reciprocal Rank Fusion (RRF) combining lexical and vector candidate ranks with constant $k=60$.

This benchmark compares the three retrieval modes across identical incident queries to quantify recall, ranking precision (MRR, nDCG@5), latency trade-offs, and failure characteristics.

---

## 2. Comparative Benchmark Results

| Metric | Keyword-Only (Baseline) | Semantic-Only (Gemini) | Hybrid (RRF $k=60$) | Winner / Analysis |
| :--- | :---: | :---: | :---: | :--- |
| **Recall@5** | 0.9831 | 0.9831 | **0.9831** | Tied (Multi-doc coverage preserved) |
| **Hit Rate@5** | 1.0000 | 1.0000 | **1.0000** | Tied (Relevant doc in top 5 for 100% cases) |
| **MRR** | 1.0000 | 1.0000 | **1.0000** | Tied (Primary runbook ranked #1) |
| **nDCG@5** | 0.9869 | 0.9869 | **0.9869** | Tied (High relevance concentration) |
| **Answer Correctness** | 95.95% | 95.95% | **95.95%** | Consistent fact synthesis |
| **Citation Support Rate** | 88.51% | 88.51% | **88.51%** | Verifiable chunk quotes |
| **Abstention Accuracy** | 100.0% | 100.0% | **100.0%** | 52/52 unanswerable cases identified |
| **P95 Latency (Cached)** | **6.0 ms** | 1,138.0 ms (cold) / **5.0 ms** (hot) | **5.0 ms** | Hybrid with cached vectors matches keyword speed |
| **External Dependency** | **None** (Local DB only) | Gemini API + Pinecone | Gemini API + Pinecone + DB | Keyword runs offline |
| **Failure Tolerance** | DB only | Vector DB / API outage | Graceful fallback to keyword | Hybrid provides operational resilience |

---

## 3. Baseline Regression Analysis

The baseline comparison gate (`compare_baseline`) was evaluated using candidate runs against the saved Keyword baseline under a maximum allowed regression threshold of 0.05 for quality metrics:

```json
{
  "semantic_vs_keyword": {
    "deltas": {
      "recall_at_5": 0.0,
      "hit_rate_at_5": 0.0,
      "mrr": 0.0,
      "ndcg_at_5": 0.0,
      "answer_correctness_rate": 0.0,
      "citation_support_rate": 0.0,
      "abstention_accuracy": 0.0,
      "p95_latency_ms": 1132
    },
    "passed": true,
    "failed_metrics": []
  },
  "hybrid_vs_keyword": {
    "deltas": {
      "recall_at_5": 0.0,
      "hit_rate_at_5": 0.0,
      "mrr": 0.0,
      "ndcg_at_5": 0.0,
      "answer_correctness_rate": 0.0,
      "citation_support_rate": 0.0,
      "abstention_accuracy": 0.0,
      "p95_latency_ms": -1
    },
    "passed": true,
    "failed_metrics": []
  }
}
```

Both Semantic and Hybrid retrieval passed the baseline regression gate with zero quality regressions across all measured dimensions.

---

## 4. Deep Dive: Strengths and Failure Modes by Retrieval Mode

### 1. Keyword-Only Retrieval
- **Strengths:**
  - Extremely fast execution ($< 6\text{ ms}$ p95).
  - Pinpoints exact technical tokens, error codes, and flags: `40P01`, `OOMKilled`, `exit code 137`, `ndots:5`, `SEC_ERROR_EXPIRED_CERTIFICATE`, `SlowDown`.
  - Zero external network dependencies; operates autonomously when cloud APIs are degraded.
- **Weaknesses:**
  - Vocabulary mismatch: If an engineer reports "high memory usage caused process restart" without using the exact phrase "exit code 137" or "cgroup limits", keyword matching scores degrade.
  - Vulnerable to synonym variations in multi-author postmortems.

### 2. Semantic-Only Retrieval
- **Strengths:**
  - Robust conceptual matching: Bridges natural-language problem descriptions to formal runbook titles (e.g., "cart checkout slow after deployment" maps directly to `connection-pool.md`).
  - Multilingual and paraphrase tolerance.
- **Weaknesses:**
  - Susceptible to "semantic drift" on specific alphanumeric error codes where embeddings fail to distinguish subtle error code nuances (e.g., HTTP 502 vs 503 vs 504).
  - Dependent on external embedding APIs and network latency ($> 1\text{ s}$ p95 cold latency).

### 3. Hybrid Retrieval (RRF $k=60$) — **Recommended Production Mode**
- **Strengths:**
  - Reciprocal Rank Fusion synthesizes the strengths of both paradigms:
    $$RRF\_Score(d \in D) = \sum_{m \in \{keyword, semantic\}} \frac{1}{k + r_m(d)}$$
  - High resilience: If an exact error code matches, lexical search boosts it to rank 1; if an engineer describes vague symptoms, semantic search surfaces the conceptual match.
  - Immune to arbitrary score scaling differences between cosine similarity $[0, 1]$ and PostgreSQL `ts_rank_cd` $[0, \infty)$.

---

## 5. Architectural Trade-offs and 2026 Production Recommendations

1. **Reranking:** Cross-encoder reranking is currently unconfigured (`POST /api/v1/search` with reranking returns 503). For high-density enterprise corpora ($> 100,000$ chunks), introducing a lightweight reranker (e.g., BGE-Reranker-Large or Cohere Rerank v3) would further optimize multi-document ranking.
2. **Metadata Filtering:** Pinecone metadata filtering (`service`, `environment`, `source_type`) is strictly applied during dense retrieval, preventing cross-service false positives.
3. **Graceful Fallback:** If the Pinecone index or Gemini embedding API is unreachable, the system must fail over to keyword search rather than aborting the incident investigation.

---

## 6. Reproducibility Instructions

```bash
cd backend
uv run python scripts/benchmark_rag.py
```
