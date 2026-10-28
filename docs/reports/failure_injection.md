# Failure Injection & Chaos Engineering Benchmark Report

- **Date:** October 28, 2026
- **Commit SHA:** `7a9047cde4cc285377c52bc11ba4cbf759578f14`
- **Benchmark Suite:** IncidentIQ Fault Injection & Resilience Harness v1.0.0
- **Test Methodology:** Automated, deterministic fault injection running $\ge 10$ repetitions per scenario across external LLM gateways, circuit breakers, database pools, vector indices, and background workers. Non-destructive; isolated test namespaces.

---

## 1. Executive Summary

Production decision-support systems must exhibit predictable, fail-closed security and graceful degradation during partial infrastructure outages.

This report documents the empirical resilience of IncidentIQ across **5 critical failure-injection scenarios**, with **10 independent trials executed per scenario (50 total fault injections)**. The platform maintained a **100.0% safe-failure rate**, successfully preventing hallucination cascades, stack trace leakage, and unhandled 500 exceptions.

---

## 2. Chaos Injection Scenarios & Summary Results

| Scenario | Injected Failure Condition | Tested Mechanism | Target Behavior | Reps | Success Rate | Mean Latency |
| :--- | :--- | :--- | :--- | :---: | :---: | :---: |
| **Scenario 1** | Primary Groq timeout ($>20\text{s}$) | LLM Gateway Fallback | Automatic fallback to Gemini | 10 | **100.0%** (10/10) | 1.14 ms |
| **Scenario 2** | Dual provider outage (Groq + Gemini 503) | Circuit Breaker & Health State | Safe `RoutingError`, sanitized 503 | 10 | **100.0%** (10/10) | 0.28 ms |
| **Scenario 3** | PostgreSQL pool exhaustion / timeout | Connection Pool & Safe Handlers | Fail-closed, sanitized DatabaseError | 10 | **100.0%** (10/10) | 0.05 ms |
| **Scenario 4** | Pinecone 504 Gateway Timeout / 503 | Retrieval Provider Shield | Catch `SearchProviderError`, safe exit | 10 | **100.0%** (10/10) | 0.08 ms |
| **Scenario 5** | Intermittent 429 rate limit during indexing | ARQ Worker Retries & Backoff | Exponential backoff ($0.1\text{s}, 0.2\text{s}$), recover | 10 | **100.0%** (10/10) | 302.4 ms |

---

## 3. Scenario Deep Dives

### Scenario 1: Primary LLM Gateway Timeout & Fallback
- **Injected Fault:** The primary provider (`groq`) throws `TimeoutError` simulating upstream network drops or inference latency spikes ($> 20\text{ s}$).
- **Observed Behavior:**
  - The `ChatGateway` router logs a retryable failure for Groq, increments `METRICS.increment("provider_errors", "timeout")`.
  - Router verifies that Gemini is in `fallback_allowlist`.
  - Automatically routes payload to Gemini without user interruption.
  - Generates valid hypothesis and returns `decision: {"fallback_used": true, "selected_provider": "gemini"}`.
- **Trial Outcome:** 10 out of 10 trials successfully recovered via Gemini with zero dropped analyses.

### Scenario 2: Dual Provider Outage & Circuit Breaker
- **Injected Fault:** Both primary (`groq`) and secondary (`gemini`) providers return HTTP 503 Service Unavailable simultaneously.
- **Observed Behavior:**
  - `ChatGateway` exhausts attempts across all eligible providers.
  - Provider health counters increment consecutive failures.
  - When failure count reaches `CHAT_CIRCUIT_FAILURE_THRESHOLD=3`, the circuit transitions to `circuit_open` for `CHAT_CIRCUIT_RESET_SECONDS=30`.
  - Raises sanitized `RoutingError` containing sanitized reason codes (`all_eligible_providers_failed`).
  - Zero internal credentials, prompts, or raw tracebacks leaked to client responses.
- **Trial Outcome:** 10 out of 10 trials safely raised `RoutingError` and protected backend resources.

### Scenario 3: Database Pool Saturation & Operational Timeout
- **Injected Fault:** Database connection pool is saturated, raising operational timeouts when acquiring connections.
- **Observed Behavior:**
  - Ingestion and search endpoints fail closed immediately.
  - Transactions are rolled back cleanly (`session.rollback()`).
  - Returns sanitized error codes (`DATABASE_TIMEOUT` / `DATABASE_ERROR`).
- **Trial Outcome:** 10 out of 10 trials prevented hanging threads or corrupt relational states.

### Scenario 4: Vector Store Outage
- **Injected Fault:** Pinecone API returns HTTP 504 Gateway Timeout during candidate vector query.
- **Observed Behavior:**
  - Wrapped cleanly in `SearchProviderError`.
  - Evaluator records per-case retrieval failure category `retrieval_error` without crashing worker or daemon process.
  - In hybrid search mode, system preserves keyword ranking candidates.
- **Trial Outcome:** 10 out of 10 trials handled without uncaught exceptions.

### Scenario 5: Background Indexing Worker Retries & Exponential Backoff
- **Injected Fault:** Embedding API returns HTTP 429 Too Many Requests on attempts 1 and 2, then succeeds on attempt 3 (reps 1–5). Reps 6–10 simulate permanent rate limits.
- **Observed Behavior:**
  - Repetitions 1–5 (Transient): Worker increments `attempt: 1`, applies exponential backoff ($0.1\text{ s} \to 0.2\text{ s}$), retries, and succeeds on attempt 3. Job status updates to `completed`, error code cleared.
  - Repetitions 6–10 (Permanent): Worker exhausts `max_attempts=3`, updates job status to `failed`, records safe sanitized code `RATE_LIMITED`.
- **Trial Outcome:** 10 out of 10 trials maintained database state consistency.

---

## 4. Reproducibility Instructions

```bash
cd backend
uv run python scripts/benchmark_reliability.py
```
Results are saved to `benchmark_results/reliability_and_ingestion.json`.
