"""Deterministic chat routing, bounded retries, fallback, and process-local health state."""

import math
import os
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from incidentiq.observability import METRICS, span
from incidentiq.services.analysis import ChatProvider, GroqChatProvider
from incidentiq.services.gemini import GeminiChatProvider


@dataclass(frozen=True)
class ProviderConfig:
    provider: str
    model: str
    client: ChatProvider
    input_cost_per_1k: float | None = None
    output_cost_per_1k: float | None = None
    estimated_latency_ms: int | None = None

    def __post_init__(self) -> None:
        for value in (self.input_cost_per_1k, self.output_cost_per_1k):
            if value is not None and (not math.isfinite(value) or value < 0):
                raise ValueError("provider token-cost estimates must be finite and non-negative")
        if self.estimated_latency_ms is not None and self.estimated_latency_ms < 1:
            raise ValueError("estimated latency must be positive")

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float | None:
        if self.input_cost_per_1k is None or self.output_cost_per_1k is None:
            return None
        return (input_tokens * self.input_cost_per_1k + output_tokens * self.output_cost_per_1k) / 1000


@dataclass
class ProviderHealth:
    failures: int = 0
    open_until: float = 0.0

    def available(self, now: float) -> bool:
        return now >= self.open_until


@dataclass(frozen=True)
class GatewayResult:
    content: str
    input_tokens: int | None
    output_tokens: int | None
    provider: str
    model: str
    estimated_cost_usd: float | None
    decision: dict


class RoutingError(RuntimeError):
    def __init__(self, decision: dict):
        super().__init__("No configured provider completed the request")
        self.decision = decision


class ChatGateway:
    def __init__(
        self,
        providers: Sequence[ProviderConfig],
        *,
        default_provider: str,
        fallback_allowlist: set[str] | None = None,
        max_attempts: int = 2,
        circuit_failure_threshold: int = 3,
        circuit_reset_seconds: float = 30,
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ):
        if max_attempts < 1 or max_attempts > 3:
            raise ValueError("max_attempts must be between 1 and 3")
        if circuit_failure_threshold < 1 or not math.isfinite(circuit_reset_seconds) or circuit_reset_seconds <= 0:
            raise ValueError("circuit breaker threshold and reset duration must be positive")
        self.providers = {provider.provider: provider for provider in providers}
        self.default_provider = default_provider
        self.fallback_allowlist = fallback_allowlist or set()
        self.max_attempts = max_attempts
        self.circuit_failure_threshold = circuit_failure_threshold
        self.circuit_reset_seconds = circuit_reset_seconds
        self.sleeper = sleeper
        self.clock = clock
        self.health = {name: ProviderHealth() for name in self.providers}
        self._health_lock = threading.Lock()

    def _eligible(
        self, policy: str, input_tokens: int, output_tokens: int,
        max_latency_ms: int | None, max_cost_usd: float | None,
        permitted_providers: set[str] | None = None,
    ) -> tuple[list[ProviderConfig], list[dict]]:
        if policy not in {"static", "rule_based"}:
            raise ValueError("policy must be static or rule_based")
        now = self.clock()
        allowed = {self.default_provider} | self.fallback_allowlist
        if permitted_providers is not None:
            allowed &= permitted_providers
        candidates = [p for p in self.providers.values() if p.provider in allowed]
        candidates.sort(key=lambda p: (p.provider != self.default_provider, p.provider))
        eligible = []
        excluded = [
            {"provider": p.provider, "model": p.model, "reason_codes": ["provider_not_allowed"]}
            for p in self.providers.values() if p.provider not in allowed
        ]
        for provider in candidates:
            reasons = []
            with self._health_lock:
                healthy = self.health[provider.provider].available(now)
            if not healthy:
                reasons.append("circuit_open")
            if max_latency_ms is not None and (
                provider.estimated_latency_ms is None or provider.estimated_latency_ms > max_latency_ms
            ):
                reasons.append("latency_budget_unavailable_or_exceeded")
            estimate = provider.estimate_cost(input_tokens, output_tokens)
            if max_cost_usd is not None and (estimate is None or estimate > max_cost_usd):
                reasons.append("cost_budget_unavailable_or_exceeded")
            if reasons:
                excluded.append({"provider": provider.provider, "model": provider.model, "reason_codes": reasons})
            else:
                eligible.append(provider)
        if policy == "rule_based":
            eligible.sort(key=lambda p: (
                p.estimate_cost(input_tokens, output_tokens) is None,
                p.estimate_cost(input_tokens, output_tokens) or float("inf"),
                p.estimated_latency_ms if p.estimated_latency_ms is not None else float("inf"),
                p.provider != self.default_provider,
                p.provider,
            ))
        elif eligible:
            default = next((p for p in eligible if p.provider == self.default_provider), None)
            if default:
                eligible = [default] + [p for p in eligible if p is not default]
        return eligible, excluded

    def simulate(
        self, *, policy: str, input_tokens: int, output_tokens: int,
        max_latency_ms: int | None = None, max_cost_usd: float | None = None,
        permitted_providers: set[str] | None = None,
    ) -> dict:
        eligible, excluded = self._eligible(
            policy, input_tokens, output_tokens, max_latency_ms, max_cost_usd, permitted_providers
        )
        estimates = [
            {
                "provider": p.provider, "model": p.model,
                "estimated_cost_usd": p.estimate_cost(input_tokens, output_tokens),
                "estimated_latency_ms": p.estimated_latency_ms,
            }
            for p in eligible
        ]
        selected = {"provider": eligible[0].provider, "model": eligible[0].model} if eligible else None
        return {"policy": policy, "eligible_models": estimates, "selected": selected, "excluded": excluded}

    def generate(
        self, messages: Sequence[dict[str, str]], max_output_tokens: int, *, policy: str,
        input_tokens_estimate: int, max_latency_ms: int | None = None,
        max_cost_usd: float | None = None, permitted_providers: set[str] | None = None,
    ) -> GatewayResult:
        candidates, excluded = self._eligible(
            policy, input_tokens_estimate, max_output_tokens, max_latency_ms, max_cost_usd,
            permitted_providers,
        )
        reason_codes = ["provider_healthy", "eligible_for_task"]
        if max_latency_ms is not None:
            reason_codes.append("within_latency_budget")
        if max_cost_usd is not None:
            reason_codes.append("within_cost_budget")
        attempts_log = []
        last_error = None
        for candidate_index, config in enumerate(candidates):
            for attempt in range(self.max_attempts):
                try:
                    with span("llm.generate") as current_span:
                        if current_span is not None:
                            current_span.set_attribute("llm.provider", config.provider)
                            current_span.set_attribute("llm.model", config.model)
                        content, input_tokens, output_tokens = config.client.generate(messages, max_output_tokens)
                    with self._health_lock:
                        self.health[config.provider].failures = 0
                        self.health[config.provider].open_until = 0
                    fallback_used = candidate_index > 0 or (
                        policy == "static" and config.provider != self.default_provider
                    )
                    decision = {
                        "policy": policy, "selected_provider": config.provider,
                        "selected_model": config.model,
                        "reason_codes": reason_codes + (["fallback_used"] if fallback_used else []),
                        "fallback_used": fallback_used,
                        "attempts": attempts_log + [{"provider": config.provider, "count": attempt + 1}],
                        "excluded": excluded,
                    }
                    actual_input = input_tokens if input_tokens is not None else input_tokens_estimate
                    actual_output = output_tokens if output_tokens is not None else max_output_tokens
                    cost = config.estimate_cost(actual_input, actual_output)
                    METRICS.llm(input_tokens=input_tokens, output_tokens=output_tokens, cost=cost,
                                fallback=fallback_used)
                    return GatewayResult(
                        content, input_tokens, output_tokens, config.provider, config.model,
                        cost, decision,
                    )
                except Exception as error:  # noqa: BLE001 — provider SDK exception types vary by adapter.
                    last_error = error
                    code = _error_code(error)
                    METRICS.increment("provider_errors", code)
                    attempts_log.append({"provider": config.provider, "error_code": code})
                    if attempt + 1 < self.max_attempts and _is_retryable(error):
                        METRICS.increment("provider_retries", config.provider)
                        self.sleeper(min(0.1 * (2**attempt), 1.0))
                        continue
                    break
            with self._health_lock:
                state = self.health[config.provider]
                state.failures += 1
                if state.failures >= self.circuit_failure_threshold:
                    state.open_until = self.clock() + self.circuit_reset_seconds
        decision = {
            "policy": policy, "selected_provider": None, "selected_model": None,
            "reason_codes": ["all_eligible_providers_failed" if candidates else "no_eligible_provider"],
            "fallback_used": len(attempts_log) > 0 and len(candidates) > 1,
            "attempts": attempts_log, "excluded": excluded,
        }
        raise RoutingError(decision) from last_error

    def health_snapshot(self) -> dict[str, dict]:
        now = self.clock()
        with self._health_lock:
            return {
                name: {"healthy": state.available(now), "consecutive_failures": state.failures}
                for name, state in self.health.items()
            }


def _error_code(error: Exception) -> str:
    name = type(error).__name__.casefold()
    status = getattr(error, "status_code", None)
    if isinstance(error, TimeoutError) or "timeout" in name:
        return "timeout"
    if status == 429 or "ratelimit" in name or "rate_limit" in name:
        return "rate_limited"
    if status is not None and status >= 500:
        return "server_error"
    if isinstance(error, ConnectionError) or "connection" in name:
        return "connection_error"
    return "provider_error"


def _is_retryable(error: Exception) -> bool:
    code = _error_code(error)
    return code in {"timeout", "rate_limited", "server_error", "connection_error"}


def configured_gateway() -> ChatGateway:
    providers: list[ProviderConfig] = []
    groq_key = os.getenv("GROQ_API_KEY")
    if groq_key:
        model = os.getenv("GROQ_CHAT_MODEL", "")
        if not model:
            raise RuntimeError("GROQ_CHAT_MODEL is required when GROQ_API_KEY is configured")
        providers.append(ProviderConfig(
            "groq", model,
            GroqChatProvider(groq_key, model, float(os.getenv("CHAT_TIMEOUT_SECONDS", "20"))),
            _optional_float("GROQ_INPUT_COST_PER_1K"), _optional_float("GROQ_OUTPUT_COST_PER_1K"),
            _optional_int("GROQ_ESTIMATED_LATENCY_MS"),
        ))
    gemini_key = os.getenv("GEMINI_API_KEY")
    if gemini_key:
        model = os.getenv("GEMINI_CHAT_MODEL", "")
        if not model:
            raise RuntimeError("GEMINI_CHAT_MODEL is required when GEMINI_API_KEY is configured")
        providers.append(ProviderConfig(
            "gemini", model,
            GeminiChatProvider(gemini_key, model, float(os.getenv("CHAT_TIMEOUT_SECONDS", "20"))),
            _optional_float("GEMINI_INPUT_COST_PER_1K"), _optional_float("GEMINI_OUTPUT_COST_PER_1K"),
            _optional_int("GEMINI_ESTIMATED_LATENCY_MS"),
        ))
    return ChatGateway(
        providers,
        default_provider="groq",
        fallback_allowlist={"gemini"},
        max_attempts=int(os.getenv("CHAT_MAX_ATTEMPTS", "2")),
        circuit_failure_threshold=int(os.getenv("CHAT_CIRCUIT_FAILURE_THRESHOLD", "3")),
        circuit_reset_seconds=float(os.getenv("CHAT_CIRCUIT_RESET_SECONDS", "30")),
    )


def _optional_float(name: str) -> float | None:
    value = os.getenv(name)
    return float(value) if value else None


def _optional_int(name: str) -> int | None:
    value = os.getenv(name)
    return int(value) if value else None
