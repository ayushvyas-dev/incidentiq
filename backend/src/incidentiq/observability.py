"""Small process-local metrics registry and optional OpenTelemetry tracing."""

from collections import deque
from collections.abc import Iterator
from contextlib import contextmanager
from math import ceil
from threading import Lock
from time import time


class Metrics:
    # shortcut: metrics are per process and retain one hour, use a shared backend when scaling workers.
    def __init__(self) -> None:
        self._lock = Lock()
        self._requests: deque[tuple[float, float, int]] = deque(maxlen=100_000)
        self._counters: dict[tuple[str, str], float] = {}
        self._llm: dict[str, float] = {
            "input_tokens": 0, "output_tokens": 0, "estimated_cost_usd": 0,
            "fallback_count": 0,
        }
        self._llm_events: deque[tuple[float, int, int, float, int]] = deque(maxlen=100_000)
        self._retrieval_events: deque[tuple[float, int, bool]] = deque(maxlen=100_000)

    def increment(self, name: str, label: str = "all", value: float = 1) -> None:
        with self._lock:
            key = (name, label)
            self._counters[key] = self._counters.get(key, 0) + value

    def observe_stage(self, stage: str, duration_ms: float) -> None:
        self.increment("stage_duration_ms_sum", stage, duration_ms)
        self.increment("stage_duration_ms_count", stage)

    def request(self, duration_ms: float, status_code: int) -> None:
        with self._lock:
            self._requests.append((time(), duration_ms, status_code))

    def retrieval(self, candidates: int, reranker_used: bool = False) -> None:
        with self._lock:
            self._retrieval_events.append((time(), candidates, reranker_used))

    def llm(self, *, input_tokens=None, output_tokens=None, cost=None, fallback=False) -> None:
        with self._lock:
            self._llm_events.append((time(), input_tokens or 0, output_tokens or 0,
                                     cost or 0, int(fallback)))
            for key, value in (("input_tokens", input_tokens), ("output_tokens", output_tokens),
                               ("estimated_cost_usd", cost)):
                if value is not None:
                    self._llm[key] += value
            self._llm["fallback_count"] += int(fallback)

    def summary(self, window_seconds: int = 86_400) -> dict:
        cutoff = time() - window_seconds
        with self._lock:
            samples = [(duration, status) for timestamp, duration, status in self._requests if timestamp >= cutoff]
            durations = sorted(duration for duration, _ in samples)
            total = len(samples)
            success = sum(status < 400 for _, status in samples)
            retrievals = [event for event in self._retrieval_events if event[0] >= cutoff]
            llm_events = [event for event in self._llm_events if event[0] >= cutoff]

        def percentile(percent: float):
            if not durations:
                return None
            return round(durations[min(len(durations) - 1, ceil(len(durations) * percent) - 1)])

        return {
            "requests": {"total": total, "success_rate": success / total if total else 0,
                         "error_rate": (total - success) / total if total else 0},
            "latency_ms": {"p50": percentile(.50), "p95": percentile(.95), "p99": percentile(.99)},
            "llm": {"input_tokens": sum(row[1] for row in llm_events),
                    "output_tokens": sum(row[2] for row in llm_events),
                    "estimated_cost_usd": sum(row[3] for row in llm_events),
                    "fallback_count": sum(row[4] for row in llm_events)},
            "retrieval": {"average_candidates": sum(row[1] for row in retrievals) / len(retrievals) if retrievals else 0,
                          "reranker_usage_rate": sum(row[2] for row in retrievals) / len(retrievals) if retrievals else 0},
        }

    def prometheus(self) -> str:
        with self._lock:
            counters = dict(self._counters)
            requests = list(self._requests)
            llm = dict(self._llm)
        lines = ["# TYPE incidentiq_requests_total counter"]
        statuses: dict[str, int] = {}
        for _, _, status in requests:
            key = f"{status // 100}xx"
            statuses[key] = statuses.get(key, 0) + 1
        lines.extend(f'incidentiq_requests_total{{status_class="{key}"}} {value}' for key, value in sorted(statuses.items()))
        lines.extend(["# TYPE incidentiq_request_duration_ms histogram",
                      f"incidentiq_request_duration_ms_count {len(requests)}",
                      f"incidentiq_request_duration_ms_sum {sum(row[1] for row in requests):.3f}"])
        for bound in (50, 100, 250, 500, 1000, 2500, 5000, float("inf")):
            label = "+Inf" if bound == float("inf") else str(bound)
            count = sum(row[1] <= bound for row in requests)
            lines.append(f'incidentiq_request_duration_ms_bucket{{le="{label}"}} {count}')
        for (name, label), value in sorted(counters.items()):
            lines.append(f'incidentiq_{name}{{result="{label}"}} {value:g}')
        for name, value in llm.items():
            lines.append(f"incidentiq_{name} {value:g}")
        return "\n".join(lines) + "\n"


METRICS = Metrics()

try:
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    _provider = TracerProvider(resource=Resource.create({"service.name": "incidentiq"}))
    if __import__("os").getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
        _provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(_provider)
    _tracer = trace.get_tracer("incidentiq")

    @contextmanager
    def span(name: str) -> Iterator[object]:
        with _tracer.start_as_current_span(name) as current:
            yield current
except ImportError:
    @contextmanager
    def span(name: str) -> Iterator[None]:
        yield None
