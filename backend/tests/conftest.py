"""Load safe test settings before application modules are imported."""

import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from dotenv import dotenv_values
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

_CONFIG_KEYS = {
    "API_KEY",
    "READONLY_API_KEY",
    "API_RATE_LIMIT_PER_MINUTE",
    "UPLOAD_RATE_LIMIT_PER_MINUTE",
    "DATABASE_URL",
    "DIRECT_DATABASE_URL",
    "DATABASE_CONNECT_TIMEOUT_SECONDS",
    "DATABASE_POOL_TIMEOUT_SECONDS",
    "REDIS_URL",
    "GROQ_API_KEY",
    "GROQ_CHAT_MODEL",
    "GEMINI_API_KEY",
    "GEMINI_CHAT_MODEL",
    "GEMINI_EMBEDDING_MODEL",
    "CHAT_TIMEOUT_SECONDS",
    "CHAT_MAX_ATTEMPTS",
    "CHAT_CIRCUIT_FAILURE_THRESHOLD",
    "CHAT_CIRCUIT_RESET_SECONDS",
    "ROUTING_POLICY",
    "MAX_UPLOAD_MB",
    "CHUNK_SIZE",
    "CHUNK_OVERLAP",
    "INGESTION_JOB_MAX_ATTEMPTS",
    "EMBEDDING_DIMENSION",
    "PINECONE_API_KEY",
    "PINECONE_INDEX",
    "PINECONE_NAMESPACE",
    "EVALUATION_DATASET_DIR",
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "GROQ_INPUT_COST_PER_1K",
    "GROQ_OUTPUT_COST_PER_1K",
    "GROQ_ESTIMATED_LATENCY_MS",
    "GEMINI_INPUT_COST_PER_1K",
    "GEMINI_OUTPUT_COST_PER_1K",
    "GEMINI_ESTIMATED_LATENCY_MS",
}


def _load_test_env(path: Path) -> None:
    values = dotenv_values(path)
    for key in _CONFIG_KEYS:
        os.environ.pop(key, None)
    for key, value in values.items():
        if value is not None:
            os.environ[key] = value
    # main.py and worker modules call load_dotenv() at import time; keep root .env out.
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"


def _validate_isolated_integration_env(allow_live_providers: bool = False) -> None:
    for variable in ("DATABASE_URL", "DIRECT_DATABASE_URL"):
        database_url = os.getenv(variable, "")
        if not database_url:
            continue
        try:
            url = make_url(database_url)
        except (ArgumentError, TypeError, ValueError):
            raise pytest.UsageError(f"Integration {variable} is invalid.") from None
        host = (url.host or "").casefold()
        if (
            not url.database
            or "test" not in url.database.casefold()
            or "prod" in url.database.casefold()
            or "prod" in host
            or not (host in {"localhost", "127.0.0.1", "::1"} or "test" in host)
        ):
            raise pytest.UsageError(
                f"Integration {variable} must use a test-named database on localhost or a test host."
            )

    redis_url = os.getenv("REDIS_URL", "")
    if redis_url:
        parsed = urlsplit(redis_url)
        host = (parsed.hostname or "").casefold()
        try:
            redis_db = int(parsed.path.strip("/") or "0")
        except ValueError as error:
            raise pytest.UsageError(
                "Integration REDIS_URL must use a numeric test database path."
            ) from error
        if (
            redis_db < 1
            or "prod" in host
            or not (host in {"localhost", "127.0.0.1", "::1"} or "test" in host)
        ):
            raise pytest.UsageError(
                "Integration REDIS_URL must use a nonzero DB on localhost or a test host."
            )

    pinecone_key = os.getenv("PINECONE_API_KEY", "")
    pinecone_index = os.getenv("PINECONE_INDEX", "")
    if pinecone_key or pinecone_index:
        if (
            not pinecone_key
            or "test" not in pinecone_index.casefold()
            or "prod" in pinecone_index.casefold()
        ):
            raise pytest.UsageError(
                "Integration Pinecone requires a key and an index name containing 'test'."
            )
        namespace = os.getenv("PINECONE_NAMESPACE", "").casefold()
        if "test" not in namespace or "prod" in namespace:
            raise pytest.UsageError(
                "Integration PINECONE_NAMESPACE must contain 'test'."
            )

    if not allow_live_providers and any(
        os.getenv(key) for key in ("GROQ_API_KEY", "GEMINI_API_KEY")
    ):
        raise pytest.UsageError(
            "Integration model credentials require --live-provider."
        )


def pytest_addoption(parser):
    group = parser.getgroup("incidentiq")
    group.addoption(
        "--integration",
        action="store_true",
        help="run only explicitly marked integration tests",
    )
    group.addoption(
        "--test-env-file",
        help="explicit isolated integration env file (requires --integration)",
    )
    group.addoption(
        "--live-provider",
        action="store_true",
        help="allow explicitly marked live-provider tests",
    )


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "integration: requires explicitly configured isolated test services"
    )
    config.addinivalue_line(
        "markers", "live_provider: may call a paid or rate-limited model provider"
    )
    integration = config.getoption("--integration")
    env_file = config.getoption("--test-env-file")
    if not integration and env_file:
        raise pytest.UsageError("--test-env-file requires --integration.")
    if config.getoption("--live-provider") and not integration:
        raise pytest.UsageError("--live-provider requires --integration.")

    if integration:
        if not env_file:
            raise pytest.UsageError(
                "--integration requires --test-env-file pointing to an isolated test config."
            )
        path = Path(env_file).resolve()
        if not path.is_file():
            raise pytest.UsageError("Integration test environment file does not exist.")
        _load_test_env(path)
        _validate_isolated_integration_env(config.getoption("--live-provider"))
    else:
        _load_test_env(Path(__file__).with_name(".env.test"))


def pytest_collection_modifyitems(config, items):
    integration = config.getoption("--integration")
    live_provider = config.getoption("--live-provider")
    skip = pytest.mark.skip(
        reason="requires --integration and an isolated test env file"
    )
    skip_live = pytest.mark.skip(reason="requires --live-provider")
    for item in items:
        if bool(item.get_closest_marker("integration")) != integration:
            item.add_marker(skip)
        if item.get_closest_marker("live_provider") and not live_provider:
            item.add_marker(skip_live)
