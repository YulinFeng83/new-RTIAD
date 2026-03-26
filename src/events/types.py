"""
Event dataclasses for the RetailVision event system.

All events are JSON-serializable for Azure Event Hub publishing.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class CrossingEvent:
    track_id: int
    zone_id: str
    camera_id: str
    direction: str             # "entering" or "exiting"
    person_label: str          # "employee", "customer", "unknown"
    timestamp: float = field(default_factory=time.time)
    centroid: tuple[int, int] = (0, 0)

    def to_json(self) -> str:
        return json.dumps(asdict(self))


@dataclass
class FootfallUpdate:
    event_type: str            # "entry" or "exit"
    track_id: int
    zone_id: str
    camera_id: str
    total_entries: int = 0
    total_exits: int = 0
    current_in_store: int = 0
    employees_filtered: int = 0
    timestamp: float = field(default_factory=time.time)

    def to_json(self) -> str:
        return json.dumps(asdict(self))
