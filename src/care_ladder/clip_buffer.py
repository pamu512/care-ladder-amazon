"""Rolling pre-event clip buffer of recent frames."""

from __future__ import annotations

from collections import deque
from typing import Deque

import numpy as np


class ClipBuffer:
    """Keep frames covering approximately the last ``seconds`` of wall time."""

    def __init__(self, seconds: float) -> None:
        if seconds <= 0:
            raise ValueError("seconds must be positive")
        self.seconds = float(seconds)
        self._items: Deque[tuple[float, np.ndarray]] = deque()

    def push(self, frame: np.ndarray, t: float) -> None:
        """Append a frame stamped at time ``t`` and drop entries older than the window."""
        self._items.append((float(t), frame))
        self._trim(now=float(t))

    def snapshot(self, now: float | None = None) -> list[np.ndarray]:
        """Return frames in the last ``seconds`` ending at ``now`` (or latest stamp)."""
        if not self._items:
            return []
        if now is None:
            now = self._items[-1][0]
        self._trim(now=float(now))
        return [frame for _, frame in self._items]

    def _trim(self, now: float) -> None:
        cutoff = now - self.seconds
        while self._items and self._items[0][0] < cutoff:
            self._items.popleft()
