from __future__ import annotations

import os
import socket
import sys
import time
from uuid import uuid4

from app.core.config import settings
from app.db.base import SessionLocal
from app.services.distributed_asset_pipeline import run_worker_cycle
from app.services.migrations import migration_status, upgrade_to_head
from app.services.worker_heartbeat import mark_worker_offline, record_worker_heartbeat
from app.services.worker_signal import wait_for_signal


def worker_id() -> str:
    configured = os.getenv("ASSET_WORKER_ID")
    return configured or f"{socket.gethostname()}-{os.getpid()}-{uuid4().hex[:6]}"


def heartbeat(identity: str, status: str = "online", **meta) -> None:
    with SessionLocal() as db:
        record_worker_heartbeat(
            db,
            identity,
            status=status,
            worker_type="asset",
            meta={"storage": settings.asset_storage_backend, **meta},
        )


def main() -> None:
    if settings.auto_migrate:
        upgrade_to_head()
    elif settings.require_migration_head:
        status = migration_status()
        if not status["at_head"]:
            raise RuntimeError(f"Database migration is not at head: {status}")
    identity = worker_id()
    heartbeat(identity, "online", state="starting")
    print(
        f"[asset-worker] started id={identity} version={settings.app_version} storage={settings.asset_storage_backend}",
        flush=True,
    )
    last_heartbeat = 0.0
    try:
        while True:
            try:
                now = time.monotonic()
                if now - last_heartbeat >= settings.worker_heartbeat_seconds:
                    heartbeat(identity, "online", state="polling")
                    last_heartbeat = now
                worked = run_worker_cycle(identity)
                if worked:
                    heartbeat(identity, "online", state="working")
                else:
                    wait_for_signal(settings.asset_worker_poll_seconds)
            except KeyboardInterrupt:
                break
            except Exception as exc:
                heartbeat(identity, "online", state="error", error=str(exc))
                print(f"[asset-worker] cycle error: {exc}", file=sys.stderr, flush=True)
                time.sleep(max(0.2, settings.asset_worker_poll_seconds))
    finally:
        with SessionLocal() as db:
            mark_worker_offline(db, identity)
        print("[asset-worker] stopped", flush=True)


if __name__ == "__main__":
    main()
