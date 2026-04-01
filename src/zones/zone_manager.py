"""Zone manager — CRUD for zones + repeated session crossing checks."""

from __future__ import annotations

import logging
from typing import Any, Optional

from src.config import AppConfig, ZoneConfig
from src.tracking.track import Track
from src.zones.crossing_detector import CrossingResult, detect_crossing, point_in_polygon
from src.zones.zone import Zone, ZoneType

logger = logging.getLogger(__name__)


class ZoneManager:
    """Manages all zones across all cameras and checks crossings per frame."""

    def __init__(self):
        self._zones: dict[str, Zone] = {}
        self._track_zone_state: dict[tuple[int, str], bool] = {}
        self._dwell_started: set[tuple[int, str]] = set()

    def load_from_config(self, config: AppConfig) -> None:
        """Load zones from config (called at startup and on config change)."""
        self._zones.clear()
        self._track_zone_state.clear()
        self._dwell_started.clear()
        for cam in config.cameras:
            for z_cfg in cam.zones:
                self.add_zone_from_config(z_cfg, cam.id)

    def add_zone_from_config(self, z_cfg: ZoneConfig, camera_id: str) -> Zone:
        polygon = [(p[0], p[1]) for p in z_cfg.polygon]
        direction = (z_cfg.direction[0], z_cfg.direction[1]) if len(z_cfg.direction) >= 2 else (0.0, -1.0)

        zone = Zone(
            zone_id=z_cfg.id,
            camera_id=camera_id,
            polygon=polygon,
            zone_type=ZoneType(z_cfg.type),
            direction_vector=direction,
            name=z_cfg.name,
            promo_zone_flag=z_cfg.promo_zone_flag,
        )
        self._zones[zone.zone_id] = zone
        logger.info("Zone loaded: %s (%s) on camera %s", zone.zone_id, zone.zone_type, camera_id)
        return zone

    def add_zone(self, zone: Zone) -> None:
        self._zones[zone.zone_id] = zone

    def remove_zone(self, zone_id: str) -> bool:
        if zone_id in self._zones:
            del self._zones[zone_id]
            stale_keys = [key for key in self._track_zone_state if key[1] == zone_id]
            for key in stale_keys:
                self._track_zone_state.pop(key, None)
                self._dwell_started.discard(key)
            return True
        return False

    def get_zone(self, zone_id: str) -> Optional[Zone]:
        return self._zones.get(zone_id)

    def get_zones_for_camera(self, camera_id: str) -> list[Zone]:
        return [z for z in self._zones.values() if z.camera_id == camera_id]

    def all_zones(self) -> list[Zone]:
        return list(self._zones.values())

    def check_crossings(self, tracks: list[Track], camera_id: str) -> list[tuple[Track, dict[str, Any]]]:
        """Check all active tracks against all zones for this camera."""
        results: list[tuple[Track, dict[str, Any]]] = []
        zones = self.get_zones_for_camera(camera_id)

        if not zones:
            return results

        for track in tracks:
            prev = track.previous_centroid
            curr = track.current_centroid
            if curr is None:
                continue

            for zone in zones:
                state_key = (track.track_id, zone.zone_id)
                prev_state_known = state_key in self._track_zone_state
                prev_inside = self._track_zone_state.get(state_key)
                if prev_inside is None:
                    reference_point = prev if prev is not None else curr
                    prev_inside = point_in_polygon(reference_point, zone.polygon)
                curr_inside = point_in_polygon(curr, zone.polygon)

                self._track_zone_state[state_key] = curr_inside

                if not prev_state_known and curr_inside:
                    self._initialize_zone_presence(track, zone, state_key)
                    self._update_behavior_features(track)
                    continue

                if prev is None or prev_inside == curr_inside:
                    self._update_behavior_features(track)
                    continue

                crossing = detect_crossing(prev, curr, zone)
                if crossing is None:
                    crossing = CrossingResult(
                        zone_id=zone.zone_id,
                        direction="entering" if curr_inside else "exiting",
                    )

                timestamp = track.last_seen
                zone_visitors = self._count_zone_visitors(tracks, zone)
                if curr_inside:
                    zone_session_id = track.start_zone_session(zone.zone_id, timestamp)
                    self._dwell_started.add(state_key)
                    results.append((track, self._event_payload(
                        event_type="zone_entered",
                        zone=zone,
                        timestamp=timestamp,
                        direction=crossing.direction,
                        zone_session_id=zone_session_id,
                        zone_visitors=zone_visitors,
                    )))
                    results.append((track, self._event_payload(
                        event_type="dwell_started",
                        zone=zone,
                        timestamp=timestamp,
                        direction=crossing.direction,
                        zone_session_id=zone_session_id,
                        has_dwell_flag=True,
                        zone_visitors=zone_visitors,
                    )))
                else:
                    had_dwell = state_key in self._dwell_started
                    zone_session_id, dwell_seconds = track.end_zone_session(zone.zone_id, timestamp)
                    self._dwell_started.discard(state_key)
                    results.append((track, self._event_payload(
                        event_type="zone_exited",
                        zone=zone,
                        timestamp=timestamp,
                        direction=crossing.direction,
                        zone_session_id=zone_session_id,
                        dwell_seconds=dwell_seconds,
                        has_dwell_flag=dwell_seconds > 0.0,
                        zone_visitors=zone_visitors,
                    )))
                    if had_dwell and zone_session_id is not None:
                        results.append((track, self._event_payload(
                            event_type="dwell_ended",
                            zone=zone,
                            timestamp=timestamp,
                            direction=crossing.direction,
                            zone_session_id=zone_session_id,
                            dwell_seconds=dwell_seconds,
                            has_dwell_flag=dwell_seconds > 0.0,
                            zone_visitors=zone_visitors,
                        )))

                door_session_id = track.active_zone_session_id(zone.zone_id) if curr_inside else zone_session_id
                door_dwell_seconds = 0.0 if curr_inside else dwell_seconds
                results.append((track, self._event_payload(
                    event_type="door_crossed",
                    zone=zone,
                    timestamp=timestamp,
                    direction=crossing.direction,
                    zone_session_id=door_session_id,
                    dwell_seconds=door_dwell_seconds,
                    has_dwell_flag=door_dwell_seconds > 0.0,
                    zone_visitors=zone_visitors,
                )))
                self._update_behavior_features(track)
                logger.debug(
                    "Crossing: track %d → zone %s (%s) | entry_count=%d exit_count=%d",
                    track.track_id,
                    zone.zone_id,
                    crossing.direction,
                    track.entry_count,
                    track.exit_count,
                )

        return results

    def _initialize_zone_presence(
        self,
        track: Track,
        zone: Zone,
        state_key: tuple[int, str],
    ) -> None:
        if track.active_zone_session_id(zone.zone_id) is not None:
            return

        timestamp = track.last_seen
        track.start_zone_session(zone.zone_id, timestamp)
        self._dwell_started.add(state_key)
        logger.debug(
            "Initialized in-zone session: track %d already inside zone %s",
            track.track_id,
            zone.zone_id,
        )

    def _event_payload(
        self,
        event_type: str,
        zone: Zone,
        timestamp: float,
        direction: str | None,
        zone_session_id: str | None,
        zone_visitors: int,
        dwell_seconds: float = 0.0,
        has_dwell_flag: bool = False,
    ) -> dict[str, Any]:
        return {
            "event_type": event_type,
            "zone_id": zone.zone_id,
            "timestamp": timestamp,
            "direction": direction,
            "zone_session_id": zone_session_id,
            "dwell_seconds": dwell_seconds,
            "has_dwell_flag": has_dwell_flag,
            "zone_visitors": zone_visitors,
        }

    def _count_zone_visitors(self, tracks: list[Track], zone: Zone) -> int:
        count = 0
        for track in tracks:
            curr = track.current_centroid
            if curr is not None and point_in_polygon(curr, zone.polygon):
                count += 1
        return count

    def _update_behavior_features(self, track: Track) -> None:
        total_visits = max(1, sum(track.zone_visit_counts.values()))
        staff_zone_ids = {
            zone_id
            for zone_id, zone_obj in self._zones.items()
            if zone_obj.zone_type == ZoneType.STAFF_ONLY or "staff" in f"{zone_id} {zone_obj.name}".lower()
        }
        counter_zone_ids = {
            zone_id
            for zone_id, zone_obj in self._zones.items()
            if "counter" in f"{zone_id} {zone_obj.name}".lower() or "checkout" in f"{zone_id} {zone_obj.name}".lower()
        }
        staff_visits = float(sum(track.zone_visit_counts.get(zone_id, 0) for zone_id in staff_zone_ids))
        counter_visits = float(sum(track.zone_visit_counts.get(zone_id, 0) for zone_id in counter_zone_ids))
        session_duration = max(track.session_duration_seconds, 1.0)

        track.derived_features["staff_zone_hits"] = staff_visits
        track.derived_features["counter_zone_hits"] = counter_visits
        track.derived_features["staff_zone_visit_ratio"] = min(1.0, staff_visits / total_visits)
        revisit_visits = sum(max(0, count - 1) for count in track.zone_visit_counts.values())
        track.derived_features["reentry_pattern_score"] = min(1.0, revisit_visits / total_visits)

        completed_staff_dwell = sum(
            track.zone_dwell_seconds.get(zone_id, 0.0)
            for zone_id in staff_zone_ids
        )
        active_staff_dwell = sum(
            max(0.0, track.last_seen - entry_time)
            for zone_id, entry_time in track.zone_entry_times.items()
            if zone_id in staff_zone_ids
        )
        staff_dwell_seconds = completed_staff_dwell + active_staff_dwell
        track.derived_features["staff_zone_dwell_seconds"] = staff_dwell_seconds
        track.derived_features["staff_zone_dwell_ratio"] = min(1.0, staff_dwell_seconds / session_duration)

        completed_counter_dwell = sum(
            track.zone_dwell_seconds.get(zone_id, 0.0)
            for zone_id in counter_zone_ids
        )
        active_counter_dwell = sum(
            max(0.0, track.last_seen - entry_time)
            for zone_id, entry_time in track.zone_entry_times.items()
            if zone_id in counter_zone_ids
        )
        counter_presence_seconds = completed_counter_dwell + active_counter_dwell
        track.derived_features["counter_presence_ratio"] = min(1.0, counter_presence_seconds / session_duration)
        track.derived_features["active_staff_zone"] = 1.0 if any(
            zone_id in staff_zone_ids for zone_id in track.active_zone_session_ids
        ) else 0.0

    def on_config_change(self, config: AppConfig) -> None:
        self.load_from_config(config)
