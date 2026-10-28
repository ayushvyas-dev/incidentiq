FROM ghcr.io/astral-sh/uv:0.13.1 AS uv

FROM python:3.12-slim AS build
COPY --from=uv /uv /uvx /bin/
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY src ./src
COPY alembic ./alembic
COPY alembic.ini ./
COPY datasets ./datasets
COPY start.sh ./
RUN uv sync --locked --no-dev --no-editable

FROM python:3.12-slim AS runtime
RUN useradd --create-home --uid 10001 incidentiq
WORKDIR /app
COPY --from=build --chown=incidentiq:incidentiq /app/.venv ./.venv
COPY --from=build --chown=incidentiq:incidentiq /app/alembic ./alembic
COPY --from=build --chown=incidentiq:incidentiq /app/alembic.ini ./alembic.ini
COPY --from=build --chown=incidentiq:incidentiq /app/datasets ./datasets
COPY --from=build --chown=incidentiq:incidentiq --chmod=755 /app/start.sh ./start.sh
ENV PATH="/app/.venv/bin:$PATH" \
    EVALUATION_DATASET_DIR=/app/datasets \
    PYTHONUNBUFFERED=1
USER incidentiq
EXPOSE 8000
CMD ["./start.sh"]
