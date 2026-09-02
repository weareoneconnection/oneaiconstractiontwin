"""Schedule logic links on activities.

Revision ID: 20260902_0005
Revises: 20260825_0004
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260902_0005"
down_revision: Union[str, None] = "20260825_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "activities" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("activities")}
    if "predecessors" not in columns:
        # Existing rows get an empty link set: the CPM pass then reports the schedule as
        # having no logic, which is true, rather than inventing a chain.
        op.add_column("activities", sa.Column("predecessors", sa.JSON(), nullable=True))


def downgrade() -> None:
    pass
