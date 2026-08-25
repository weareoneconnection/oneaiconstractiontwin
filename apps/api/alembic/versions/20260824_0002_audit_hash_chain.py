"""Tamper-evident audit chain columns.

Revision ID: 20260824_0002
Revises: 20260824_0001
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260824_0002"
down_revision: Union[str, None] = "20260824_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_COLUMNS = {
    "sequence": sa.Column("sequence", sa.Integer(), nullable=False, server_default="0"),
    "prev_hash": sa.Column("prev_hash", sa.String(64), nullable=False, server_default=""),
    "entry_hash": sa.Column("entry_hash", sa.String(64), nullable=False, server_default=""),
}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "audit_logs" not in inspector.get_table_names():
        # Fresh install: the baseline create_all already produced the final shape.
        return
    existing = {column["name"] for column in inspector.get_columns("audit_logs")}
    for name, column in NEW_COLUMNS.items():
        if name not in existing:
            op.add_column("audit_logs", column)
    indexes = {index["name"] for index in inspector.get_indexes("audit_logs")}
    if "ix_audit_tenant_sequence" not in indexes:
        op.create_index("ix_audit_tenant_sequence", "audit_logs", ["tenant_id", "sequence"])
    # Pre-existing rows keep sequence 0 and empty hashes. They are reported by the
    # verifier as unchained legacy entries rather than silently back-dated into a
    # chain that was never actually protected.


def downgrade() -> None:
    # See the baseline revision: enterprise downgrades restore a verified backup.
    pass
