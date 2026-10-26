import os

import pytest

from tests.conftest import _validate_isolated_integration_env


def test_default_test_environment_has_dummy_auth_and_no_live_services():
    assert len(os.environ["API_KEY"]) >= 32
    assert len(os.environ["READONLY_API_KEY"]) >= 32
    assert os.environ["API_KEY"] != os.environ["READONLY_API_KEY"]
    for key in (
        "DATABASE_URL",
        "REDIS_URL",
        "GROQ_API_KEY",
        "GEMINI_API_KEY",
        "PINECONE_API_KEY",
        "PINECONE_INDEX",
    ):
        assert os.environ[key] == ""


def test_integration_configuration_rejects_non_test_database(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:secret@db.example/incidentiq")
    with pytest.raises(pytest.UsageError, match="test-named database"):
        _validate_isolated_integration_env()


def test_integration_configuration_validates_direct_database_url_too(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv(
        "DIRECT_DATABASE_URL",
        "postgresql://user:secret@prod-db.example/incidentiq_test",
    )
    with pytest.raises(pytest.UsageError, match="test-named database"):
        _validate_isolated_integration_env()


def test_integration_configuration_rejects_production_host_even_with_test_database(
    monkeypatch,
):
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql://user:secret@prod-db.example/incidentiq_test"
    )
    with pytest.raises(pytest.UsageError, match="test-named database"):
        _validate_isolated_integration_env()


def test_integration_configuration_rejects_production_redis(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("REDIS_URL", "redis://prod-cache.example:6379/1")
    with pytest.raises(
        pytest.UsageError, match="nonzero DB on localhost or a test host"
    ):
        _validate_isolated_integration_env()


def test_integration_configuration_rejects_production_named_pinecone_index(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setenv("PINECONE_API_KEY", "dummy-test-key")
    monkeypatch.setenv("PINECONE_INDEX", "incidentiq-prod-test")
    monkeypatch.setenv("PINECONE_NAMESPACE", "incidentiq-test")
    with pytest.raises(pytest.UsageError, match="index name containing 'test'"):
        _validate_isolated_integration_env()


def test_integration_configuration_accepts_isolated_test_resources(monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql://user:secret@db-test.example/incidentiq_test"
    )
    monkeypatch.setenv("REDIS_URL", "redis://redis-test.example:6379/1")
    monkeypatch.setenv("PINECONE_API_KEY", "dummy-test-key")
    monkeypatch.setenv("PINECONE_INDEX", "incidentiq-test")
    monkeypatch.setenv("PINECONE_NAMESPACE", "incidentiq-test")
    _validate_isolated_integration_env()


def test_integration_model_credentials_require_live_provider_opt_in(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DIRECT_DATABASE_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("PINECONE_API_KEY", raising=False)
    monkeypatch.delenv("PINECONE_INDEX", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "dummy-test-key")
    with pytest.raises(pytest.UsageError, match="require --live-provider"):
        _validate_isolated_integration_env()
    _validate_isolated_integration_env(allow_live_providers=True)
