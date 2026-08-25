from __future__ import annotations

import time

from app.core.config import settings

QUEUE_KEY = "oneai:construction-twin:asset-workers"


def notify_workers(tokens: int = 1) -> None:
    try:
        import redis
        client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=0.3, socket_timeout=0.3)
        for _ in range(max(1, min(tokens, 64))):
            client.lpush(QUEUE_KEY, "wake")
    except Exception:
        # The database remains the durable queue. Redis is only a low-latency wake-up channel.
        return


def wait_for_signal(timeout: float | None = None) -> None:
    timeout = settings.asset_worker_poll_seconds if timeout is None else timeout
    try:
        import redis
        client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=0.3, socket_timeout=max(1.0, timeout + 0.5))
        client.brpop(QUEUE_KEY, timeout=max(1, int(timeout)))
    except Exception:
        time.sleep(max(0.05, timeout))
