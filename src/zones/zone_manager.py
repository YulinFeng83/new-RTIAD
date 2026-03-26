"""
Zone manager — CRUD for zones + per-frame crossing checks.
"""

from __future__ import annotations

import logging
from typing import Optional

from src.config import AppConfig, ZoneConfig
from src.tracking.track import Track
from src.zones.crossing_detector import CrossingResult, detect_crossing
from src.zones.zone import Zone, ZoneType

logger = logging.getLogger(__name__)


class ZoneManager:
    """Manages all zones across all cameras and checks crossings per frame."""

    def __init__(self):
        self._zones: dict[str, Zone] = {}  # zone_id → Zone
        self._crossed_tracks: dict[str, set[int]] = {}  # zone_id → set of track_ids that already crossed

    def load_from_config(self, config: AppConfig) -> None:
        """Load zones from config (called at startup and on config change)."""
        self._zones.clear()
        self._crossed_tracks.clear()
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
        )
        self._zones[zone.zone_id] = zone
        self._crossed_tracks[zone.zone_id] = set()
        logger.info("Zone loaded: %s (%s) on camera %s", zone.zone_id, zone.zone_type, camera_id)
        return zone

    def add_zone(self, zone: Zone) -> None:
        self._zones[zone.zone_id] = zone
        self._crossed_tracks[zone.zone_id] = set()

    def remove_zone(self, zone_id: str) -> bool:
        if zone_id in self._zones:
            del self._zones[zone_id]
            self._crossed_tracks.pop(zone_id, None)
            return True
        return False

    def get_zone(self, zone_id: str) -> Optional[Zone]:
        return self._zones.get(zone_id)

    def get_zones_for_camera(self, camera_id: str) -> list[Zone]:
        return [z for z in self._zones.values() if z.camera_id == camera_id]

    def all_zones(self) -> list[Zone]:
        return list(self._zones.values())

    def check_crossings(self, tracks: list[Track], camera_id: str) -> list[tuple[Track, CrossingResult]]:
        """
        Check all active tracks against all zones for this camera.

        Returns list of (track, crossing_result) for new crossings only.
        Each track can only cross each zone once (prevents double-counting).
        """
        results: list[tuple[Track, CrossingResult]] = []
        zones = self.get_zones_for_camera(camera_id)

        if not zones:
            return results

        for track in tracks:
            prev = track.previous_centroid
            curr = track.current_centroid
            if prev is None or curr is None:
                continue

            for zone in zones:
                if track.track_id in self._crossed_tracks.get(zone.zone_id, set()):
                    continue

                crossing = detect_crossing(prev, curr, zone)
                if crossing is not None:
                    self._crossed_tracks[zone.zone_id].add(track.track_id)
                    results.append((track, crossing))
                    logger.debug(
                        "Crossing: track %d → zone %s (%s)",
                        track.track_id,
                        zone.zone_id,
                        crossing.direction,
                    )

        return results

    def on_config_change(self, config: AppConfig) -> None:
        self.load_from_config(config)
