from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Optional


def _format_event_time(value: Optional[float]) -> Optional[str]:
    if value is None:
        return None
    # Convert UTC timestamp to local timezone ISO format (include offset)
    return datetime.fromtimestamp(value, tz=UTC).astimezone().isoformat()


@dataclass
class BaseEvent:
    """Runtime event with a Fabric-compatible serialization view for Event Hub."""

    event_type: str
    tenant_id: str
    store_id: str
    camera_id: str
    timestamp: float = field(default_factory=time.time)
    track_id: Optional[int] = None
    store_visit_session_id: Optional[str] = None
    previous_group_id: Optional[str] = None
    group_id: Optional[str] = None
    zone_id: Optional[str] = None
    direction: Optional[str] = None
    classification_label: Optional[str] = None
    employee_probability: float = 0.0
    customer_probability: float = 0.0
    unknown_probability: float = 1.0
    group_probability: float = 0.0
    dwell_seconds: float = 0.0
    zone_session_id: Optional[str] = None
    has_dwell_flag: bool = False
    window_start: Optional[float] = None
    window_end: Optional[float] = None
    group_visitor_count: int = 0
    zone_visitors: int = 0
    max_dwell_bucket: Optional[str] = None
    promo_zone_flag: bool = False
    event_id: Optional[str] = None
    session_completed_at: Optional[float] = None
    session_duration_seconds: float = 0.0
    total_dwell_seconds: float = 0.0
    session_entry_count: int = 0
    session_exit_count: int = 0
    visited_zones: list[str] = field(default_factory=list)
    session_completion_reason: Optional[str] = None
    final_group_id: Optional[str] = None
    group_lineage: list[str] = field(default_factory=list)
    split_detected_flag: bool = False
    regroup_detected_flag: bool = False
    merge_detected_flag: bool = False
    entry_zone_id: Optional[str] = None
    exit_zone_id: Optional[str] = None
    entry_timestamp: Optional[float] = None
    exit_timestamp: Optional[float] = None
    zone_dwell_map: dict[str, float] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    def to_eventhub_payload(self) -> dict[str, object]:
        return {
            "event_type": self.event_type,
            "tenant_id": self.tenant_id,
            "store_id": self.store_id,
            "camera_id": self.camera_id,
            "timestamp": _format_event_time(self.timestamp),
            "track_id": self.track_id,
            "group_id": self.group_id,
            "zone_id": self.zone_id,
            "direction": self.direction,
            "classification_label": self.classification_label,
            "employee_probability": self.employee_probability,
            "customer_probability": self.customer_probability,
            "unknown_probability": self.unknown_probability,
            "group_probability": self.group_probability,
            "dwell_seconds": self.dwell_seconds,
            "zone_session_id": self.zone_session_id,
            "has_dwell_flag": self.has_dwell_flag,
            "window_start": _format_event_time(self.window_start),
            "window_end": _format_event_time(self.window_end),
            "group_visitor_count": self.group_visitor_count,
            "zone_visitors": self.zone_visitors,
            "max_dwell_bucket": self.max_dwell_bucket,
            "promo_zone_flag": self.promo_zone_flag,
            "event_id": self.event_id,
            "total_entries": None,
            "total_exits": None,
            "current_in_store": None,
            "employees_filtered": None,
            "shopping_party_entries": None,
            "store_visit_session_id": self.store_visit_session_id,
            "previous_group_id": self.previous_group_id,
            "session_completed_at": _format_event_time(self.session_completed_at),
            "session_duration_seconds": self.session_duration_seconds,
            "total_dwell_seconds": self.total_dwell_seconds,
            "session_entry_count": self.session_entry_count,
            "session_exit_count": self.session_exit_count,
            "visited_zones": self.visited_zones,
        }


@dataclass
class FootfallUpdate:
    """Runtime footfall event with a Fabric-compatible serialization view."""

    event_type: str
    tenant_id: str
    store_id: str
    camera_id: str
    timestamp: float = field(default_factory=time.time)
    track_id: Optional[int] = None
    group_id: Optional[str] = None
    store_visit_session_id: Optional[str] = None
    previous_group_id: Optional[str] = None
    group_probability: float = 0.0
    event_id: Optional[str] = None
    counting_event_type: Optional[str] = None
    entry_delta: int = 0
    exit_delta: int = 0
    source_zone_id: Optional[str] = None
    source_direction: Optional[str] = None
    zone_session_id: Optional[str] = None
    total_entries: int = 0
    total_exits: int = 0
    current_in_store: int = 0
    employees_filtered: int = 0
    shopping_party_entries: int = 0
    session_completed_at: Optional[float] = None

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    def to_eventhub_payload(self) -> dict[str, object]:
        return {
            "event_type": self.event_type,
            "tenant_id": self.tenant_id,
            "store_id": self.store_id,
            "camera_id": self.camera_id,
            "timestamp": _format_event_time(self.timestamp),
            "track_id": self.track_id,
            "group_id": self.group_id,
            "zone_id": self.source_zone_id,
            "direction": self.source_direction,
            "classification_label": None,
            "employee_probability": None,
            "customer_probability": None,
            "unknown_probability": None,
            "group_probability": self.group_probability,
            "dwell_seconds": None,
            "zone_session_id": self.zone_session_id,
            "has_dwell_flag": None,
            "window_start": None,
            "window_end": None,
            "group_visitor_count": None,
            "zone_visitors": None,
            "max_dwell_bucket": None,
            "promo_zone_flag": None,
            "event_id": self.event_id,
            "total_entries": self.total_entries,
            "total_exits": self.total_exits,
            "current_in_store": self.current_in_store,
            "employees_filtered": self.employees_filtered,
            "shopping_party_entries": self.shopping_party_entries,
            "store_visit_session_id": self.store_visit_session_id,
            "previous_group_id": self.previous_group_id,
            "session_completed_at": _format_event_time(self.session_completed_at),
            "session_duration_seconds": None,
            "total_dwell_seconds": None,
            "session_entry_count": None,
            "session_exit_count": None,
            "visited_zones": None,
        }
