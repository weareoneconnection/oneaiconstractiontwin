import os
import sys

# Run directly (`python scripts/migrate.py`) the API package root is not on sys.path,
# because sys.path[0] is scripts/. Add it so the documented commands work as written.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.migrations import migration_status, upgrade_to_head

if __name__ == "__main__":
    upgrade_to_head()
    print(migration_status())
