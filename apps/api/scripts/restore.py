import os
import sys

# Run directly (`python scripts/restore.py`) the API package root is not on sys.path,
# because sys.path[0] is scripts/. Add it so the documented commands work as written.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import argparse
from pathlib import Path
from app.services.backup import restore_backup, verify_backup

parser = argparse.ArgumentParser(description="Restore a Construction Twin backup")
parser.add_argument("backup", type=Path)
parser.add_argument("--confirm", required=True)
args = parser.parse_args()
print(verify_backup(args.backup))
restore_backup(args.backup, args.confirm)
print("restore completed")
