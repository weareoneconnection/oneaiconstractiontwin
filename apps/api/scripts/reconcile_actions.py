"""Find approved actions that were dispatched and never confirmed.

`dispatched` means an action left the twin for the executor and no outcome came
back. That is a real operational condition, not a synonym for success, and it is
invisible until something looks for it — which is what this job is.

Run it on a schedule. It exits 1 when anything is unconfirmed, so cron mail,
systemd, or a monitoring check will notice without needing to parse the output.

    python scripts/reconcile_actions.py            # human-readable
    python scripts/reconcile_actions.py --json     # for a monitoring agent
"""
import os
import sys

# Run directly (`python scripts/reconcile_actions.py`) the API package root is not
# on sys.path, because sys.path[0] is scripts/. Add it so the documented commands
# work as written.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import argparse
import json

from app.core.config import settings
from app.db.session import SessionLocal
from app.services.action_execution import all_stale_dispatched_actions

parser = argparse.ArgumentParser(description="Report actions dispatched but never confirmed")
parser.add_argument("--json", action="store_true", help="emit JSON for a monitoring agent")
args = parser.parse_args()

db = SessionLocal()
try:
    stale = all_stale_dispatched_actions(db)
finally:
    db.close()

threshold = settings.oneclaw_dispatch_stale_after_seconds

if args.json:
    print(json.dumps({"unconfirmed": len(stale), "threshold_seconds": threshold, "actions": stale}, default=str))
elif not stale:
    print(f"No unconfirmed actions (threshold {threshold}s).")
else:
    print(f"{len(stale)} action(s) dispatched over {threshold}s ago with no outcome reported:\n")
    for item in stale:
        print(f"  {item['id']}")
        print(f"    tenant   {item['tenant_id']} / {item['organization_id']}")
        print(f"    project  {item['project_id']}")
        print(f"    approved by {item['approved_by']} · executor {item['executor']} · task {item['executor_task_id']}")
        print(f"    unconfirmed for {item['unconfirmed_for_seconds']}s\n")
    print("Each of these was sent to an executor and never accounted for. Check the")
    print("executor's task, then either retry the dispatch or record the outcome.")

sys.exit(1 if stale else 0)
