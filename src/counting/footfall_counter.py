"""
Simplified footfall counter.

Counts individual customers entering/exiting through configured zones.
Employees are filtered out. Tracks in-store occupancy.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field

from src.tracking.track import PersonLabel, Track
from src.zones.crossing_detector import CrossingResult
from src.zones.zone import Zone, ZoneType

logger = logging.getLogger(__name__)


@dataclass
class FootfallStats:
    total_entries: int = 0
    total_exits: int = 0
    current_in_store: int = 0
    employees_filtered: int = 0

    def to_dict(self) -> dict:
        return {
            "total_entries": self.total_entries,
            "total_exits": self.total_exits,
            "current_in_store": self.current_in_store,
            "employees_filtered": self.employees_filtered,
        }


@dataclass
class FootfallEvent:
    event_type: str          # "entry" or "exit"
    track_id: int
    zone_id: str
    camera_id: str
    person_label: str
    timestamp: float
    stats_snapshot: dict = field(default_factory=dict)


class FootfallCounter:
    """Counts customer entries/exits and maintains in-store occupancy."""

    def __init__(self):
        self._stats = FootfallStats()
        self._lock = threading.Lock()
        self._events: list[FootfallEvent] = []

    @property
    def stats(self) -> FootfallStats:
        with self._lock:
            return FootfallStats(
                total_entries=self._stats.total_entries,
                total_exits=self._stats.total_exits,
                current_in_store=self._stats.current_in_store,
                employees_filtered=self._stats.employees_filtered,
            )

    def process_crossing(
        self,
        track: Track,
        crossing: CrossingResult,
        zone: Zone,
        timestamp: float,
    ) -> FootfallEvent | None:
        """
        Process a zone crossing event. Returns a FootfallEvent if it's a
        countable customer crossing, or None if filtered.
        """
        if track.label == PersonLabel.EMPLOYEE:
            with self._lock:
                self._stats.employees_filtered += 1
            logger.debug("Filtered employee track %d at zone %s", track.track_id, crossing.zone_id)
            return None

        is_entry = (
            (crossing.direction == "entering" and zone.is_entry) or
            (crossing.direction == "exiting" and zone.zone_type == ZoneType.EXIT)
        )
        is_exit = (
            (crossing.direction == "exiting" and zone.is_exit) or
            (crossing.direction == "entering" and zone.zone_type == ZoneType.EXIT)
        )

        if crossing.direction == "entering" and zone.is_entry:
            event_type = "entry"
        elif crossing.direction == "exiting" and zone.is_exit:
            event_type = "exit"
        elif crossing.direction == "exiting" and zone.zone_type == ZoneType.ENTRY:
            event_type = "exit"
        elif crossing.direction == "entering" and zone.zone_type == ZoneType.EXIT:
            event_type = "entry"
        else:
            return None

        with self._lock:
            if event_type == "entry":
                self._stats.total_entries += 1
            elif event_type == "exit":
                self._stats.total_exits += 1

            self._stats.current_in_store = max(
                0, self._stats.total_entries - self._stats.total_exits
            )
            snapshot = self._stats.to_dict()

        event = FootfallEvent(
            event_type=event_type,
            track_id=track.track_id,
            zone_id=crossing.zone_id,
            camera_id=track.camera_id,
            person_label=track.label.value,
            timestamp=timestamp,
            stats_snapshot=snapshot,
        )

        self._events.append(event)
        logger.info(
            "Footfall %s: track %d at zone %s | In-store: %d",
            event_type,
            track.track_id,
            crossing.zone_id,
            snapshot["current_in_store"],
        )
        return event

    def pop_events(self) -> list[FootfallEvent]:
        """Return and clear pending events (for Event Hub publishing)."""
        events = self._events
        self._events = []
        return events

    def reset(self) -> None:
        with self._lock:
            self._stats = FootfallStats()
        self._events.clear()
