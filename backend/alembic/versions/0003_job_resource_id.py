"""Add resource identity for idempotent background jobs."""

from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0003_job_resource_id"
down_revision: str | None = "0002_analysis_routing_decision"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_index(
        "ix_jobs_type_resource_created", "jobs", ["job_type", "resource_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_jobs_type_resource_created", table_name="jobs")
    op.drop_column("jobs", "resource_id")
