"""OneAI Construction Twin v0.7 enterprise baseline.

Revision ID: 20260824_0001
Revises: None
"""
from typing import Sequence, Union

from alembic import op

revision: str = "20260824_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The v0.7 package may be installed over a v0.6 database that predates
    # Alembic. create_all is intentionally idempotent here: it preserves
    # existing tables, creates the new enterprise tables, and then Alembic
    # records this baseline revision.
    from app.db.base import Base
    from app.domain import models  # noqa: F401

    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    # A destructive full downgrade is intentionally not automated for an
    # enterprise pilot database. Restore a verified backup instead.
    pass
