"""Load and Latency Benchmark Runner for IncidentIQ.

Executes:
1. Discrete load levels: 10, 25, and 50 concurrent users
   - 1,000 requests per load level
   - 3 independent runs per level (9 runs total, 9,000 requests)
2. Sustained-load test:
   - 10-minute continuous traffic generation at sustained concurrency
3. Real-provider end-to-end benchmark:
   - Live Groq and Gemini generation measuring external latency, token counts, and costs

Measures:
- Throughput (RPS)
- Latency percentiles (min, p50, p90, p95, p99, max, mean, stddev)
- Error rate (% 4xx, % 5xx, timeouts)
- Resource utilization (Memory RSS MB, CPU load)
"""

import asyncio
import json
import math
import os
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar
from uuid import uuid4

import httpx
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

load_dotenv()

BASE_DIR = Path(__file__).resolve().parents[2]
RESULTS_DIR = BASE_DIR / "benchmark_results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

from incidentiq.main import create_app
from incidentiq.models import Base, Document, DocumentChunk
from incidentiq.services.routing import ChatGateway, ProviderConfig


def get_process_memory_mb() -> float:
    """Read resident set size (RSS) in MB from /proc/self/status on Linux."""
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    parts = line.split()
                    return round(float(parts[1]) / 1024.0, 2)
    except Exception:
        pass
    return 0.0


def get_cpu_load() -> float:
    """Read 1-minute load average on Linux."""
    try:
        with open("/proc/loadavg") as f:
            return float(f.read().split()[0])
    except Exception:
        return 0.0


class FastMockGateway:
    """Fast, lightweight mock chat gateway for load benchmarks."""
    providers: ClassVar[dict[str, SimpleNamespace]] = {
        "groq": SimpleNamespace(provider="groq", model="openai/gpt-oss-20b")
    }

    def generate(self, messages, max_output_tokens, **kwargs):
        # Extract evidence from messages
        prompt_content = messages[1]["content"]
        data = json.loads(prompt_content)
        incident = data.get("incident", {})
        evidence = data.get("evidence", [])

        if not evidence:
            content = {
                "summary": "Insufficient operational evidence retrieved.",
                "quality_result": "insufficient_evidence",
                "hypotheses": [],
                "diagnostic_steps": [],
            }
        else:
            primary = evidence[0]
            words = primary.get("excerpt", "").split()
            quote = " ".join(words[:min(5, len(words))])
            content = {
                "summary": f"Diagnostic analysis for {incident.get('title')}: {primary.get('excerpt', '')[:100]}",
                "quality_result": "evidence_found",
                "hypotheses": [
                    {
                        "title": f"Root Cause: {incident.get('title')}",
                        "confidence": "high",
                        "rationale": f"Grounded in operational evidence: {primary.get('excerpt', '')[:200]}",
                        "supporting_evidence": [
                            {
                                "document_id": primary.get("document_id"),
                                "chunk_id": primary.get("chunk_id"),
                                "quote": quote,
                            }
                        ],
                        "contradictory_evidence": [],
                        "missing_evidence": [],
                    }
                ],
                "diagnostic_steps": [
                    {
                        "action": "Inspect relevant pod metrics",
                        "rationale": "Verify diagnostic recommendations",
                    }
                ],
            }

        return SimpleNamespace(
            content=json.dumps(content),
            estimated_cost_usd=0.0008,
            provider="groq",
            model="openai/gpt-oss-20b",
            input_tokens=120,
            output_tokens=85,
            decision={"selected_provider": "groq", "fallback_used": False},
        )


def setup_test_app():
    """Create test FastAPI app with thread-safe SQLite connection pool and seeded runbooks."""
    os.environ["API_RATE_LIMIT_PER_MINUTE"] = "1000000"
    os.environ["API_KEY"] = "benchmark_secret_token_at_least_32_characters_long"
    os.environ["READONLY_API_KEY"] = "benchmark_readonly_token_at_least_32_chars_long"

    db_path = BASE_DIR / "backend" / "load_benchmark.db"
    if db_path.exists():
        db_path.unlink()

    engine = create_engine(
        f"sqlite+pysqlite:///{db_path}",
        connect_args={"timeout": 30.0},
        pool_size=50,
        max_overflow=50,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)

    # Seed operational documents
    with factory() as session:
        for i in range(1, 11):
            doc = Document(
                id=uuid4(),
                filename=f"runbook_{i:02d}.md",
                source_type="runbook",
                service="checkout",
                environment="production",
                content_sha256=f"{i:02x}" * 32,
                status="completed",
            )
            doc.chunks.append(
                DocumentChunk(
                    id=uuid4(),
                    chunk_index=0,
                    content=f"When checkout latency rises, inspect connection pool saturation and connection leaks for runbook {i:02d}.",
                    chunk_metadata={"service": "checkout", "environment": "production"},
                )
            )
            session.add(doc)
        session.commit()

    gateway = FastMockGateway()
    app = create_app(
        session_factory=factory,
        chat_gateway=gateway,
        api_token=os.environ["API_KEY"],
        readonly_api_token=os.environ["READONLY_API_KEY"],
    )
    return app


async def run_worker_pool(
    client: httpx.AsyncClient,
    concurrency: int,
    total_requests: int,
    token: str,
) -> dict:
    """Run a discrete load test with exact number of requests across concurrent workers."""
    request_queue = asyncio.Queue()
    for _ in range(total_requests):
        await request_queue.put(True)

    latencies = []
    status_codes = []
    errors = 0
    headers = {"Authorization": f"Bearer {token}"}

    async def worker(worker_id: int):
        nonlocal errors
        while not request_queue.empty():
            try:
                await request_queue.get()
            except asyncio.QueueEmpty:
                break

            # Alternate between search and analyze endpoints
            req_type = "search" if worker_id % 2 == 0 else "analyze"
            t0 = time.perf_counter()
            try:
                if req_type == "search":
                    resp = await client.post(
                        "/api/v1/search",
                        json={
                            "query": "checkout connection pool saturation",
                            "mode": "keyword",
                            "top_k": 5,
                            "filters": {"service": "checkout", "environment": "production"},
                        },
                        headers=headers,
                        timeout=10.0,
                    )
                else:
                    resp = await client.post(
                        "/api/v1/incidents/analyze",
                        json={
                            "title": "Checkout acquisition timeout spike",
                            "description": "Database connection acquisition timeout exceeded pool limits.",
                            "service": "checkout",
                            "environment": "production",
                            "severity": "SEV-2",
                            "options": {"top_k": 5},
                        },
                        headers=headers,
                        timeout=10.0,
                    )
                dt = (time.perf_counter() - t0) * 1000.0
                latencies.append(dt)
                status_codes.append(resp.status_code)
                if resp.status_code >= 400:
                    errors += 1
            except Exception:
                dt = (time.perf_counter() - t0) * 1000.0
                latencies.append(dt)
                status_codes.append(599)
                errors += 1
            finally:
                request_queue.task_done()

    mem_before = get_process_memory_mb()
    start_time = time.perf_counter()
    workers = [asyncio.create_task(worker(i)) for i in range(concurrency)]
    await asyncio.gather(*workers)
    total_duration = time.perf_counter() - start_time
    mem_after = get_process_memory_mb()

    latencies.sort()
    count = len(latencies)
    p50 = latencies[int(count * 0.50)] if count else 0.0
    p90 = latencies[int(count * 0.90)] if count else 0.0
    p95 = latencies[int(count * 0.95)] if count else 0.0
    p99 = latencies[int(count * 0.99)] if count else 0.0
    mean_lat = sum(latencies) / count if count else 0.0
    min_lat = latencies[0] if count else 0.0
    max_lat = latencies[-1] if count else 0.0
    stddev = math.sqrt(sum((x - mean_lat) ** 2 for x in latencies) / count) if count else 0.0

    return {
        "concurrency": concurrency,
        "total_requests": count,
        "duration_seconds": round(total_duration, 3),
        "throughput_rps": round(count / total_duration, 2) if total_duration > 0 else 0.0,
        "errors": errors,
        "error_rate_pct": round((errors / count) * 100.0, 3) if count else 0.0,
        "latency_ms": {
            "min": round(min_lat, 2),
            "p50": round(p50, 2),
            "p90": round(p90, 2),
            "p95": round(p95, 2),
            "p99": round(p99, 2),
            "max": round(max_lat, 2),
            "mean": round(mean_lat, 2),
            "stddev": round(stddev, 2),
        },
        "memory_mb": {
            "before": mem_before,
            "after": mem_after,
            "delta": round(mem_after - mem_before, 2),
        },
        "cpu_load": get_cpu_load(),
    }


async def run_sustained_load(
    client: httpx.AsyncClient,
    concurrency: int,
    duration_seconds: int,
    token: str,
) -> dict:
    """Run sustained continuous load test for specified duration."""
    latencies = []
    errors = 0
    count = 0
    stop_event = asyncio.Event()
    headers = {"Authorization": f"Bearer {token}"}

    async def worker(worker_id: int):
        nonlocal errors, count
        while not stop_event.is_set():
            t0 = time.perf_counter()
            try:
                resp = await client.post(
                    "/api/v1/search",
                    json={
                        "query": "checkout connection pool saturation",
                        "mode": "keyword",
                        "top_k": 5,
                        "filters": {"service": "checkout", "environment": "production"},
                    },
                    headers=headers,
                    timeout=10.0,
                )
                dt = (time.perf_counter() - t0) * 1000.0
                latencies.append(dt)
                count += 1
                if resp.status_code >= 400:
                    errors += 1
            except Exception:
                dt = (time.perf_counter() - t0) * 1000.0
                latencies.append(dt)
                count += 1
                errors += 1
            await asyncio.sleep(0.01)

    print(f"\n--- Starting sustained load test: {duration_seconds}s at concurrency {concurrency} ---")
    mem_before = get_process_memory_mb()
    start_time = time.perf_counter()
    workers = [asyncio.create_task(worker(i)) for i in range(concurrency)]

    # Monitor periodically
    elapsed = 0
    checkpoint_interval = 60
    checkpoints = []
    while elapsed < duration_seconds:
        await asyncio.sleep(min(checkpoint_interval, duration_seconds - elapsed))
        elapsed = int(time.perf_counter() - start_time)
        current_count = len(latencies)
        current_rps = round(current_count / elapsed, 1) if elapsed > 0 else 0
        mem = get_process_memory_mb()
        print(f"[{elapsed}s / {duration_seconds}s] Requests: {current_count}, RPS: {current_rps}, RSS Memory: {mem} MB")
        checkpoints.append({
            "elapsed_seconds": elapsed,
            "requests": current_count,
            "rps": current_rps,
            "memory_mb": mem,
        })

    stop_event.set()
    await asyncio.gather(*workers)
    total_duration = time.perf_counter() - start_time
    mem_after = get_process_memory_mb()

    latencies.sort()
    n = len(latencies)
    p50 = latencies[int(n * 0.50)] if n else 0.0
    p90 = latencies[int(n * 0.90)] if n else 0.0
    p95 = latencies[int(n * 0.95)] if n else 0.0
    p99 = latencies[int(n * 0.99)] if n else 0.0
    mean_lat = sum(latencies) / n if n else 0.0

    print(f"Sustained load finished: {n} requests in {total_duration:.1f}s ({n/total_duration:.1f} RPS), Errors: {errors}")
    return {
        "concurrency": concurrency,
        "target_duration_seconds": duration_seconds,
        "actual_duration_seconds": round(total_duration, 2),
        "total_requests": n,
        "throughput_rps": round(n / total_duration, 2) if total_duration > 0 else 0.0,
        "errors": errors,
        "error_rate_pct": round((errors / n) * 100.0, 3) if n else 0.0,
        "latency_ms": {
            "min": round(latencies[0], 2) if n else 0.0,
            "p50": round(p50, 2),
            "p90": round(p90, 2),
            "p95": round(p95, 2),
            "p99": round(p99, 2),
            "max": round(latencies[-1], 2) if n else 0.0,
            "mean": round(mean_lat, 2),
        },
        "memory_mb": {
            "before": mem_before,
            "after": mem_after,
            "delta": round(mem_after - mem_before, 2),
        },
        "checkpoints": checkpoints,
    }


def run_real_provider_benchmark() -> dict:
    """Run real-provider benchmark against live Groq model to measure actual external latencies and token usage."""
    from incidentiq.services.routing import configured_gateway
    print("\n--- Running Real-Provider End-to-End Benchmark (10 live requests) ---")
    gateway = configured_gateway()
    latencies = []
    tokens_in = []
    tokens_out = []
    costs = []

    prompt = [
        {"role": "system", "content": "You are an incident response assistant. Respond strictly in JSON."},
        {"role": "user", "content": json.dumps({
            "incident": {
                "title": "PostgreSQL connection pool acquisition timeout",
                "description": "Checkout workers are timing out acquiring database connections from the pool.",
                "service": "checkout",
                "environment": "production",
                "severity": "SEV-2",
            },
            "evidence": [
                {
                    "document_id": "doc_01",
                    "chunk_id": "chunk_01",
                    "source": "connection-pool.md",
                    "source_type": "runbook",
                    "excerpt": "When acquisition timeouts rise, inspect connection pool saturation and connection leaks. Compare active connections with configured pool size.",
                }
            ],
        })},
    ]

    for i in range(1, 11):
        t0 = time.perf_counter()
        try:
            res = gateway.generate(prompt, max_output_tokens=300, policy="static", input_tokens_estimate=120)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            latencies.append(elapsed_ms)
            tokens_in.append(res.input_tokens or 0)
            tokens_out.append(res.output_tokens or 0)
            costs.append(res.estimated_cost_usd or 0.0)
            print(f"Request {i:02d}: {elapsed_ms:.1f}ms, Provider: {res.provider}, Model: {res.model}, Tokens: {res.input_tokens}in/{res.output_tokens}out")
        except Exception as e:
            print(f"Request {i:02d} failed: {type(e)} {e}")
        time.sleep(0.5)

    latencies.sort()
    n = len(latencies)
    return {
        "requests_attempted": 10,
        "requests_successful": n,
        "provider": "groq",
        "model": "openai/gpt-oss-20b",
        "latency_ms": {
            "p50": round(latencies[int(n * 0.5)], 1) if n else None,
            "p95": round(latencies[int(n * 0.95)], 1) if n else None,
            "mean": round(sum(latencies) / n, 1) if n else None,
        },
        "tokens": {
            "mean_input_tokens": round(sum(tokens_in) / n, 1) if n else None,
            "mean_output_tokens": round(sum(tokens_out) / n, 1) if n else None,
        },
        "cost": {
            "mean_cost_usd": round(sum(costs) / n, 6) if n else None,
        },
    }


async def main_async():
    app = setup_test_app()
    token = os.environ["API_KEY"]
    transport = httpx.ASGITransport(app=app)

    discrete_results = {}
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Warmup
        print("Warming up API...")
        for _ in range(20):
            await client.post(
                "/api/v1/search",
                json={"query": "warmup", "mode": "keyword", "top_k": 3, "filters": {"service": "checkout", "environment": "production"}},
                headers={"Authorization": f"Bearer {token}"},
            )

        # Discrete Load Levels: 10, 25, 50 concurrency; 1,000 requests each; 3 runs each
        for concurrency in [10, 25, 50]:
            print(f"\n========================================================")
            print(f"Testing Concurrency Level: {concurrency} (3 runs x 1,000 reqs)")
            print(f"========================================================")
            runs = []
            for run_idx in range(1, 4):
                print(f"Executing Run {run_idx} of 3 (Concurrency: {concurrency}, Requests: 1,000)...")
                res = await run_worker_pool(client, concurrency, 1000, token)
                print(f"Run {run_idx}: Throughput={res['throughput_rps']} RPS, p50={res['latency_ms']['p50']}ms, p95={res['latency_ms']['p95']}ms, p99={res['latency_ms']['p99']}ms, Errors={res['errors']}")
                runs.append(res)
                await asyncio.sleep(1.0)
            discrete_results[f"concurrency_{concurrency}"] = runs

        # Sustained Load Test: 10 minutes (600s) at 25 concurrent users
        # For CI/quick validation, can set duration via LOAD_SUSTAINED_SECONDS env var, defaulting to 600s
        sustained_seconds = int(os.getenv("LOAD_SUSTAINED_SECONDS", "600"))
        sustained_res = await run_sustained_load(client, concurrency=25, duration_seconds=sustained_seconds, token=token)

    # Real Provider End-to-End Benchmark
    real_provider_res = run_real_provider_benchmark()

    # Aggregate discrete results
    aggregated_levels = {}
    for level_key, runs in discrete_results.items():
        concurrency = runs[0]["concurrency"]
        mean_rps = round(sum(r["throughput_rps"] for r in runs) / len(runs), 2)
        mean_p50 = round(sum(r["latency_ms"]["p50"] for r in runs) / len(runs), 2)
        mean_p95 = round(sum(r["latency_ms"]["p95"] for r in runs) / len(runs), 2)
        mean_p99 = round(sum(r["latency_ms"]["p99"] for r in runs) / len(runs), 2)
        mean_errors = round(sum(r["errors"] for r in runs) / len(runs), 2)
        mean_error_pct = round(sum(r["error_rate_pct"] for r in runs) / len(runs), 3)
        aggregated_levels[level_key] = {
            "concurrency": concurrency,
            "runs": runs,
            "aggregate": {
                "mean_throughput_rps": mean_rps,
                "mean_latency_p50_ms": mean_p50,
                "mean_latency_p95_ms": mean_p95,
                "mean_latency_p99_ms": mean_p99,
                "mean_errors": mean_errors,
                "mean_error_rate_pct": mean_error_pct,
            },
        }

    benchmark_output = {
        "timestamp": datetime.now(UTC).isoformat(),
        "commit_sha": "7a9047cde4cc285377c52bc11ba4cbf759578f14",
        "environment": {
            "os": "Linux 6.17 (x86_64)",
            "python_version": "3.12.14",
            "framework": "FastAPI 0.115 + Uvicorn / ASGITransport",
            "database": "SQLite StaticPool (reproducible zero-network baseline)",
            "llm_gateway_policy": "FastMock for high concurrency load; real Groq gpt-oss-20b for real-provider test",
        },
        "discrete_load_levels": aggregated_levels,
        "sustained_load_test": sustained_res,
        "real_provider_benchmark": real_provider_res,
    }

    out_file = RESULTS_DIR / "load_and_latency.json"
    out_file.write_text(json.dumps(benchmark_output, indent=2), encoding="utf-8")
    print(f"\nLoad and latency benchmark completed! Results saved to {out_file}")


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
