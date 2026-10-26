import asyncio
import importlib

import pytest
from arq.connections import RedisSettings

from incidentiq.main import create_app
from tests.auth_support import TEST_API_TOKEN


@pytest.mark.parametrize(
    ("url", "tls"),
    [
        ("redis://localhost:6379/0", False),
        ("rediss://default:placeholder@redis.example:6380/0", True),
    ],
)
def test_api_uses_arq_settings_for_local_and_tls_redis(monkeypatch, url, tls):
    import arq

    settings_seen = []

    class FakeRedis:
        async def ping(self):
            return True

        async def aclose(self):
            pass

    async def fake_create_pool(settings):
        settings_seen.append(settings)
        return FakeRedis()

    monkeypatch.setenv("REDIS_URL", url)
    monkeypatch.setattr(arq, "create_pool", fake_create_pool, raising=False)
    app = create_app(api_token=TEST_API_TOKEN)

    async def run_lifespan():
        async with app.router.lifespan_context(app):
            assert app.state.job_queue is not None

    asyncio.run(run_lifespan())

    assert len(settings_seen) == 1
    assert settings_seen[0].ssl is tls
    assert settings_seen[0].host in {"localhost", "redis.example"}


@pytest.mark.parametrize(
    ("url", "tls"),
    [
        ("redis://localhost:6379/0", False),
        ("rediss://default:placeholder@redis.example:6380/0", True),
    ],
)
def test_worker_uses_arq_settings_for_local_and_tls_redis(monkeypatch, url, tls):
    monkeypatch.setenv("REDIS_URL", url)
    from incidentiq.workers import queue

    queue = importlib.reload(queue)
    assert queue.WorkerSettings.redis_settings.ssl is tls
    assert queue.WorkerSettings.redis_settings.host in {"localhost", "redis.example"}


def test_worker_loads_tls_redis_url_from_dotenv(monkeypatch, tmp_path):
    from dotenv import main as dotenv_main

    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("PYTHON_DOTENV_DISABLED", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "REDIS_URL=rediss://default:placeholder@redis.example:6380/0\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(dotenv_main, "find_dotenv", lambda *args, **kwargs: str(env_file))
    from incidentiq.workers import queue

    queue = importlib.reload(queue)
    assert queue.WorkerSettings.redis_settings.ssl is True
    assert queue.WorkerSettings.redis_settings.host == "redis.example"


def test_worker_empty_redis_url_uses_local_default(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "")
    from incidentiq.workers import queue

    queue = importlib.reload(queue)
    assert queue.WorkerSettings.redis_settings.ssl is False
    assert queue.WorkerSettings.redis_settings.host == "localhost"


@pytest.mark.parametrize(
    ("url", "tls"),
    [
        ("redis://localhost:6379/0", False),
        ("rediss://default:placeholder@redis.example:6380/0", True),
    ],
)
def test_arq_dsn_parser_maps_redis_scheme_to_tls(url, tls):
    settings = RedisSettings.from_dsn(url)
    assert settings.ssl is tls
