"""Small session-bound repository for the Phase 2 persistence operations."""

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from incidentiq.models import Base


class Repository[ModelT: Base]:
    def __init__(self, session: Session, model: type[ModelT]) -> None:
        self.session = session
        self.model = model

    def add(self, **values: Any) -> ModelT:
        instance = self.model(**values)
        self.session.add(instance)
        self.session.flush()
        return instance

    def get(self, entity_id: UUID) -> ModelT | None:
        return self.session.get(self.model, entity_id)

    def delete(self, instance: ModelT) -> None:
        self.session.delete(instance)
