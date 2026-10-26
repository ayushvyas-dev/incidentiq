"""Entrypoint proxy allowing 'uvicorn main:app' from the backend directory."""

from incidentiq.main import app

__all__ = ["app"]
