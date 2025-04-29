from asyncio import Lock, sleep
from time import monotonic

class RateLimiter:
    """Token‑bucket limiter tuned for GitHub GraphQL cost points."""

    def __init__(self, *, capacity: int, refill_per_min: int):
        self.capacity = capacity
        self._tokens = capacity
        self._refill_rate = refill_per_min / 60  # tokens per second
        self._updated = monotonic()
        self._lock = Lock()

    async def acquire(self, cost: int):
        async with self._lock:
            await self._refill()
            while self._tokens < cost:
                sleep_time = (cost - self._tokens) / self._refill_rate
                await sleep(sleep_time)
                await self._refill()
            self._tokens -= cost

    async def _refill(self):
        now = monotonic()
        delta = now - self._updated
        self._updated = now
        self._tokens = min(self.capacity, self._tokens + delta * self._refill_rate)