"""Persist the model-routing decision for each analysis run."""

from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0002_analysis_routing_decision"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("analysis_runs", sa.Column("routing_decision", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("analysis_runs", "routing_decision")
