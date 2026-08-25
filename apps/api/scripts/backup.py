import os
import sys

# Run directly (`python scripts/backup.py`) the API package root is not on sys.path,
# because sys.path[0] is scripts/. Add it so the documented commands work as written.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import argparse
from app.services.backup import create_backup, prune_old_backups, verify_backup

parser = argparse.ArgumentParser(description="Create a verified Construction Twin backup")
parser.add_argument("--label", default="manual")
args = parser.parse_args()
root = create_backup(args.label)
result = verify_backup(root)
prune_old_backups()
print(root)
print("verified=" + str(result["ok"]).lower())
