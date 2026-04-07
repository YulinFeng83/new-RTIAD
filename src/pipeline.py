"""
Per-camera frame processing pipeline.

Chains: frame skip → detect + track → classify → zone crossing → footfall count →
        event publish → overlay render → output annotated frame.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import hashlib
import logging
import threading
import time
from typing import Any, Optional

import numpy as np
import cv2

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
        self._group_engine = GroupLikelihoodEngine(
            threshold=0.5,
            group_rejoin_grace_seconds=config.tracking.group_rejoin_grace_seconds,
        )
        self._exit_confirmation_cooldown_seconds = float(config.tracking.exit_confirmation_cooldown_seconds)
        self._track_lost_timeout_seconds = float(config.tracking.track_lost_timeout_seconds)

        self._annotated_frame: Optional[np.ndarray] = None
        self._frame_lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._processed_count = 0
        self._video_writer: Optional[cv2.VideoWriter] = None
        self._clip_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix=f"clip-{camera_id}",
        )

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
            self._thread.join(timeout=10)
            self._thread = None
        self._clip_executor.shutdown(wait=True, cancel_futures=True)
        if self._video_writer is not None:
            self._video_writer.release()
            self._video_writer = None
            logger.info("[%s] Video output saved", self.camera_id)
        logger.info("[%s] Pipeline stopped", self.camera_id)

    def get_annotated_frame(self) -> Optional[np.ndarray]:
        with self._frame_lock:
            return self._annotated_frame.copy() if self._annotated_frame is not None else None

    def _run_loop(self) -> None:
        frame_skip = self._config.system.frame_skip
        frame_counter = 0
        write_counter = 0
        fps = self._config.system.fps_target
        max_seconds = self._config.system.max_duration_seconds
        max_frames = max_seconds * fps if max_seconds > 0 else 0
        last_tracks: list[Track] = []
        last_zones: list = []
        last_stats = self._footfall.stats

        while self._running:
            if max_frames > 0 and frame_counter >= max_frames:
                logger.info(
                    "[%s] Reached %ds limit (%d frames), finishing pipeline",
                    self.camera_id, max_seconds, frame_counter,
                )
                break

            ok, frame, frame_id = self._stream.read_queued()
            if not ok or frame is None:
                if not self._stream.is_running:
                    logger.info("[%s] Stream ended, finishing pipeline", self.camera_id)
                    break
                continue

            frame_counter += 1
            should_process = (frame_counter % frame_skip == 0)

            if should_process:
                self._processed_count += 1
                try:
                    annotated = self._process_frame(frame, frame_id)
                    last_tracks = self._tracker.active_tracks()
                    last_zones = self._zone_manager.get_zones_for_camera(self.camera_id)
                    last_stats = self._footfall.stats
                except Exception:
                    logger.exception("[%s] Error processing frame %d", self.camera_id, frame_id)
                    annotated = frame
            else:
                annotated = self._overlay.render(frame, last_tracks, last_zones, last_stats)

            with self._frame_lock:
                self._annotated_frame = annotated
            self._write_frame(annotated)
            write_counter += 1

        if self._video_writer is not None:
            self._video_writer.release()
            self._video_writer = None
            logger.info("[%s] Video output saved (%d written, %d processed)", self.camera_id, write_counter, self._processed_count)

    def _write_frame(self, frame: np.ndarray) -> None:
        if self._video_writer is None:
            from pathlib import Path
            out_dir = Path("outputs")
            out_dir.mkdir(exist_ok=True)
            h, w = frame.shape[:2]
            out_path = out_dir / f"{self.camera_id}_output.mp4"
            fps = self._config.system.fps_target
            self._video_writer = cv2.VideoWriter(
                str(out_path),
                cv2.VideoWriter_fourcc(*"mp4v"),
                fps,
                (w, h),
            )
            logger.info("[%s] Recording to %s (%dx%d @ %d fps)", self.camera_id, out_path, w, h, fps)
        self._video_writer.write(frame)

    def _process_frame(self, frame: np.ndarray, frame_id: int) -> np.ndarray:
        ts = time.time()

        active_tracks = self._tracker.update(frame, frame_id)
        self._update_track_behavior_context(active_tracks, ts, frame_id)

        # Fire-and-forget CLIP classification in background thread
        context: dict[str, Any] = {
            "current_time": ts,
            "frame_id": frame_id,
            "pre_open_entry_flag": self._pre_open_entry_flag(ts),
            "first_n_entries_flag": 1.0 if frame_id < 300 else 0.0,
            "classification_events": [],
        }
        self._clip_executor.submit(
            self._classify_and_publish, list(active_tracks), frame.copy(), frame_id, context, ts,
        )

        self._apply_group_assignments(active_tracks, ts)

        for track, event_data in self._zone_manager.check_crossings(active_tracks, self.camera_id):
            event_timestamp = float(event_data.get("timestamp", ts))
            zone_id = str(event_data["zone_id"])
            zone = self._zone_manager.get_zone(zone_id)
            if zone is None:
                continue

            dwell_seconds = float(event_data.get("dwell_seconds", 0.0))
            base_event = BaseEvent(
                event_id=self._make_event_id(
                    event_type=str(event_data["event_type"]),
                    track=track,
                    timestamp=event_timestamp,
                    zone_session_id=event_data.get("zone_session_id"),
                    zone_id=zone_id,
                ),
                event_type=str(event_data["event_type"]),
                tenant_id=self._config.store.tenant_id,
                store_id=self._config.store.store_id,
                camera_id=self.camera_id,
                timestamp=event_timestamp,
                track_id=track.track_id,
                store_visit_session_id=track.store_visit_session_id,
                previous_group_id=track.previous_group_id,
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
                    if ff_event.event_type == "exit":
                        track.mark_pending_exit(event_timestamp, self._exit_confirmation_cooldown_seconds)
                    elif ff_event.event_type == "entry":
                        track.clear_pending_exit()
                    self._event_hub.send(FootfallUpdate(
                        event_id=self._make_event_id(
                            event_type="footfall_updated",
                            track=track,
                            timestamp=event_timestamp,
                            zone_session_id=base_event.zone_session_id,
                            zone_id=zone_id,
                        ),
                        event_type="footfall_updated",
                        tenant_id=self._config.store.tenant_id,
                        store_id=self._config.store.store_id,
                        camera_id=self.camera_id,
                        track_id=track.track_id,
                        store_visit_session_id=track.store_visit_session_id,
                        previous_group_id=track.previous_group_id,
                        group_id=track.group_id,
                        group_probability=track.group_probability,
                        total_entries=ff_event.stats_snapshot.get("total_entries", 0),
                        total_exits=ff_event.stats_snapshot.get("total_exits", 0),
                        current_in_store=ff_event.stats_snapshot.get("current_in_store", 0),
                        employees_filtered=ff_event.stats_snapshot.get("employees_filtered", 0),
                        shopping_party_entries=ff_event.stats_snapshot.get("shopping_party_entries", 0),
                        timestamp=event_timestamp,
                    ))

        self._emit_completed_sessions(ts)

        zones = self._zone_manager.get_zones_for_camera(self.camera_id)
        stats = self._footfall.stats
        return self._overlay.render(frame, active_tracks, zones, stats)

    def _classify_and_publish(
        self,
        tracks: list[Track],
        frame: np.ndarray,
        frame_id: int,
        context: dict[str, Any],
        ts: float,
    ) -> None:
        """Run CLIP classification in a background thread."""
        try:
            self._classifier.classify_tracks(tracks, frame, frame_id, context)
            for payload in context["classification_events"]:
                track = next((t for t in tracks if t.track_id == payload["track_id"]), None)
                if track is None:
                    continue
                self._event_hub.send(BaseEvent(
                    event_id=self._make_event_id(
                        event_type="classification_updated",
                        track=track,
                        timestamp=ts,
                    ),
                    event_type="classification_updated",
                    tenant_id=self._config.store.tenant_id,
                    store_id=self._config.store.store_id,
                    camera_id=self.camera_id,
                    timestamp=ts,
                    track_id=track.track_id,
                    store_visit_session_id=track.store_visit_session_id,
                    previous_group_id=track.previous_group_id,
                    group_id=track.group_id,
                    classification_label=payload["classification_label"],
                    employee_probability=payload["employee_probability"],
                    customer_probability=payload["customer_probability"],
                    unknown_probability=payload["unknown_probability"],
                    group_probability=track.group_probability,
                    window_start=self._window_start(ts),
                    window_end=self._window_end(ts),
                ))
        except Exception:
            logger.exception("[%s] Background classification error", self.camera_id)

    def on_config_change(self, config: AppConfig) -> None:
        self._config = config
        self._group_engine = GroupLikelihoodEngine(
            threshold=0.5,
            group_rejoin_grace_seconds=config.tracking.group_rejoin_grace_seconds,
        )
        self._exit_confirmation_cooldown_seconds = float(config.tracking.exit_confirmation_cooldown_seconds)
        self._track_lost_timeout_seconds = float(config.tracking.track_lost_timeout_seconds)

    def _update_track_behavior_context(self, tracks: list[Track], timestamp: float, frame_id: int) -> None:
        pre_open_flag = self._pre_open_entry_flag(timestamp)
        first_n_entries_flag = 1.0 if frame_id < 300 else 0.0
        for track in tracks:
            track.refresh_session_activity(timestamp)
            track.derived_features["pre_open_entry_flag"] = pre_open_flag
            track.derived_features["first_n_entries_flag"] = first_n_entries_flag

    def _pre_open_entry_flag(self, timestamp: float) -> float:
        now = datetime.fromtimestamp(timestamp)
        open_hour, open_minute = [int(part) for part in self._config.store.open_time.split(":", 1)]
        open_minutes = open_hour * 60 + open_minute
        now_minutes = now.hour * 60 + now.minute
        window_start = open_minutes - 60
        return 1.0 if window_start <= now_minutes < open_minutes else 0.0

    def _apply_group_assignments(self, tracks: list[Track], timestamp: float) -> None:
        assignments = self._group_engine.assign_groups(tracks)
        logged_groups: set[str] = set()
        for track in tracks:
            previous_group_id = track.group_id
            assignment = assignments.get(track.track_id)
            if assignment is None or assignment["group_id"] is None:
                if track.group_id:
                    track.remember_group_membership(timestamp)
                track.group_id = None
                track.group_probability = 0.0
                continue

            if previous_group_id and previous_group_id != assignment["group_id"]:
                track.previous_group_id = previous_group_id
                track.last_group_seen_at = timestamp

            track.group_id = assignment["group_id"]
            track.group_probability = assignment["group_probability"]
            if assignment["signals"]:
                track.derived_features["group_signals"] = assignment["signals"]
            if previous_group_id != track.group_id:
                self._event_hub.send(BaseEvent(
                    event_id=self._make_event_id(
                        event_type="group_updated",
                        track=track,
                        timestamp=timestamp,
                        suffix=track.group_id or "ungrouped",
                    ),
                    event_type="group_updated",
                    tenant_id=self._config.store.tenant_id,
                    store_id=self._config.store.store_id,
                    camera_id=self.camera_id,
                    timestamp=timestamp,
                    track_id=track.track_id,
                    store_visit_session_id=track.store_visit_session_id,
                    previous_group_id=track.previous_group_id,
                    group_id=track.group_id,
                    group_probability=track.group_probability,
                    classification_label=track.label.value,
                    employee_probability=track.employee_probability,
                    customer_probability=track.customer_probability,
                    unknown_probability=track.unknown_probability,
                    window_start=self._window_start(timestamp),
                    window_end=self._window_end(timestamp),
                    group_visitor_count=self._group_visitor_count(track, tracks),
                ))
            if track.group_id and track.group_id not in logged_groups:
                logged_groups.add(track.group_id)
                logger.info(
                    "[%s] Group detected: %s  prob=%.3f",
                    self.camera_id, track.group_id, track.group_probability,
                )

    def _emit_completed_sessions(self, timestamp: float) -> None:
        for track in self._tracker.tracks.values():
            if track.session_completed_emitted:
                continue

            completed_at: float | None = None
            if (
                track.pending_exit_at is not None
                and track.last_exit_seen_at is not None
                and timestamp >= track.pending_exit_at
                and track.last_seen <= track.last_exit_seen_at
            ):
                completed_at = track.pending_exit_at
            elif (not track.is_active) and (timestamp - track.last_seen >= self._track_lost_timeout_seconds):
                completed_at = track.last_seen + self._track_lost_timeout_seconds

            if completed_at is None:
                continue

            track.mark_session_completed(completed_at)
            self._event_hub.send(BaseEvent(
                event_id=self._make_event_id(
                    event_type="session_completed",
                    track=track,
                    timestamp=completed_at,
                    suffix=track.store_visit_session_id,
                ),
                event_type="session_completed",
                tenant_id=self._config.store.tenant_id,
                store_id=self._config.store.store_id,
                camera_id=self.camera_id,
                timestamp=completed_at,
                track_id=track.track_id,
                store_visit_session_id=track.store_visit_session_id,
                previous_group_id=track.previous_group_id,
                group_id=track.group_id,
                classification_label=track.label.value,
                employee_probability=track.employee_probability,
                customer_probability=track.customer_probability,
                unknown_probability=track.unknown_probability,
                group_probability=track.group_probability,
                window_start=self._window_start(completed_at),
                window_end=self._window_end(completed_at),
                session_completed_at=completed_at,
                session_duration_seconds=max(0.0, completed_at - track.store_visit_started_at),
                total_dwell_seconds=track.total_dwell_seconds,
                session_entry_count=track.entry_count,
                session_exit_count=track.exit_count,
                visited_zones=list(track.zones_visited),
            ))

    def _make_event_id(
        self,
        event_type: str,
        track: Track,
        timestamp: float,
        zone_session_id: str | None = None,
        zone_id: str | None = None,
        suffix: str | None = None,
    ) -> str:
        raw = "|".join([
            self.camera_id,
            event_type,
            str(track.track_id),
            track.store_visit_session_id,
            zone_id or "",
            zone_session_id or "",
            suffix or "",
            f"{timestamp:.6f}",
        ])
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

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
