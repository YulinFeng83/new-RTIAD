"""
Zone dataclass — represents a drawn polygon zone on a camera feed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ZoneType(str, Enum):
    ENTRY = "entry"
    EXIT = "exit"
    BIDIRECTIONAL = "bidirectional"
    STAFF_ONLY = "staff_only"


@dataclass
class Zone:
    zone_id: str
    camera_id: str
    polygon: list[tuple[int, int]]       # List of (x, y) vertices
    zone_type: ZoneType = ZoneType.BIDIRECTIONAL
    business_zone_type: str = "aisle"
    direction_vector: tuple[float, float] = (0.0, -1.0)  # Normal: "into store"
    name: str = ""
    promo_zone_flag: bool = False

    @property
    def is_entry(self) -> bool:
        return self.zone_type in (ZoneType.ENTRY, ZoneType.BIDIRECTIONAL)

    @property
    def is_exit(self) -> bool:
        return self.zone_type in (ZoneType.EXIT, ZoneType.BIDIRECTIONAL)
