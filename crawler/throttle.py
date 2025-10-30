import random
import threading
import time


class RequestThrottler:
    """Serialize outbound requests with a configurable pause to reduce blocking risk."""

    def __init__(self, min_delay: float = 0.0, max_delay: float | None = None) -> None:
        if min_delay < 0:
            raise ValueError("min_delay must be non-negative")

        if max_delay is None:
            max_delay = min_delay

        if max_delay < min_delay:
            raise ValueError("max_delay must be greater than or equal to min_delay")

        self.min_delay = min_delay
        self.max_delay = max_delay
        self._last_request: float | None = None
        self._lock = threading.Lock()

    def wait(self) -> None:
        """Sleep if necessary so that consecutive requests are spaced apart."""
        if self.max_delay <= 0:
            return

        delay = random.uniform(self.min_delay, self.max_delay)
        with self._lock:
            now = time.monotonic()
            if self._last_request is None:
                self._last_request = now
                sleep_for = 0.0
            else:
                elapsed = now - self._last_request
                sleep_for = max(delay - elapsed, 0.0)
                self._last_request = now + sleep_for

        if sleep_for > 0:
            time.sleep(sleep_for)
