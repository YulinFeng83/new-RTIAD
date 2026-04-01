"""
Per-camera frame processing pipeline.

Chains: frame skip → detect + track → classify → zone crossing → footfall count →
        event publish → overlay render → output annotated frame.
"""

from __future__ import annotations

from datetime import datetime
import logging
import threading
import time
from typing import Any, Optional

import numpy as np

from src.camera.stream import VideoStream
from src.analytics.group_likelihood import GroupLikelihoodEngine
from src.config import AppConfig
from src.counting.footfall_counter import FootfallCounter
from src.events.types import BaseEvent, FootfallUpdate
from src.events.event_hub import EventHubProducer
from src.models.employee_classifier import EmployeeClassifier
from src.rendering.overlay import OverlayRenderer
from src.tracking.track import Track
from src.tracking.tracker import PersonTracker
from src.zones.crossing_detector import CrossingResult
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
        self._group_engine = GroupLikelihoodEngine()

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

        self._update_track_behavior_context(active_tracks, ts, frame_id)

        context: dict[str, Any] = {
            "current_time": ts,
            "frame_id": frame_id,
            "pre_open_entry_flag": self._pre_open_entry_flag(ts),
            "first_n_entries_flag": 1.0 if frame_id < 300 else 0.0,
            "classification_events": [],
        }
        self._classifier.classify_tracks(active_tracks, frame, frame_id, context)

        self._apply_group_assignments(active_tracks)

        for payload in context["classification_events"]:
            track = next((candidate for candidate in active_tracks if candidate.track_id == payload["track_id"]), None)
            if track is None:
                continue
            self._event_hub.send(BaseEvent(
                event_type="classification_updated",
                tenant_id=self._config.store.tenant_id,
                store_id=self._config.store.store_id,
                camera_id=self.camera_id,
                timestamp=ts,
                track_id=track.track_id,
                group_id=track.group_id,
                classification_label=payload["classification_label"],
                employee_probability=payload["employee_probability"],
                customer_probability=payload["customer_probability"],
                unknown_probability=payload["unknown_probability"],
                group_probability=track.group_probability,
                window_start=self._window_start(ts),
                window_end=self._window_end(ts),
            ))

        for track, event_data in self._zone_manager.check_crossings(active_tracks, self.camera_id):
            event_timestamp = float(event_data.get("timestamp", ts))
            zone_id = str(event_data["zone_id"])
            zone = self._zone_manager.get_zone(zone_id)
            if zone is None:
                continue

            dwell_seconds = float(event_data.get("dwell_seconds", 0.0))
            base_event = BaseEvent(
                event_type=str(event_data["event_type"]),
                tenant_id=self._config.store.tenant_id,
                store_id=self._config.store.store_id,
                camera_id=self.camera_id,
                timestamp=event_timestamp,
                track_id=track.track_id,
                group_id=track.group_id,
                zone_id=zone_id,
                direction=event_data.get("direction"),
                classification_label=track.label.value,
                employee_probability=track.employee_probability,
                customer_probability=track.customer_probability,
                unknown_probability=track.unknown_probability,
                group_probability=track.group_probability,
                dwell_seconds=dwell_seconds,
                zone_session_id=event_data.get("zone_session_id"),
                has_dwell_flag=bool(event_data.get("has_dwell_flag", dwell_seconds > 0.0)),
                window_start=self._window_start(event_timestamp),
                window_end=self._window_end(event_timestamp),
                group_visitor_count=self._group_visitor_count(track, active_tracks),
                zone_visitors=int(event_data.get("zone_visitors", 0)),
                max_dwell_bucket=self._dwell_bucket(dwell_seconds),
                promo_zone_flag=zone_id in self._config.store.promo_zone_ids,
            )
            self._event_hub.send(base_event)

            if base_event.event_type == "door_crossed":
                crossing = CrossingResult(zone_id=zone_id, direction=base_event.direction or "entering")
                ff_event = self._footfall.process_crossing(
                    track,
                    crossing,
                    zone,
                    event_timestamp,
                    zone_session_id=base_event.zone_session_id,
                )
                if ff_event:
                    self._event_hub.send(FootfallUpdate(
                        event_type="footfall_updated",
                        tenant_id=self._config.store.tenant_id,
                        store_id=self._config.store.store_id,
                        camera_id=self.camera_id,
                        total_entries=ff_event.stats_snapshot.get("total_entries", 0),
                        total_exits=ff_event.stats_snapshot.get("total_exits", 0),
                        current_in_store=ff_event.stats_snapshot.get("current_in_store", 0),
                        employees_filtered=ff_event.stats_snapshot.get("employees_filtered", 0),
                        shopping_party_entries=ff_event.stats_snapshot.get("shopping_party_entries", 0),
                        timestamp=event_timestamp,
                    ))

        zones = self._zone_manager.get_zones_for_camera(self.camera_id)
        stats = self._footfall.stats
        annotated = self._overlay.render(frame, active_tracks, zones, stats)

        return annotated

    def on_config_change(self, config: AppConfig) -> None:
        self._config = config

    def _update_track_behavior_context(self, tracks: list[Track], timestamp: float, frame_id: int) -> None:
        pre_open_flag = self._pre_open_entry_flag(timestamp)
        first_n_entries_flag = 1.0 if frame_id < 300 else 0.0
        for track in tracks:
            track.derived_features["pre_open_entry_flag"] = pre_open_flag
            track.derived_features["first_n_entries_flag"] = first_n_entries_flag

    def _pre_open_entry_flag(self, timestamp: float) -> float:
        now = datetime.fromtimestamp(timestamp)
        open_hour, open_minute = [int(part) for part in self._config.store.open_time.split(":", 1)]
        open_minutes = open_hour * 60 + open_minute
        now_minutes = now.hour * 60 + now.minute
        window_start = open_minutes - 60
        return 1.0 if window_start <= now_minutes < open_minutes else 0.0

    def _apply_group_assignments(self, tracks: list[Track]) -> None:
        assignments = self._group_engine.assign_groups(tracks)
        for track in tracks:
            assignment = assignments.get(track.track_id)
            if assignment is None:
                track.group_id = None
                track.group_probability = 0.0
                continue
            track.group_id = assignment["group_id"]
            track.group_probability = assignment["group_probability"]
            if assignment["signals"]:
                track.derived_features["group_signals"] = assignment["signals"]

    def _window_start(self, timestamp: float) -> float:
        return timestamp - (timestamp % 300)

    def _window_end(self, timestamp: float) -> float:
        return self._window_start(timestamp) + 300.0

    def _group_visitor_count(self, track: Track, tracks: list[Track]) -> int:
        if not track.group_id:
            return 1
        return sum(1 for candidate in tracks if candidate.group_id == track.group_id)

    def _dwell_bucket(self, dwell_seconds: float) -> str | None:
        if dwell_seconds <= 0:
            return None
        if dwell_seconds < 30:
            return "<30s"
        if dwell_seconds < 60:
            return "30–60s"
        if dwell_seconds < 120:
            return "60–120s"
        return ">120s"
