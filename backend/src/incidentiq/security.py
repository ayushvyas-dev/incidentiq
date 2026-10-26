"""API token authorization and process-local request limits."""

from collections import OrderedDict, deque
from hashlib import sha256
from threading import Lock
from time import monotonic


class SlidingWindowLimiter:
    # shortcut: per-process and per-client-address limits, use Redis for multi-instance deployments.
    def __init__(self, max_requests: int, window_seconds: int = 60, max_clients: int = 10_000):
        if max_requests < 1 or window_seconds < 1:
            raise ValueError("rate limit and window must be positive")
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.max_clients = max_clients
        self._lock = Lock()
        self._clients: OrderedDict[str, deque[float]] = OrderedDict()

    def allow(self, client: str, now: float | None = None) -> tuple[bool, int]:
        current = monotonic() if now is None else now
        key = sha256(client.encode()).hexdigest()
        with self._lock:
            events = self._clients.pop(key, deque())
            while events and events[0] <= current - self.window_seconds:
                events.popleft()
            if len(events) >= self.max_requests:
                self._clients[key] = events
                retry_after = max(1, int(events[0] + self.window_seconds - current + 0.999))
                return False, retry_after
            events.append(current)
            self._clients[key] = events
            while len(self._clients) > self.max_clients:
                self._clients.popitem(last=False)
            return True, 0
