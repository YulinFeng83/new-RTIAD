from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from typing import Protocol

from src.events.typed_events import FloorPositionSampleEvent, format_event_time
from src.sessions.visit_session_manager import VisitSession
from src.tracking.track import Track


class FloorCoordinateMapper(Protocol):
    def image_to_floor(
        self,
        camera_id: str,
        point: tuple[int, int],
    ) -> tuple[float, float] | None:
        """Return calibrated floor coordinates, or None when unavailable."""


@dataclass
class FloorPositionSampleState:
    last_floor_x: float
    last_floor_y: float
    seq: int


class FloorPositionSampler:
    """Owns movement-threshold state for calibrated floor_position_sample events."""

    def __init__(self, mapper: FloorCoordinateMapper, movement_threshold: float):
        self._mapper = mapper
        self._movement_threshold = movement_threshold
        self._state_by_visit: dict[str, FloorPositionSampleState] = {}

    def maybe_sample(
        self,
        store_id: str,
        camera_id: str,
        zone_id: str | None,
        track: Track,
        visit: VisitSession,
        emitted_at: float,
    ) -> FloorPositionSampleEvent | None:
        foot_point = self._foot_point(track)
        if foot_point is None:
            return None

        floor_point = self._mapper.image_to_floor(camera_id, foot_point)
        if floor_point is None:
            return None

        floor_x, floor_y = floor_point
        previous = self._state_by_visit.get(visit.store_visit_id)
        if previous is not None:
            dx = floor_x - previous.last_floor_x
            dy = floor_y - previous.last_floor_y
            if ((dx * dx) + (dy * dy)) ** 0.5 < self._movement_threshold:
                return None
            seq = previous.seq + 1
        else:
            seq = 1

        self._state_by_visit[visit.store_visit_id] = FloorPositionSampleState(floor_x, floor_y, seq)
        return FloorPositionSampleEvent(
            position_id=self._make_position_id(visit.store_visit_id, camera_id, track.track_id, seq),
            store_visit_id=visit.store_visit_id,
            store_id=store_id,
            zone_id=zone_id,
            track_id=str(track.track_id),
            seq=seq,
            floor_x=floor_x,
            floor_y=floor_y,
            emitted_at=format_event_time(emitted_at),
            classification_label=track.label.value,
            max_employee_probability=track.max_employee_probability,
            edge_emitted_at=format_event_time(time.time()),
        )

    def forget_visit(self, store_visit_id: str) -> None:
        self._state_by_visit.pop(store_visit_id, None)

    def _make_position_id(
        self,
        store_visit_id: str,
        camera_id: str,
        track_id: int,
        seq: int,
    ) -> str:
        raw = f"{store_visit_id}|{camera_id}|{track_id}|{seq}"
        digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()
        return f"pos-{digest[:20]}"

    def _foot_point(self, track: Track) -> tuple[int, int] | None:
        bbox = track.current_bbox
        if bbox is None:
            return None
        x1, _y1, x2, y2 = bbox
        return (int(round((x1 + x2) / 2.0)), int(round(y2)))
