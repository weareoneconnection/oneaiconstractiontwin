"""Test isolation.

The suite used to run against whatever `construction_twin.db` and data directories
the developer happened to have, so results depended on prior runs (a test that
deliberately tampers with the audit chain poisoned every later run) and a test run
mutated real local data. Every run now gets its own database and storage roots.

These variables must be set before `app.core.config` is imported, which is why they
live in conftest rather than in a fixture.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

_TEST_ROOT = Path(tempfile.mkdtemp(prefix="construction-twin-tests-"))

os.environ.setdefault("APP_ENV", "test")
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_ROOT / 'test.db'}"
os.environ["UPLOAD_ROOT"] = str(_TEST_ROOT / "uploads")
os.environ["GENERATED_ASSET_ROOT"] = str(_TEST_ROOT / "generated-assets")
os.environ["ASSET_LOCAL_ROOT"] = str(_TEST_ROOT / "object-store")
os.environ["ASSET_WORK_ROOT"] = str(_TEST_ROOT / "asset-work")
os.environ["BACKUP_ROOT"] = str(_TEST_ROOT / "backups")
os.environ["REDIS_REQUIRED"] = "false"
os.environ["RATE_LIMIT_ENABLED"] = "false"


def pytest_report_header(config) -> str:
    return f"construction-twin test root: {_TEST_ROOT}"
