"""
Simplified footfall counter.

Counts individual customers entering/exiting through configured zones.
Employees are filtered out. Tracks in-store occupancy.
"""

from __future__ import annotations

import logging
import threading
import time
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
    shopping_party_entries: int = 0
    total_group_entries: int = 0
    total_group_exits: int = 0
    current_groups_in_store: int = 0

    def to_dict(self) -> dict:
        return {
            "total_entries": self.total_entries,
            "total_exits": self.total_exits,
            "current_in_store": self.current_in_store,
            "employees_filtered": self.employees_filtered,
            "shopping_party_entries": self.shopping_party_entries,
            "total_group_entries": self.total_group_entries,
            "total_group_exits": self.total_group_exits,
            "current_groups_in_store": self.current_groups_in_store,
        }


@dataclass
class FootfallEvent:
    event_type: str          # "entry" or "exit"
    track_id: int
    zone_id: str
    camera_id: str
    person_label: str
    timestamp: float
    group_id: str | None = None
    group_probability: float = 0.0
    people_count: int = 1
    shopping_party_count: int = 1
    stats_snapshot: dict = field(default_factory=dict)


class FootfallCounter:
    """Counts customer entries/exits and maintains in-store occupancy."""

    def __init__(self):
        self._stats = FootfallStats()
        self._lock = threading.Lock()
        self._events: list[FootfallEvent] = []
        self._counted_group_entries: set[str] = set()
        self._counted_group_exits: set[str] = set()
        self._counted_session_entries: set[str] = set()
        self._counted_session_exits: set[str] = set()

    @property
    def stats(self) -> FootfallStats:
        with self._lock:
            return FootfallStats(
                total_entries=self._stats.total_entries,
                total_exits=self._stats.total_exits,
                current_in_store=self._stats.current_in_store,
                employees_filtered=self._stats.employees_filtered,
                shopping_party_entries=self._stats.shopping_party_entries,
                total_group_entries=self._stats.total_group_entries,
                total_group_exits=self._stats.total_group_exits,
                current_groups_in_store=self._stats.current_groups_in_store,
            )

    def process_crossing(
        self,
        track: Track,
        crossing: CrossingResult,
        zone: Zone,
        timestamp: float,
        zone_session_id: str | None = None,
    ) -> FootfallEvent | None:
        """
        Process a zone crossing event. Returns a FootfallEvent if it's a
        countable customer crossing, or None if filtered.
        """
        if track.label == PersonLabel.EMPLOYEE or track.employee_probability >= 0.75:
            with self._lock:
                self._stats.employees_filtered += 1
            logger.debug("Filtered employee track %d at zone %s", track.track_id, crossing.zone_id)
            return None

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
            session_id = track.store_visit_session_id or f"{track.camera_id}:{track.track_id}"
            if event_type == "entry":
                if track.counted_entry or session_id in self._counted_session_entries:
                    return None
                track.counted_entry = True
                self._counted_session_entries.add(session_id)
                self._stats.total_entries += 1
                if track.group_id and track.group_id not in self._counted_group_entries:
                    self._counted_group_entries.add(track.group_id)
                    self._stats.shopping_party_entries += 1
                    self._stats.total_group_entries += 1
            elif event_type == "exit":
                if track.counted_exit or session_id in self._counted_session_exits:
                    return None
                track.counted_exit = True
                self._counted_session_exits.add(session_id)
                self._stats.total_exits += 1
                if track.group_id and track.group_id not in self._counted_group_exits:
                    self._counted_group_exits.add(track.group_id)
                    self._stats.total_group_exits += 1

            self._stats.current_in_store = max(
                0, self._stats.total_entries - self._stats.total_exits
            )
            self._stats.current_groups_in_store = max(
                0, self._stats.total_group_entries - self._stats.total_group_exits
            )
            snapshot = self._stats.to_dict()

        event = FootfallEvent(
            event_type=event_type,
            track_id=track.track_id,
            zone_id=crossing.zone_id,
            camera_id=track.camera_id,
            person_label=track.label.value,
            timestamp=timestamp,
            group_id=track.group_id,
            group_probability=track.group_probability,
            people_count=1,
            shopping_party_count=1 if event_type == "entry" and track.group_id else 0,
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
        self._counted_group_entries.clear()
        self._counted_group_exits.clear()
        self._counted_session_entries.clear()
        self._counted_session_exits.clear()
