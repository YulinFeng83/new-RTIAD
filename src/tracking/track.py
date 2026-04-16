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


UNGROUPED_LINEAGE_TOKEN = "ungrouped"


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
    store_visit_session_id: str = ""
    store_visit_started_at: float = 0.0
    session_completed_emitted: bool = False
    session_completed_at: float | None = None
    pending_exit_at: float | None = None
    last_exit_seen_at: float | None = None

    _last_classified_frame: int = 0
    entry_count: int = 0
    exit_count: int = 0
    zones_visited: list[str] = field(default_factory=list)
    zone_visit_counts: dict[str, int] = field(default_factory=dict)
    zone_entry_times: dict[str, float] = field(default_factory=dict)
    zone_dwell_seconds: dict[str, float] = field(default_factory=dict)
    active_zone_session_ids: dict[str, str] = field(default_factory=dict)

    employee_probability: float = 0.0
    customer_probability: float = 0.0
    unknown_probability: float = 1.0

    group_id: str | None = None
    previous_group_id: str | None = None
    last_group_seen_at: float | None = None
    group_probability: float = 0.0
    group_lineage: list[str] = field(default_factory=list)
    split_detected_flag: bool = False
    regroup_detected_flag: bool = False
    merge_detected_flag: bool = False

    store_entry_zone_id: str | None = None
    store_exit_zone_id: str | None = None
    store_entry_at: float | None = None
    store_exit_at: float | None = None

    clip_signals: dict[str, float] = field(default_factory=dict)
    derived_features: dict[str, float] = field(default_factory=dict)
    decision_reasons: list[str] = field(default_factory=list)

    counted_entry: bool = False
    counted_exit: bool = False

    def __post_init__(self) -> None:
        if self.store_visit_started_at <= 0.0:
            self.store_visit_started_at = self.first_seen
        if not self.store_visit_session_id:
            self.store_visit_session_id = self._make_store_visit_session_id(self.store_visit_started_at)

    @property
    def current_bbox(self) -> Optional[tuple[int, int, int, int]]:
        return self.history[-1].bbox if self.history else None

    @property
    def current_centroid(self) -> Optional[tuple[int, int]]:
        return self.history[-1].centroid if self.history else None

    @property
    def previous_centroid(self) -> Optional[tuple[int, int]]:
        return self.history[-2].centroid if len(self.history) >= 2 else None

    @property
    def session_duration_seconds(self) -> float:
        return max(0.0, self.last_seen - self.first_seen)

    @property
    def store_visit_duration_seconds(self) -> float:
        return max(0.0, self.last_seen - self.store_visit_started_at)

    @property
    def total_dwell_seconds(self) -> float:
        return sum(self.zone_dwell_seconds.values())

    @property
    def current_speed(self) -> float:
        if len(self.history) < 2:
            return 0.0
        p1 = self.history[-2].centroid
        p2 = self.history[-1].centroid
        dt = max(1e-6, self.history[-1].timestamp - self.history[-2].timestamp)
        dx = p2[0] - p1[0]
        dy = p2[1] - p1[1]
        return ((dx * dx + dy * dy) ** 0.5) / dt

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

    def remember_group_membership(self, timestamp: Optional[float] = None) -> None:
        if not self.group_id:
            return
        ts = timestamp or self.last_seen or time.time()
        self.previous_group_id = self.group_id
        self.last_group_seen_at = ts

    def record_group_transition(
        self,
        previous_group_id: str | None,
        new_group_id: str | None,
    ) -> None:
        if previous_group_id == new_group_id:
            return

        if previous_group_id and (not self.group_lineage or self.group_lineage[-1] != previous_group_id):
            self.group_lineage.append(previous_group_id)

        if previous_group_id and new_group_id is None:
            self.split_detected_flag = True
            if not self.group_lineage or self.group_lineage[-1] != UNGROUPED_LINEAGE_TOKEN:
                self.group_lineage.append(UNGROUPED_LINEAGE_TOKEN)
            return

        if new_group_id is None:
            return

        if previous_group_id is None:
            if self.previous_group_id == new_group_id or new_group_id in self.group_lineage:
                self.regroup_detected_flag = True
        elif previous_group_id != new_group_id:
            self.merge_detected_flag = True
            if new_group_id in self.group_lineage:
                self.regroup_detected_flag = True

        if not self.group_lineage or self.group_lineage[-1] != new_group_id:
            self.group_lineage.append(new_group_id)

    def clear_pending_exit(self) -> None:
        self.pending_exit_at = None
        self.last_exit_seen_at = None

    def mark_pending_exit(self, timestamp: float, cooldown_seconds: float) -> None:
        self.pending_exit_at = timestamp + cooldown_seconds
        self.last_exit_seen_at = timestamp

    def mark_session_completed(self, timestamp: float) -> None:
        self.session_completed_emitted = True
        self.session_completed_at = timestamp
        self.clear_pending_exit()

    def refresh_session_activity(self, timestamp: Optional[float] = None) -> None:
        if self.last_exit_seen_at is None or self.session_completed_emitted:
            return
        ts = timestamp or self.last_seen
        if ts > self.last_exit_seen_at:
            self.clear_pending_exit()

    def _make_store_visit_session_id(self, timestamp: float) -> str:
        return f"sess-{self.track_id}-{int(timestamp * 1000)}"

    def mark_store_entry(self, zone_id: str, timestamp: float) -> None:
        if self.store_entry_zone_id is None:
            self.store_entry_zone_id = zone_id
        if self.store_entry_at is None:
            self.store_entry_at = timestamp

    def mark_store_exit(self, zone_id: str, timestamp: float) -> None:
        self.store_exit_zone_id = zone_id
        self.store_exit_at = timestamp

    def mark_zone_entered(self, zone_id: str, timestamp: float) -> None:
        self.zone_entry_times[zone_id] = timestamp
        if zone_id not in self.zones_visited:
            self.zones_visited.append(zone_id)

    def mark_zone_exited(self, zone_id: str, timestamp: float) -> float:
        start = self.zone_entry_times.pop(zone_id, None)
        if start is None:
            return 0.0
        dwell = max(0.0, timestamp - start)
        self.zone_dwell_seconds[zone_id] = self.zone_dwell_seconds.get(zone_id, 0.0) + dwell
        return dwell

    def start_zone_session(self, zone_id: str, timestamp: Optional[float] = None) -> str:
        ts = timestamp or time.time()
        visit_count = self.zone_visit_counts.get(zone_id, 0) + 1
        self.zone_visit_counts[zone_id] = visit_count
        self.entry_count += 1
        self.mark_zone_entered(zone_id, ts)
        session_id = f"zsess-{zone_id}-{visit_count:03d}"
        self.active_zone_session_ids[zone_id] = session_id
        return session_id

    def end_zone_session(
        self,
        zone_id: str,
        timestamp: Optional[float] = None,
    ) -> tuple[Optional[str], float]:
        ts = timestamp or time.time()
        self.exit_count += 1
        session_id = self.active_zone_session_ids.pop(zone_id, None)
        dwell_seconds = self.mark_zone_exited(zone_id, ts)
        return session_id, dwell_seconds

    def active_zone_session_id(self, zone_id: str) -> Optional[str]:
        return self.active_zone_session_ids.get(zone_id)

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
