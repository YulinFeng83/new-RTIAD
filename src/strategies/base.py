"""
Abstract base class for employee/customer classification strategies.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

import numpy as np

from src.tracking.track import Track


class ClassificationStrategy(ABC):
    """
    Each strategy independently scores a person from 0.0 (customer) to 1.0 (employee).
    """

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    def score(
        self,
        crop: Optional[np.ndarray],
        track: Track,
        context: dict[str, Any],
    ) -> float:
        """
        Return a score between 0.0 and 1.0.

        Args:
            crop: Cropped person image (may be None if unavailable).
            track: The Track object for this person.
            context: Shared context dict with keys like "current_time",
                     "store_open_time", "frame_id", etc.
        """
        ...

    def initialize(self) -> None:
        """Optional: load models or pre-compute data. Called once at startup."""

    def on_config_change(self, strategy_config: dict) -> None:
        """Optional: react to hot-reload config changes."""
