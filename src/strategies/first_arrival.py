"""
First-arrival classification strategy.

People detected within a configurable time window before store opening
are assumed to be employees (up to a max count cap). This is a
supplementary signal — never the sole classifier.
"""

from __future__ import annotations

import logging
from datetime import datetime, time as dt_time
from typing import Any, Optional

import numpy as np

from src.strategies.base import ClassificationStrategy
from src.tracking.track import Track

logger = logging.getLogger(__name__)


class FirstArrivalStrategy(ClassificationStrategy):

    def __init__(
        self,
        store_open_time: str = "09:00",
        pre_open_window_minutes: int = 60,
        max_first_arrivals: int = 20,
    ):
        self._store_open_time = self._parse_time(store_open_time)
        self._pre_open_minutes = pre_open_window_minutes
        self._max_count = max_first_arrivals
        self._arrival_count = 0
        self._counted_tracks: set[int] = set()

    @property
    def name(self) -> str:
        return "first_arrival"

    def score(
        self,
        crop: Optional[np.ndarray],
        track: Track,
        context: dict[str, Any],
    ) -> float:
        now = datetime.now().time()

        if not self._is_in_pre_open_window(now):
            return 0.5  # neutral — outside the window

        if track.track_id in self._counted_tracks:
            return 0.85

        if self._arrival_count >= self._max_count:
            return 0.5

        self._counted_tracks.add(track.track_id)
        self._arrival_count += 1
        logger.debug(
            "First arrival #%d: track %d", self._arrival_count, track.track_id
        )
        return 0.85

    def _is_in_pre_open_window(self, now: dt_time) -> bool:
        open_hour = self._store_open_time.hour
        open_min = self._store_open_time.minute
        open_total_min = open_hour * 60 + open_min
        window_start_min = open_total_min - self._pre_open_minutes
        now_total_min = now.hour * 60 + now.minute

        return window_start_min <= now_total_min < open_total_min

    def reset_daily(self) -> None:
        """Call at the start of each day to reset counters."""
        self._arrival_count = 0
        self._counted_tracks.clear()
        logger.info("First-arrival counters reset")

    @staticmethod
    def _parse_time(t: str) -> dt_time:
        parts = t.strip().split(":")
        return dt_time(int(parts[0]), int(parts[1]))

    def on_config_change(self, strategy_config: dict) -> None:
        if "pre_open_window_minutes" in strategy_config:
            self._pre_open_minutes = strategy_config["pre_open_window_minutes"]
        if "max_first_arrivals" in strategy_config:
            self._max_count = strategy_config["max_first_arrivals"]
