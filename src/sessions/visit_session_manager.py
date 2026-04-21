from __future__ import annotations

import hashlib
import logging
import threading
import time
from dataclasses import dataclass, field

from src.events.typed_events import DoorCrossedEvent, SessionCompletedEvent, format_event_time
from src.tracking.track import Track
from src.zones.zone import Zone, ZoneType

logger = logging.getLogger(__name__)

TrackKey = tuple[str, int]


@dataclass
class VisitSegment:
    camera_id: str
    track_id: int
    started_at: float
    last_seen_at: float
    ended_at: float | None = None


@dataclass
class VisitSession:
    store_visit_id: str
    store_id: str
    opened_at: float
    last_activity_at: float
    classification_label: str
    track_id: str
    max_employee_probability: float = 0.0
    last_group_id: str | None = None
    group_visitor_count: int = 1
    group_was_active_at_exit: bool = False
    session_entry_count: int = 0
    session_exit_count: int = 0
    total_dwell_seconds: float = 0.0
    segment_count: int = 1
    segments: list[VisitSegment] = field(default_factory=list)
    active_track_keys: set[TrackKey] = field(default_factory=set)
    pending_close_at: float | None = None
    pending_close_reason: str | None = None
    closed_at: float | None = None
    close_reason: str | None = None
    completion_emitted: bool = False


class VisitSessionManager:
    """Owns MOVA store visit identity and session aggregates.

    Current implementation links a visit to camera-local tracks after a valid
    customer door entry. The segment APIs are intentionally shaped for later
    cross-camera stitching, where another camera-local track can be attached to
    an existing store_visit_id and increment segment_count.
    """

    def __init__(self, exit_confirmation_cooldown_seconds: float):
        self._exit_confirmation_cooldown_seconds = exit_confirmation_cooldown_seconds
        self._visits: dict[str, VisitSession] = {}
        self._active_visit_by_track: dict[TrackKey, str] = {}
        self._lock = threading.RLock()

    def on_config_change(self, exit_confirmation_cooldown_seconds: float) -> None:
        with self._lock:
            self._exit_confirmation_cooldown_seconds = exit_confirmation_cooldown_seconds

    def active_visit_for_track(self, camera_id: str, track_id: int) -> VisitSession | None:
        with self._lock:
            visit_id = self._active_visit_by_track.get((camera_id, track_id))
            if visit_id is None:
                return None
            visit = self._visits.get(visit_id)
            if visit is None or visit.closed_at is not None:
                return None
            return visit

    def refresh_track(
        self,
        store_id: str,
        camera_id: str,
        track: Track,
        timestamp: float,
        group_visitor_count: int,
    ) -> None:
        with self._lock:
            visit = self.active_visit_for_track(camera_id, track.track_id)
            if visit is None:
                return
            self._refresh_visit_snapshot(visit, track, timestamp, group_visitor_count)
            self._refresh_segment(visit, camera_id, track.track_id, timestamp)
            if visit.store_id != store_id:
                logger.warning(
                    "Visit %s store mismatch: expected %s, saw %s",
                    visit.store_visit_id,
                    visit.store_id,
                    store_id,
                )

    def record_door_crossing(
        self,
        store_id: str,
        camera_id: str,
        track: Track,
        zone: Zone,
        direction: str,
        crossed_at: float,
        group_visitor_count: int,
    ) -> DoorCrossedEvent | None:
        with self._lock:
            door_event_type = self._door_event_type(zone, direction)
            if door_event_type is None:
                return None

            visit = self.active_visit_for_track(camera_id, track.track_id)
            if door_event_type == "entry":
                if visit is None:
                    visit = self._open_visit(store_id, camera_id, track, crossed_at, group_visitor_count)
                else:
                    visit.pending_close_at = None
                    visit.pending_close_reason = None
                    self._refresh_visit_snapshot(visit, track, crossed_at, group_visitor_count)
                visit.session_entry_count += 1
            elif door_event_type == "exit":
                if visit is None:
                    logger.info(
                        "[%s] Skipping typed door_crossed exit for track %d: no active store visit",
                        camera_id,
                        track.track_id,
                    )
                    return None
                self._refresh_visit_snapshot(visit, track, crossed_at, group_visitor_count)
                visit.session_exit_count += 1
                visit.group_was_active_at_exit = visit.last_group_id is not None
                visit.pending_close_at = crossed_at + self._exit_confirmation_cooldown_seconds
                visit.pending_close_reason = "exit"

            crossing_id = self._make_id(
                "crossing",
                store_id,
                camera_id,
                str(track.track_id),
                visit.store_visit_id,
                direction,
                f"{crossed_at:.6f}",
            )
            return DoorCrossedEvent(
                crossing_id=crossing_id,
                store_id=store_id,
                camera_id=camera_id,
                store_visit_id=visit.store_visit_id,
                direction=direction,
                crossed_at=format_event_time(crossed_at),
                classification_label=track.label.value,
                max_employee_probability=track.max_employee_probability,
                edge_emitted_at=format_event_time(time.time()),
            )

    def record_zone_exit(self, camera_id: str, track: Track, dwell_seconds: float) -> VisitSession | None:
        with self._lock:
            visit = self.active_visit_for_track(camera_id, track.track_id)
            if visit is None:
                return None
            visit.total_dwell_seconds += dwell_seconds
            return visit

    def close_due_visits(
        self,
        camera_id: str,
        tracks: dict[int, Track],
        timestamp: float,
        inactivity_timeout_seconds: float,
    ) -> list[tuple[VisitSession, Track | None]]:
        with self._lock:
            closed: list[tuple[VisitSession, Track | None]] = []

            for visit in list(self._visits.values()):
                if visit.closed_at is not None or visit.completion_emitted:
                    continue

                representative_track = self._representative_track_for_camera(visit, camera_id, tracks)
                if visit.pending_close_at is not None and timestamp >= visit.pending_close_at:
                    closed.append((self._close_visit(visit, visit.pending_close_at, "exit"), representative_track))
                    continue

                active_keys_for_camera = [
                    key for key in visit.active_track_keys
                    if key[0] == camera_id
                ]
                for _, track_id in active_keys_for_camera:
                    track = tracks.get(track_id)
                    if track is None or track.is_active:
                        continue
                    if timestamp - track.last_seen >= inactivity_timeout_seconds:
                        closed_at = track.last_seen + inactivity_timeout_seconds
                        closed.append((self._close_visit(visit, closed_at, "timeout"), track))
                        break

            return closed

    def to_session_completed_event(self, visit: VisitSession) -> SessionCompletedEvent:
        with self._lock:
            closed_at = visit.closed_at or visit.last_activity_at
            close_reason = visit.close_reason or "timeout"
            return SessionCompletedEvent(
                store_visit_id=visit.store_visit_id,
                store_id=visit.store_id,
                track_id=visit.track_id,
                classification_label=visit.classification_label,
                max_employee_probability=visit.max_employee_probability,
                last_group_id=visit.last_group_id,
                group_visitor_count=visit.group_visitor_count,
                group_was_active_at_exit=visit.group_was_active_at_exit,
                segment_count=visit.segment_count,
                close_reason=close_reason,
                session_duration_seconds=max(0.0, closed_at - visit.opened_at),
                total_dwell_seconds=visit.total_dwell_seconds,
                session_entry_count=visit.session_entry_count,
                session_exit_count=visit.session_exit_count,
                session_completed_at=format_event_time(closed_at),
                edge_emitted_at=format_event_time(time.time()),
            )

    def mark_completion_emitted(self, visit: VisitSession) -> None:
        with self._lock:
            visit.completion_emitted = True
            for key in list(visit.active_track_keys):
                self._active_visit_by_track.pop(key, None)
            for segment in visit.segments:
                if segment.ended_at is None:
                    segment.ended_at = visit.closed_at

    def link_segment(
        self,
        store_visit_id: str,
        camera_id: str,
        track: Track,
        timestamp: float,
        group_visitor_count: int = 1,
    ) -> VisitSession | None:
        with self._lock:
            visit = self._visits.get(store_visit_id)
            if visit is None or visit.closed_at is not None:
                return None
            key = (camera_id, track.track_id)
            if key not in visit.active_track_keys:
                visit.active_track_keys.add(key)
                self._active_visit_by_track[key] = store_visit_id
                visit.segments.append(VisitSegment(camera_id, track.track_id, timestamp, timestamp))
                visit.segment_count = len(visit.segments)
            track.store_visit_session_id = visit.store_visit_id
            self._refresh_visit_snapshot(visit, track, timestamp, group_visitor_count)
            return visit

    def _open_visit(
        self,
        store_id: str,
        camera_id: str,
        track: Track,
        opened_at: float,
        group_visitor_count: int,
    ) -> VisitSession:
        store_visit_id = self._make_id(
            "visit",
            store_id,
            camera_id,
            str(track.track_id),
            f"{opened_at:.6f}",
        )
        visit = VisitSession(
            store_visit_id=store_visit_id,
            store_id=store_id,
            opened_at=opened_at,
            last_activity_at=opened_at,
            classification_label=track.label.value,
            track_id=str(track.track_id),
            max_employee_probability=track.max_employee_probability,
            last_group_id=track.group_id,
            group_visitor_count=max(1, group_visitor_count),
            segment_count=1,
            segments=[VisitSegment(camera_id, track.track_id, opened_at, opened_at)],
            active_track_keys={(camera_id, track.track_id)},
        )
        self._visits[store_visit_id] = visit
        self._active_visit_by_track[(camera_id, track.track_id)] = store_visit_id
        track.store_visit_session_id = store_visit_id
        return visit

    def _close_visit(self, visit: VisitSession, closed_at: float, close_reason: str) -> VisitSession:
        visit.closed_at = closed_at
        visit.close_reason = close_reason
        visit.pending_close_at = None
        visit.pending_close_reason = None
        for segment in visit.segments:
            if segment.ended_at is None:
                segment.ended_at = closed_at
        return visit

    def _refresh_visit_snapshot(
        self,
        visit: VisitSession,
        track: Track,
        timestamp: float,
        group_visitor_count: int,
    ) -> None:
        visit.last_activity_at = max(visit.last_activity_at, timestamp)
        visit.classification_label = track.label.value
        visit.max_employee_probability = max(visit.max_employee_probability, track.max_employee_probability)
        visit.last_group_id = track.group_id
        visit.group_visitor_count = max(1, group_visitor_count)

    def _refresh_segment(
        self,
        visit: VisitSession,
        camera_id: str,
        track_id: int,
        timestamp: float,
    ) -> None:
        for segment in visit.segments:
            if segment.camera_id == camera_id and segment.track_id == track_id and segment.ended_at is None:
                segment.last_seen_at = max(segment.last_seen_at, timestamp)
                return

    def _representative_track_for_camera(
        self,
        visit: VisitSession,
        camera_id: str,
        tracks: dict[int, Track],
    ) -> Track | None:
        for key_camera_id, track_id in visit.active_track_keys:
            if key_camera_id != camera_id:
                continue
            track = tracks.get(track_id)
            if track is not None:
                return track
        return None

    def _door_event_type(self, zone: Zone, direction: str) -> str | None:
        if direction == "entering" and zone.is_entry:
            return "entry"
        if direction == "exiting" and zone.is_exit:
            return "exit"
        if direction == "exiting" and zone.zone_type == ZoneType.ENTRY:
            return "exit"
        if direction == "entering" and zone.zone_type == ZoneType.EXIT:
            return "entry"
        return None

    def _make_id(self, prefix: str, *parts: str) -> str:
        raw = "|".join(parts)
        digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()
        return f"{prefix}-{digest[:20]}"
