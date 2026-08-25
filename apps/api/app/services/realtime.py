"""Live project events.

Comments and job progress used to require a refresh. This adds a WebSocket channel per
project, with two deliberate properties:

* **It survives more than one API replica.** In-process fan-out only reaches clients
  attached to the same worker. Events are therefore published to Redis and every replica
  relays what it receives to its own sockets. Without Redis the channel still works
  inside a single process, and says so, rather than silently dropping half the events.
* **It is an accelerator, not a source of truth.** Clients keep polling on a slow timer;
  the socket only makes updates arrive sooner. A dropped connection degrades latency,
  never correctness.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import Any

from app.core.config import settings
from app.core.time import utcnow

log = logging.getLogger(__name__)

CHANNEL = "oneai:construction-twin:events"


def _channel_key(tenant_id: str, project_id: str) -> str:
    return f"{tenant_id}:{project_id}"


class EventHub:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue]] = {}
        self._relay_task: asyncio.Task | None = None
        self._redis_ok = False

    # ---------------------------------------------------------------- publish
    def publish(self, tenant_id: str, project_id: str, event_type: str, payload: dict[str, Any]) -> None:
        """Fire-and-forget from synchronous request handlers."""
        message = {
            "type": event_type,
            "tenant_id": tenant_id,
            "project_id": project_id,
            "at": utcnow().isoformat(),
            # Payloads come straight from ORM rows and carry datetimes. `send_json` would
            # raise on those, and the socket would close mid-stream with no explanation,
            # so everything is normalised to JSON-safe types before it is queued.
            "payload": json.loads(json.dumps(payload, default=str)),
        }
        self._deliver_local(message)
        try:
            import redis

            client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=0.3, socket_timeout=0.3)
            client.publish(CHANNEL, json.dumps(message, default=str))
        except Exception:
            # Redis is the cross-replica path only; local subscribers already have it.
            return

    def _deliver_local(self, message: dict[str, Any]) -> None:
        key = _channel_key(message["tenant_id"], message["project_id"])
        for queue in list(self._subscribers.get(key, ())):
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(message)

    # -------------------------------------------------------------- subscribe
    async def subscribe(self, tenant_id: str, project_id: str) -> asyncio.Queue:
        key = _channel_key(tenant_id, project_id)
        queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._subscribers.setdefault(key, set()).add(queue)
        await self.ensure_relay()
        return queue

    def unsubscribe(self, tenant_id: str, project_id: str, queue: asyncio.Queue) -> None:
        key = _channel_key(tenant_id, project_id)
        listeners = self._subscribers.get(key)
        if not listeners:
            return
        listeners.discard(queue)
        if not listeners:
            self._subscribers.pop(key, None)

    @property
    def cross_replica(self) -> bool:
        return self._redis_ok

    # ------------------------------------------------------------------ relay
    async def ensure_relay(self) -> None:
        if self._relay_task and not self._relay_task.done():
            return
        self._relay_task = asyncio.create_task(self._relay())

    async def _relay(self) -> None:
        """Bridge Redis pub/sub into local queues so every replica sees every event."""
        try:
            import redis.asyncio as redis_async
        except ImportError:
            self._redis_ok = False
            return
        while True:
            try:
                client = redis_async.Redis.from_url(settings.redis_url)
                pubsub = client.pubsub()
                await pubsub.subscribe(CHANNEL)
                self._redis_ok = True
                async for raw in pubsub.listen():
                    if raw.get("type") != "message":
                        continue
                    try:
                        message = json.loads(raw["data"])
                    except (TypeError, ValueError):
                        continue
                    self._deliver_local(message)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._redis_ok = False
                log.warning("realtime relay lost, retrying: %s", exc)
                await asyncio.sleep(2.0)


hub = EventHub()
