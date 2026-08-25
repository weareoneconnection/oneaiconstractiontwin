from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory

from app.db.base import engine


API_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = API_ROOT / "alembic.ini"


def alembic_config() -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(API_ROOT / "alembic"))
    return config


def upgrade_to_head() -> None:
    command.upgrade(alembic_config(), "head")


def current_revision() -> str | None:
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def head_revision() -> str:
    return str(ScriptDirectory.from_config(alembic_config()).get_current_head())


def migration_status() -> dict[str, object]:
    current = current_revision()
    head = head_revision()
    return {"current": current, "head": head, "at_head": current == head}
