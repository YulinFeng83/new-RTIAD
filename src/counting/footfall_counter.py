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
    store_id: str
    person_label: str
    timestamp: float
    direction: str
    group_id: str | None = None
    group_probability: float = 0.0
    zone_session_id: str | None = None
    entry_delta: int = 0
    exit_delta: int = 0
    people_count: int = 1
    shopping_party_count: int = 1
    stats_snapshot: dict = field(default_factory=dict)


class FootfallCounter:
    """Counts customer entries/exits and maintains in-store occupancy."""

    def __init__(self):
        self._lock = threading.Lock()
        self._events: list[FootfallEvent] = []
        self._stats_by_store: dict[str, FootfallStats] = {}
        self._counted_group_entries_by_store: dict[str, set[str]] = {}
        self._counted_group_exits_by_store: dict[str, set[str]] = {}
        self._counted_session_entries_by_store: dict[str, set[str]] = {}
        self._counted_session_exits_by_store: dict[str, set[str]] = {}

    @property
    def stats(self) -> FootfallStats:
        with self._lock:
            return self._aggregate_stats_locked()

    def stats_for_store(self, store_id: str) -> FootfallStats:
        with self._lock:
            return self._copy_stats(self._get_store_stats_locked(store_id))

    def process_crossing(
        self,
        store_id: str,
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
                stats = self._get_store_stats_locked(store_id)
                stats.employees_filtered += 1
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
            stats = self._get_store_stats_locked(store_id)
            counted_group_entries = self._get_store_set_locked(
                self._counted_group_entries_by_store, store_id
            )
            counted_group_exits = self._get_store_set_locked(
                self._counted_group_exits_by_store, store_id
            )
            counted_session_entries = self._get_store_set_locked(
                self._counted_session_entries_by_store, store_id
            )
            counted_session_exits = self._get_store_set_locked(
                self._counted_session_exits_by_store, store_id
            )
            session_id = track.store_visit_session_id or f"{track.camera_id}:{track.track_id}"
            if event_type == "entry":
                if track.counted_entry or session_id in counted_session_entries:
                    return None
                track.counted_entry = True
                counted_session_entries.add(session_id)
                stats.total_entries += 1
                if track.group_id and track.group_id not in counted_group_entries:
                    counted_group_entries.add(track.group_id)
                    stats.shopping_party_entries += 1
                    stats.total_group_entries += 1
            elif event_type == "exit":
                if track.counted_exit or session_id in counted_session_exits:
                    return None
                track.counted_exit = True
                counted_session_exits.add(session_id)
                stats.total_exits += 1
                if track.group_id and track.group_id not in counted_group_exits:
                    counted_group_exits.add(track.group_id)
                    stats.total_group_exits += 1

            stats.current_in_store = max(
                0, stats.total_entries - stats.total_exits
            )
            stats.current_groups_in_store = max(
                0, stats.total_group_entries - stats.total_group_exits
            )
            snapshot = stats.to_dict()

        event = FootfallEvent(
            event_type=event_type,
            track_id=track.track_id,
            zone_id=crossing.zone_id,
            camera_id=track.camera_id,
            store_id=store_id,
            person_label=track.label.value,
            timestamp=timestamp,
            direction=crossing.direction,
            group_id=track.group_id,
            group_probability=track.group_probability,
            zone_session_id=zone_session_id,
            entry_delta=1 if event_type == "entry" else 0,
            exit_delta=1 if event_type == "exit" else 0,
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
            self._stats_by_store = {}
        self._events.clear()
        self._counted_group_entries_by_store.clear()
        self._counted_group_exits_by_store.clear()
        self._counted_session_entries_by_store.clear()
        self._counted_session_exits_by_store.clear()

    def _aggregate_stats_locked(self) -> FootfallStats:
        aggregated = FootfallStats()
        for stats in self._stats_by_store.values():
            aggregated.total_entries += stats.total_entries
            aggregated.total_exits += stats.total_exits
            aggregated.current_in_store += stats.current_in_store
            aggregated.employees_filtered += stats.employees_filtered
            aggregated.shopping_party_entries += stats.shopping_party_entries
            aggregated.total_group_entries += stats.total_group_entries
            aggregated.total_group_exits += stats.total_group_exits
            aggregated.current_groups_in_store += stats.current_groups_in_store
        return aggregated

    def _copy_stats(self, stats: FootfallStats) -> FootfallStats:
        return FootfallStats(
            total_entries=stats.total_entries,
            total_exits=stats.total_exits,
            current_in_store=stats.current_in_store,
            employees_filtered=stats.employees_filtered,
            shopping_party_entries=stats.shopping_party_entries,
            total_group_entries=stats.total_group_entries,
            total_group_exits=stats.total_group_exits,
            current_groups_in_store=stats.current_groups_in_store,
        )

    def _get_store_stats_locked(self, store_id: str) -> FootfallStats:
        stats = self._stats_by_store.get(store_id)
        if stats is None:
            stats = FootfallStats()
            self._stats_by_store[store_id] = stats
        return stats

    def _get_store_set_locked(self, store_map: dict[str, set[str]], store_id: str) -> set[str]:
        value = store_map.get(store_id)
        if value is None:
            value = set()
            store_map[store_id] = value
        return value
