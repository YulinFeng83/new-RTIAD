"""
Track dataclass — represents a single tracked person across frames.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import numpy as np


class PersonLabel(str, Enum):
    UNKNOWN = "unknown"
    EMPLOYEE = "employee"
    CUSTOMER = "customer"


@dataclass
class TrackPoint:
    bbox: tuple[int, int, int, int]      # x1, y1, x2, y2
    centroid: tuple[int, int]            # cx, cy
    timestamp: float
    frame_id: int


@dataclass
class Track:
    track_id: int
    camera_id: str

    history: list[TrackPoint] = field(default_factory=list)

    label: PersonLabel = PersonLabel.UNKNOWN
    label_confidence: float = 0.0
    label_sticky: bool = False
    label_strategy_scores: dict[str, float] = field(default_factory=dict)

    first_seen: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    is_active: bool = True

    _last_classified_frame: int = 0

    @property
    def current_bbox(self) -> Optional[tuple[int, int, int, int]]:
        return self.history[-1].bbox if self.history else None

    @property
    def current_centroid(self) -> Optional[tuple[int, int]]:
        return self.history[-1].centroid if self.history else None

    @property
    def previous_centroid(self) -> Optional[tuple[int, int]]:
        return self.history[-2].centroid if len(self.history) >= 2 else None

    def add_point(
        self,
        bbox: tuple[int, int, int, int],
        frame_id: int,
        timestamp: Optional[float] = None,
    ) -> None:
        ts = timestamp or time.time()
        cx = (bbox[0] + bbox[2]) // 2
        cy = (bbox[1] + bbox[3]) // 2
        self.history.append(TrackPoint(bbox=bbox, centroid=(cx, cy), timestamp=ts, frame_id=frame_id))
        self.last_seen = ts

    def crop_from_frame(self, frame: np.ndarray) -> Optional[np.ndarray]:
        """Extract the person crop from the given frame using the latest bbox."""
        bbox = self.current_bbox
        if bbox is None:
            return None
        x1, y1, x2, y2 = bbox
        h, w = frame.shape[:2]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)
        if x2 <= x1 or y2 <= y1:
            return None
        return frame[y1:y2, x1:x2]
