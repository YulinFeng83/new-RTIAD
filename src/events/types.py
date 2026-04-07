from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from typing import Optional


@dataclass
class BaseEvent:
    event_type: str
    tenant_id: str
    store_id: str
    camera_id: str
    event_id: Optional[str] = None
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
    session_completed_at: Optional[float] = None
    session_duration_seconds: float = 0.0
    total_dwell_seconds: float = 0.0
    session_entry_count: int = 0
    session_exit_count: int = 0
    visited_zones: list[str] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self))


@dataclass
class FootfallUpdate:
    event_type: str
    tenant_id: str
    store_id: str
    camera_id: str
    event_id: Optional[str] = None
    track_id: Optional[int] = None
    store_visit_session_id: Optional[str] = None
    previous_group_id: Optional[str] = None
    group_id: Optional[str] = None
    group_probability: float = 0.0
    total_entries: int = 0
    total_exits: int = 0
    current_in_store: int = 0
    employees_filtered: int = 0
    shopping_party_entries: int = 0
    timestamp: float = field(default_factory=time.time)
    session_completed_at: Optional[float] = None

    def to_json(self) -> str:
        return json.dumps(asdict(self))
