"""Project comments for team collaboration.

Revision ID: 20260825_0003
Revises: 20260824_0002
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260825_0003"
down_revision: Union[str, None] = "20260824_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "comments" in inspector.get_table_names():
        return
    op.create_table(
        "comments",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, index=True),
        sa.Column("organization_id", sa.String(64), nullable=False, index=True),
        sa.Column("project_id", sa.String(64), sa.ForeignKey("projects.id"), nullable=False, index=True),
        sa.Column("target_type", sa.String(64), nullable=False, server_default="project"),
        sa.Column("target_id", sa.String(64), nullable=False, server_default=""),
        sa.Column("parent_id", sa.String(64), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("author_id", sa.String(64), nullable=False),
        sa.Column("author_email", sa.String(255), nullable=True),
        sa.Column("author_role", sa.String(64), nullable=False, server_default="viewer"),
        sa.Column("resolved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("resolved_by", sa.String(64), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_comment_project_target", "comments", ["project_id", "target_type", "target_id"])
    op.create_index("ix_comment_thread", "comments", ["parent_id", "created_at"])


def downgrade() -> None:
    # See the baseline revision: enterprise downgrades restore a verified backup.
    pass
