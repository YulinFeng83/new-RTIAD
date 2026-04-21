from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import ClassVar


def format_event_time(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, tz=UTC).isoformat()


@dataclass(frozen=True)
class SessionCompletedEvent:
    event_type: ClassVar[str] = "session_completed"

    store_visit_id: str
    store_id: str
    track_id: str
    classification_label: str
    max_employee_probability: float
    last_group_id: str | None
    group_visitor_count: int
    group_was_active_at_exit: bool
    segment_count: int
    close_reason: str
    session_duration_seconds: float
    total_dwell_seconds: float
    session_entry_count: int
    session_exit_count: int
    session_completed_at: str
    edge_emitted_at: str

    def to_eventhub_payload(self) -> dict[str, object]:
        return {"event_type": self.event_type, **asdict(self)}


@dataclass(frozen=True)
class ZoneExitedEvent:
    event_type: ClassVar[str] = "zone_exited"

    visit_id: str
    zone_id: str
    store_id: str
    camera_id: str
    store_visit_id: str
    dwell_seconds: float
    max_dwell_bucket: str | None
    entered_at: str
    exited_at: str
    classification_label: str
    max_employee_probability: float
    edge_emitted_at: str

    def to_eventhub_payload(self) -> dict[str, object]:
        return {"event_type": self.event_type, **asdict(self)}


@dataclass(frozen=True)
class DoorCrossedEvent:
    event_type: ClassVar[str] = "door_crossed"

    crossing_id: str
    store_id: str
    camera_id: str
    store_visit_id: str
    direction: str
    crossed_at: str
    classification_label: str
    max_employee_probability: float
    edge_emitted_at: str

    def to_eventhub_payload(self) -> dict[str, object]:
        return {"event_type": self.event_type, **asdict(self)}


@dataclass(frozen=True)
class FloorPositionSampleEvent:
    event_type: ClassVar[str] = "floor_position_sample"

    position_id: str
    store_visit_id: str
    store_id: str
    zone_id: str | None
    track_id: str
    seq: int
    floor_x: float
    floor_y: float
    emitted_at: str
    classification_label: str
    max_employee_probability: float
    edge_emitted_at: str

    def to_eventhub_payload(self) -> dict[str, object]:
        return {"event_type": self.event_type, **asdict(self)}
