from incidentiq.services.routing import ChatGateway, ProviderConfig, RoutingError


class FakeProvider:
    def __init__(self, name, model, outcomes):
        self.provider = name
        self.model = model
        self.outcomes = list(outcomes)
        self.calls = 0

    def generate(self, messages, max_output_tokens):
        self.calls += 1
        outcome = self.outcomes.pop(0) if self.outcomes else ("ok", 4, 2)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def config(client, input_cost=None, output_cost=None, latency=None):
    return ProviderConfig(
        client.provider, client.model, client, input_cost, output_cost, latency
    )


def test_static_policy_uses_default_and_records_decision():
    primary = FakeProvider("groq", "default", [("answer", 10, 4)])
    secondary = FakeProvider("gemini", "fallback", [])
    gateway = ChatGateway(
        [config(primary), config(secondary)], default_provider="groq",
        fallback_allowlist={"gemini"}, sleeper=lambda _: None,
    )
    result = gateway.generate([], 20, policy="static", input_tokens_estimate=10)
    assert result.provider == "groq"
    assert result.decision["fallback_used"] is False
    assert primary.calls == 1 and secondary.calls == 0


def test_rate_limit_is_retried_with_a_bounded_delay():
    class RateLimited(Exception):
        status_code = 429

    primary = FakeProvider("groq", "default", [RateLimited(), ("answer", 3, 1)])
    sleeps = []
    gateway = ChatGateway(
        [config(primary)], default_provider="groq", sleeper=sleeps.append,
    )
    result = gateway.generate([], 10, policy="static", input_tokens_estimate=3)
    assert result.provider == "groq" and primary.calls == 2
    assert sleeps == [0.1]


def test_retry_then_fallback_only_when_explicitly_allowed():
    primary = FakeProvider("groq", "default", [TimeoutError(), RuntimeError("down")])
    secondary = FakeProvider("gemini", "fallback", [("answer", 8, 3)])
    sleeps = []
    gateway = ChatGateway(
        [config(primary), config(secondary)], default_provider="groq",
        fallback_allowlist={"gemini"}, sleeper=sleeps.append,
    )
    result = gateway.generate([], 20, policy="static", input_tokens_estimate=10)
    assert result.provider == "gemini"
    assert result.decision["fallback_used"] is True
    assert primary.calls == 2 and secondary.calls == 1
    assert sleeps == [0.1]

    restricted = ChatGateway(
        [config(FakeProvider("groq", "default", [RuntimeError()])), config(secondary)],
        default_provider="groq", sleeper=lambda _: None,
    )
    try:
        restricted.generate([], 20, policy="static", input_tokens_estimate=10)
    except RoutingError as error:
        assert error.decision["fallback_used"] is False
        assert secondary.calls == 1
    else:
        raise AssertionError("fallback should have been prohibited")


def test_rule_policy_budgets_and_simulation_estimates():
    primary = FakeProvider("groq", "expensive", [])
    cheaper = FakeProvider("gemini", "cheap", [])
    gateway = ChatGateway(
        [config(primary, 0.02, 0.02, 1200), config(cheaper, 0.001, 0.001, 1500)],
        default_provider="groq", fallback_allowlist={"gemini"},
    )
    simulation = gateway.simulate(
        policy="rule_based", input_tokens=1000, output_tokens=500,
        max_latency_ms=2000, max_cost_usd=0.03,
    )
    assert simulation["selected"] == {"provider": "gemini", "model": "cheap"}
    assert simulation["eligible_models"][0]["estimated_cost_usd"] == 0.0015

    blocked = gateway.simulate(
        policy="rule_based", input_tokens=1000, output_tokens=500,
        max_latency_ms=1000,
    )
    assert blocked["selected"] is None
    assert len(blocked["excluded"]) == 2


def test_provider_allowlist_and_circuit_breaker():
    clock = [0.0]
    primary = FakeProvider("groq", "default", [RuntimeError(), RuntimeError()])
    secondary = FakeProvider("gemini", "fallback", [])
    gateway = ChatGateway(
        [config(primary), config(secondary)], default_provider="groq",
        fallback_allowlist={"gemini"}, max_attempts=1, circuit_failure_threshold=2,
        circuit_reset_seconds=5, clock=lambda: clock[0], sleeper=lambda _: None,
    )
    for _ in range(2):
        try:
            gateway.generate([], 10, policy="static", input_tokens_estimate=1, permitted_providers={"groq"})
        except RoutingError:
            pass
    assert gateway.health_snapshot()["groq"]["healthy"] is False
    try:
        gateway.generate([], 10, policy="static", input_tokens_estimate=1, permitted_providers={"groq"})
    except RoutingError as error:
        assert error.decision["reason_codes"] == ["no_eligible_provider"]
    assert primary.calls == 2
    clock[0] = 6
    assert gateway.health_snapshot()["groq"]["healthy"] is True
