"""Execution state for approved agent actions.

Adds the columns that let an approved action be carried out by OneClaw and
reported back: which executor took it, its task id, and the outcome. Without
these an approved action has no state between "a human said yes" and nothing,
which is where the chain used to stop.

Revision ID: 20260825_0004
Revises: 20260825_0003
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260825_0004"
down_revision: Union[str, None] = "20260825_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


COLUMNS = (
    ("executor", sa.Column("executor", sa.String(64), nullable=True)),
    ("executor_task_id", sa.Column("executor_task_id", sa.String(128), nullable=True)),
    ("dispatched_at", sa.Column("dispatched_at", sa.DateTime(), nullable=True)),
    ("executed_at", sa.Column("executed_at", sa.DateTime(), nullable=True)),
    ("execution_result", sa.Column("execution_result", sa.JSON(), nullable=True)),
    ("execution_error", sa.Column("execution_error", sa.Text(), nullable=True)),
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "agent_actions" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("agent_actions")}
    for name, column in COLUMNS:
        if name not in existing:
            op.add_column("agent_actions", column)

    indexes = {index["name"] for index in inspector.get_indexes("agent_actions")}
    # Reconciliation scans for actions stuck in `dispatched`, so status has to be
    # selective on its own.
    if "ix_agent_actions_status" not in indexes:
        op.create_index("ix_agent_actions_status", "agent_actions", ["status"])
    if "ix_agent_actions_executor_task_id" not in indexes:
        op.create_index("ix_agent_actions_executor_task_id", "agent_actions", ["executor_task_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "agent_actions" not in inspector.get_table_names():
        return
    indexes = {index["name"] for index in inspector.get_indexes("agent_actions")}
    for name in ("ix_agent_actions_executor_task_id", "ix_agent_actions_status"):
        if name in indexes:
            op.drop_index(name, table_name="agent_actions")
    existing = {column["name"] for column in inspector.get_columns("agent_actions")}
    for name, _ in reversed(COLUMNS):
        if name in existing:
            op.drop_column("agent_actions", name)
