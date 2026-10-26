"""FastAPI application entry point."""

import hmac
import inspect
import json
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from time import perf_counter
from typing import Any
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import JSONResponse, Response
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from incidentiq.api.documents import router as documents_router
from incidentiq.api.evaluations import router as evaluations_router
from incidentiq.api.incidents import router as incidents_router
from incidentiq.api.jobs import router as jobs_router
from incidentiq.api.routing import router as routing_router
from incidentiq.api.search import router as search_router
from incidentiq.db.session import create_engine, create_session_factory
from incidentiq.observability import METRICS, span
from incidentiq.security import SlidingWindowLimiter
from incidentiq.services.analysis import ChatProvider
from incidentiq.services.gemini import GeminiEmbeddings
from incidentiq.services.routing import ChatGateway, ProviderConfig, configured_gateway
from incidentiq.services.vector_index import (
    EmbeddingProvider,
    PineconeVectorStore,
    VectorStore,
)

load_dotenv()


def create_app(
    session_factory: sessionmaker[Session] | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    vector_store: VectorStore | None = None,
    chat_provider: ChatProvider | None = None,
    chat_gateway: ChatGateway | None = None,
    job_queue: Any | None = None,
    api_token: str | None = None,
    readonly_api_token: str | None = None,
) -> FastAPI:
    engine: Engine | None = None
    owns_queue = False
    if session_factory is None and os.getenv("DATABASE_URL"):
        engine = create_engine()
        session_factory = create_session_factory(engine)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        nonlocal owns_queue
        try:
            if app.state.job_queue is None and os.getenv("REDIS_URL"):
                from arq import create_pool
                from arq.connections import RedisSettings

                app.state.job_queue = await create_pool(RedisSettings.from_dsn(os.environ["REDIS_URL"]))
                owns_queue = True
            yield
        finally:
            if owns_queue and app.state.job_queue is not None:
                close = getattr(app.state.job_queue, "aclose", None) or app.state.job_queue.close
                result = close()
                if inspect.isawaitable(result):
                    await result
                app.state.job_queue = None
                owns_queue = False
            if engine is not None:
                engine.dispose()

    app = FastAPI(title="IncidentIQ", version="0.1.0", lifespan=lifespan)
    app.state.engine = engine
    app.state.metrics = METRICS
    app.state.api_token = api_token if api_token is not None else os.getenv("API_KEY", "")
    app.state.readonly_api_token = (
        readonly_api_token if readonly_api_token is not None
        else os.getenv("READONLY_API_KEY", "")
    )
    if app.state.api_token and len(app.state.api_token) < 32:
        raise ValueError("API_KEY must contain at least 32 characters")
    if app.state.readonly_api_token and len(app.state.readonly_api_token) < 32:
        raise ValueError("READONLY_API_KEY must contain at least 32 characters")
    if app.state.api_token and hmac.compare_digest(
        app.state.api_token.encode(), app.state.readonly_api_token.encode()
    ):
        raise ValueError("API_KEY and READONLY_API_KEY must be different")
    app.state.request_limiter = SlidingWindowLimiter(int(os.getenv("API_RATE_LIMIT_PER_MINUTE", "120")))
    app.state.upload_limiter = SlidingWindowLimiter(int(os.getenv("UPLOAD_RATE_LIMIT_PER_MINUTE", "10")))
    app.state.session_factory = session_factory
    app.state.job_queue = job_queue
    app.state.embedding_provider = embedding_provider
    if app.state.embedding_provider is None and os.getenv("GEMINI_API_KEY"):
        model = os.getenv("GEMINI_EMBEDDING_MODEL", "")
        if not model:
            raise RuntimeError("GEMINI_EMBEDDING_MODEL is required when GEMINI_API_KEY is configured")
        app.state.embedding_provider = GeminiEmbeddings(
            os.environ["GEMINI_API_KEY"], model,
            int(os.getenv("EMBEDDING_DIMENSION", "768")),
            float(os.getenv("CHAT_TIMEOUT_SECONDS", "20")),
        )
    app.state.vector_store = vector_store
    if app.state.vector_store is None and os.getenv("PINECONE_API_KEY") and os.getenv("PINECONE_INDEX"):
        app.state.vector_store = PineconeVectorStore(
            os.environ["PINECONE_API_KEY"], os.environ["PINECONE_INDEX"]
        )
    if chat_gateway is not None:
        app.state.chat_gateway = chat_gateway
    elif chat_provider is not None:
        app.state.chat_gateway = ChatGateway(
            [ProviderConfig(chat_provider.provider, chat_provider.model, chat_provider)],
            default_provider=chat_provider.provider,
        )
    else:
        app.state.chat_gateway = configured_gateway()
    app.state.routing_policy = os.getenv("ROUTING_POLICY", "static")
    if app.state.routing_policy not in {"static", "rule_based"}:
        raise ValueError("ROUTING_POLICY must be static or rule_based")
    app.include_router(documents_router, prefix="/api/v1")
    app.include_router(search_router, prefix="/api/v1")
    app.include_router(incidents_router, prefix="/api/v1")
    app.include_router(routing_router, prefix="/api/v1")
    app.include_router(jobs_router, prefix="/api/v1")
    app.include_router(evaluations_router, prefix="/api/v1")

    @app.middleware("http")
    async def observe_request(request, call_next):
        request_id = f"req_{uuid4().hex}"
        started = perf_counter()
        status = 500
        with span("http.request") as trace_span:
            if trace_span is not None:
                trace_span.set_attribute("http.request.method", request.method)
                trace_span.set_attribute("incidentiq.request_id", request_id)
            try:
                response = await call_next(request)
                status = response.status_code
                response.headers["X-Request-ID"] = request_id
                return response
            finally:
                elapsed_ms = (perf_counter() - started) * 1000
                METRICS.request(elapsed_ms, status)
                route = request.scope.get("route")
                logging.getLogger("incidentiq.access").info(json.dumps({
                    "event": "http_request", "request_id": request_id,
                    "method": request.method,
                    "path": getattr(route, "path", "unmatched"),
                    "status_code": status, "duration_ms": round(elapsed_ms, 2),
                }, separators=(",", ":")))

    @app.middleware("http")
    async def authorize_request(request, call_next):
        path = request.url.path
        protected = path.startswith("/api/v1/") or path == "/metrics"
        if not protected or request.method == "OPTIONS":
            return await call_next(request)

        client = request.client.host if request.client is not None else "unknown"
        limiter = app.state.upload_limiter if path == "/api/v1/documents" and request.method == "POST" else app.state.request_limiter
        allowed, retry_after = limiter.allow(client)
        if not allowed:
            return JSONResponse(
                {"detail": "Rate limit exceeded"}, status_code=429,
                headers={"Retry-After": str(retry_after)},
            )
        if not app.state.api_token and not app.state.readonly_api_token:
            return JSONResponse({"detail": "API authentication is not configured"}, status_code=503)

        authorization = request.headers.get("authorization", "")
        scheme, _, token = authorization.partition(" ")
        if scheme.casefold() != "bearer" or not token:
            return JSONResponse(
                {"detail": "Authentication required"}, status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )

        admin = app.state.api_token and hmac.compare_digest(token.encode(), app.state.api_token.encode())
        readonly = app.state.readonly_api_token and hmac.compare_digest(
            token.encode(), app.state.readonly_api_token.encode()
        )
        if not admin and not readonly:
            return JSONResponse(
                {"detail": "Invalid bearer token"}, status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
        if readonly and request.method not in {"GET", "HEAD"}:
            return JSONResponse({"detail": "Write access is required"}, status_code=403)
        return await call_next(request)

    @app.get("/health/live", tags=["health"])
    def health_live():
        return {"status": "alive"}

    @app.get("/health/ready", tags=["health"])
    async def health_ready():
        dependencies = {
            "api_auth": "ok" if app.state.api_token or app.state.readonly_api_token else "unconfigured",
            "postgres": "unconfigured", "redis": "not_configured",
        }
        ready = dependencies["api_auth"] == "ok"
        if app.state.session_factory is not None:
            try:
                with app.state.session_factory() as session:
                    session.execute(text("SELECT 1"))
                dependencies["postgres"] = "ok"
            except Exception:  # noqa: BLE001 — report database driver failures as unavailable.
                dependencies["postgres"] = "unavailable"
                ready = False
        redis_required = bool(os.getenv("REDIS_URL")) or app.state.job_queue is not None
        if redis_required:
            try:
                result = app.state.job_queue.ping()
                if inspect.isawaitable(result):
                    await result
                dependencies["redis"] = "ok"
            except Exception:  # noqa: BLE001 — report Redis client failures as unavailable.
                dependencies["redis"] = "unavailable"
                ready = False
        return Response(
            content=json.dumps({"status": "ready" if ready else "not_ready", "dependencies": dependencies}),
            status_code=200 if ready else 503, media_type="application/json",
        )

    @app.get("/api/v1/metrics/summary", tags=["operations"])
    def metrics_summary(window: str = "24h"):
        windows = {"1h": 3600, "24h": 86400, "7d": 604800}
        if window not in windows:
            from fastapi import HTTPException
            raise HTTPException(status_code=422, detail="window must be 1h, 24h, or 7d")
        return {"window": window, **METRICS.summary(windows[window])}

    @app.get("/metrics", include_in_schema=False)
    def prometheus_metrics():
        return Response(METRICS.prometheus(), media_type="text/plain; version=0.0.4; charset=utf-8")
    return app


app = create_app()
