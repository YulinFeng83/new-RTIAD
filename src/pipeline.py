"""
Per-camera frame processing pipeline.

Chains: frame skip → detect + track → classify → zone crossing → footfall count →
        event publish → overlay render → output annotated frame.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional

import numpy as np

from src.camera.stream import VideoStream
from src.config import AppConfig
from src.counting.footfall_counter import FootfallCounter
from src.events.event_hub import EventHubProducer
from src.events.types import CrossingEvent, FootfallUpdate
from src.models.employee_classifier import EmployeeClassifier
from src.rendering.overlay import OverlayRenderer
from src.tracking.track import Track
from src.tracking.tracker import PersonTracker
from src.zones.zone_manager import ZoneManager

logger = logging.getLogger(__name__)


class CameraPipeline:
    """
    Processes frames from a single camera through the full vision pipeline.

    Runs in its own thread. The latest annotated frame is always available
    via `get_annotated_frame()` for the MJPEG feed.
    """

    def __init__(
        self,
        camera_id: str,
        stream: VideoStream,
        tracker: PersonTracker,
        classifier: EmployeeClassifier,
        zone_manager: ZoneManager,
        footfall_counter: FootfallCounter,
        overlay_renderer: OverlayRenderer,
        event_hub: EventHubProducer,
        config: AppConfig,
    ):
        self.camera_id = camera_id
        self._stream = stream
        self._tracker = tracker
        self._classifier = classifier
        self._zone_manager = zone_manager
        self._footfall = footfall_counter
        self._overlay = overlay_renderer
        self._event_hub = event_hub
        self._config = config

        self._annotated_frame: Optional[np.ndarray] = None
        self._frame_lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._processed_count = 0

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("[%s] Pipeline started", self.camera_id)

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("[%s] Pipeline stopped", self.camera_id)

    def get_annotated_frame(self) -> Optional[np.ndarray]:
        with self._frame_lock:
            return self._annotated_frame.copy() if self._annotated_frame is not None else None

    def _run_loop(self) -> None:
        frame_skip = self._config.system.frame_skip
        frame_counter = 0

        while self._running:
            ok, frame, frame_id = self._stream.read()
            if not ok or frame is None:
                time.sleep(0.01)
                continue

            frame_counter += 1
            if frame_counter % frame_skip != 0:
                continue

            self._processed_count += 1

            try:
                annotated = self._process_frame(frame, frame_id)
                with self._frame_lock:
                    self._annotated_frame = annotated
            except Exception:
                logger.exception("[%s] Error processing frame %d", self.camera_id, frame_id)

    def _process_frame(self, frame: np.ndarray, frame_id: int) -> np.ndarray:
        ts = time.time()

        active_tracks = self._tracker.update(frame, frame_id)

        context: dict[str, Any] = {
            "current_time": ts,
            "frame_id": frame_id,
        }
        self._classifier.classify_tracks(active_tracks, frame, frame_id, context)

        crossings = self._zone_manager.check_crossings(active_tracks, self.camera_id)

        for track, crossing in crossings:
            zone = self._zone_manager.get_zone(crossing.zone_id)
            if zone is None:
                continue

            crossing_event = CrossingEvent(
                track_id=track.track_id,
                zone_id=crossing.zone_id,
                camera_id=self.camera_id,
                direction=crossing.direction,
                person_label=track.label.value,
                timestamp=ts,
                centroid=track.current_centroid or (0, 0),
            )
            self._event_hub.send(crossing_event.__dict__)

            ff_event = self._footfall.process_crossing(track, crossing, zone, ts)
            if ff_event:
                update = FootfallUpdate(
                    event_type=ff_event.event_type,
                    track_id=ff_event.track_id,
                    zone_id=ff_event.zone_id,
                    camera_id=self.camera_id,
                    total_entries=ff_event.stats_snapshot.get("total_entries", 0),
                    total_exits=ff_event.stats_snapshot.get("total_exits", 0),
                    current_in_store=ff_event.stats_snapshot.get("current_in_store", 0),
                    employees_filtered=ff_event.stats_snapshot.get("employees_filtered", 0),
                    timestamp=ts,
                )
                self._event_hub.send(update.__dict__)

        zones = self._zone_manager.get_zones_for_camera(self.camera_id)
        stats = self._footfall.stats
        annotated = self._overlay.render(frame, active_tracks, zones, stats)

        return annotated

    def on_config_change(self, config: AppConfig) -> None:
        self._config = config
