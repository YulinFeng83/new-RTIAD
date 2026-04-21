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

from src.camera.stream import VideoStream
from src.analytics.group_likelihood import GroupLikelihoodEngine
from src.config import AppConfig
from src.counting.footfall_counter import FootfallCounter
from src.events.typed_events import (
    ZoneExitedEvent,
    format_event_time,
)
from src.events.event_hub import EventHubProducer
from src.models.employee_classifier import EmployeeClassifier
from src.position.floor_position_sampler import FloorCoordinateMapper, FloorPositionSampler
from src.reid.appearance_embedder import AppearanceEmbedder
from src.rendering.overlay import OverlayRenderer
from src.sessions.visit_session_manager import VisitSessionManager
from src.stitching.cross_camera_stitcher import CrossCameraStitcher
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
        visit_session_manager: VisitSessionManager,
        cross_camera_stitcher: CrossCameraStitcher,
        appearance_embedder: AppearanceEmbedder,
        floor_coordinate_mapper: FloorCoordinateMapper | None,
        floor_position_sampler: FloorPositionSampler | None,
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
        self._visit_sessions = visit_session_manager
        self._stitcher = cross_camera_stitcher
        self._appearance_embedder = appearance_embedder
        self._floor_coordinate_mapper = floor_coordinate_mapper
        self._floor_position_sampler = floor_position_sampler
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
        last_stats = self._footfall.stats_for_store(self._camera_store_id())

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
                    last_stats = self._footfall.stats_for_store(self._camera_store_id())
                except Exception:
                    logger.exception("[%s] Error processing frame %d", self.camera_id, frame_id)
                    annotated = frame
            else:
                annotated = self._overlay.render(frame, last_tracks, last_zones, last_stats)

            with self._frame_lock:
                self._annotated_frame = annotated
            write_counter += 1

    def _process_frame(self, frame: np.ndarray, frame_id: int) -> np.ndarray:
        ts = time.time()
        camera_store_id = self._camera_store_id()

        active_tracks = self._tracker.update(frame, frame_id)
        self._appearance_embedder.update_tracks(active_tracks, frame, ts)
        # TEMP OSNet verification instrumentation: remove after re-ID wiring is validated.
        for track in active_tracks:
            embedding_len = len(track.appearance_embedding) if track.appearance_embedding else 0
            has_embedding = embedding_len > 0
            logger.info(
                "[%s] TEMP OSNet embedding check track=%d present=%s length=%d model=%s updated_at=%s",
                self.camera_id,
                track.track_id,
                has_embedding,
                embedding_len,
                track.appearance_embedding_model,
                track.appearance_embedding_updated_at,
            )
            if self._config.reid.enabled and not has_embedding:
                logger.warning(
                    "[%s] TEMP OSNet embedding missing for visible active track=%d while reid.enabled=true",
                    self.camera_id,
                    track.track_id,
                )
        lost_tracks = [
            self._tracker.tracks[track_id]
            for track_id in self._tracker.lost_track_ids
            if track_id in self._tracker.tracks
        ]
        self._stitcher.remember_lost_tracks(self.camera_id, lost_tracks)
        self._update_track_behavior_context(active_tracks, ts, frame_id)
        self._update_calibrated_floor_positions(active_tracks)

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
        self._stitcher.try_link_new_tracks(
            self.camera_id,
            active_tracks,
            ts,
            group_visitor_count=1,
        )
        self._refresh_visit_snapshots(active_tracks, ts)

        for track, event_data in self._zone_manager.check_crossings(active_tracks, self.camera_id):
            event_timestamp = float(event_data.get("timestamp", ts))
            zone_id = str(event_data["zone_id"])
            zone = self._zone_manager.get_zone(zone_id)
            if zone is None:
                continue

            dwell_seconds = float(event_data.get("dwell_seconds", 0.0))
            raw_event_type = str(event_data["event_type"])
            raw_direction = event_data.get("direction")
            raw_zone_session_id = event_data.get("zone_session_id")

            if raw_event_type == "zone_exited":
                entered_at = event_data.get("entered_at")
                if entered_at is None:
                    logger.warning(
                        "[%s] Skipping zone_exited for track %d zone %s: missing entered_at",
                        self.camera_id,
                        track.track_id,
                        zone_id,
                    )
                else:
                    visit = self._visit_sessions.record_zone_exit(self.camera_id, track, dwell_seconds)
                    if visit is None:
                        logger.info(
                            "[%s] Skipping typed zone_exited for track %d zone %s: no active store visit",
                            self.camera_id,
                            track.track_id,
                            zone_id,
                        )
                        continue
                    self._event_hub.send(ZoneExitedEvent(
                        visit_id=str(raw_zone_session_id or self._make_event_id(
                            event_type="zone_exited",
                            track=track,
                            timestamp=event_timestamp,
                            zone_id=zone_id,
                        )),
                        zone_id=zone_id,
                        store_id=camera_store_id,
                        camera_id=self.camera_id,
                        store_visit_id=visit.store_visit_id,
                        dwell_seconds=dwell_seconds,
                        max_dwell_bucket=self._dwell_bucket(dwell_seconds),
                        entered_at=format_event_time(float(entered_at)),
                        exited_at=format_event_time(event_timestamp),
                        classification_label=track.label.value,
                        max_employee_probability=track.max_employee_probability,
                        edge_emitted_at=format_event_time(time.time()),
                    ))

            if raw_event_type == "door_crossed":
                if raw_direction is None:
                    logger.warning(
                        "[%s] Skipping door_crossed for track %d zone %s: missing direction",
                        self.camera_id,
                        track.track_id,
                        zone_id,
                    )
                    continue

                door_event = self._visit_sessions.record_door_crossing(
                    store_id=camera_store_id,
                    camera_id=self.camera_id,
                    track=track,
                    zone=zone,
                    direction=str(raw_direction),
                    crossed_at=event_timestamp,
                    group_visitor_count=self._group_visitor_count(track, active_tracks),
                )
                if door_event is not None:
                    self._event_hub.send(door_event)

                crossing = CrossingResult(zone_id=zone_id, direction=str(raw_direction))
                ff_event = self._footfall.process_crossing(
                    camera_store_id,
                    track,
                    crossing,
                    zone,
                    event_timestamp,
                    zone_session_id=raw_zone_session_id,
                )
                if ff_event:
                    if ff_event.event_type == "exit":
                        track.mark_store_exit(ff_event.zone_id, event_timestamp)
                        track.mark_pending_exit(event_timestamp, self._exit_confirmation_cooldown_seconds)
                    elif ff_event.event_type == "entry":
                        track.mark_store_entry(ff_event.zone_id, event_timestamp)
                        track.clear_pending_exit()

        self._emit_floor_position_samples(active_tracks, camera_store_id, ts)

        self._emit_completed_sessions(ts)

        zones = self._zone_manager.get_zones_for_camera(self.camera_id)
        stats = self._footfall.stats_for_store(camera_store_id)
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

    def _refresh_visit_snapshots(self, tracks: list[Track], timestamp: float) -> None:
        store_id = self._camera_store_id()
        for track in tracks:
            self._visit_sessions.refresh_track(
                store_id=store_id,
                camera_id=self.camera_id,
                track=track,
                timestamp=timestamp,
                group_visitor_count=self._group_visitor_count(track, tracks),
            )

    def _update_calibrated_floor_positions(self, tracks: list[Track]) -> None:
        for track in tracks:
            bbox = track.current_bbox
            if bbox is None:
                self._clear_floor_features(track)
                continue

            x1, _y1, x2, y2 = bbox
            foot_point = (int(round((x1 + x2) / 2.0)), int(round(y2)))
            track.derived_features["image_footpoint_x"] = float(foot_point[0])
            track.derived_features["image_footpoint_y"] = float(foot_point[1])

            if self._floor_coordinate_mapper is None:
                self._clear_floor_features(track)
                continue

            floor_point = self._floor_coordinate_mapper.image_to_floor(self.camera_id, foot_point)
            if floor_point is None:
                self._clear_floor_features(track)
                continue

            track.derived_features["floor_x"] = float(floor_point[0])
            track.derived_features["floor_y"] = float(floor_point[1])
            track.derived_features["floor_position_calibrated"] = 1.0

    def _clear_floor_features(self, track: Track) -> None:
        track.derived_features.pop("floor_x", None)
        track.derived_features.pop("floor_y", None)
        track.derived_features.pop("floor_position_calibrated", None)

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
            next_group_id = None if assignment is None else assignment["group_id"]
            if assignment is None or next_group_id is None:
                if track.group_id:
                    track.remember_group_membership(timestamp)
                track.record_group_transition(previous_group_id, None)
                track.group_id = None
                track.group_probability = 0.0
                continue

            if previous_group_id and previous_group_id != next_group_id:
                track.previous_group_id = previous_group_id
                track.last_group_seen_at = timestamp

            track.record_group_transition(previous_group_id, next_group_id)
            track.group_id = next_group_id
            track.group_probability = assignment["group_probability"]
            if assignment["signals"]:
                track.derived_features["group_signals"] = assignment["signals"]
            if track.group_id and track.group_id not in logged_groups:
                logged_groups.add(track.group_id)
                logger.info(
                    "[%s] Group detected: %s  prob=%.3f",
                    self.camera_id, track.group_id, track.group_probability,
                )

    def _emit_completed_sessions(self, timestamp: float) -> None:
        completed = self._visit_sessions.close_due_visits(
            camera_id=self.camera_id,
            tracks=self._tracker.tracks,
            timestamp=timestamp,
            inactivity_timeout_seconds=self._track_lost_timeout_seconds,
        )
        for visit, track in completed:
            self._event_hub.send(self._visit_sessions.to_session_completed_event(visit))
            self._visit_sessions.mark_completion_emitted(visit)
            if self._floor_position_sampler is not None:
                self._floor_position_sampler.forget_visit(visit.store_visit_id)
            if track is not None:
                track.mark_session_completed(visit.closed_at or timestamp)
            try:
                if track is not None and hasattr(self._tracker, "retire_track"):
                    self._tracker.retire_track(track.track_id)
            except Exception:
                logger.exception(
                    "[%s] Failed to retire track after session_completed for visit %s",
                    self.camera_id,
                    visit.store_visit_id,
                )

    def _camera_store_id(self) -> str:
        return next(
            (
                cam.store_id or self._config.store.store_id
                for cam in self._config.cameras
                if cam.id == self.camera_id
            ),
            self._config.store.store_id,
        )

    def _emit_floor_position_samples(
        self,
        tracks: list[Track],
        store_id: str,
        timestamp: float,
    ) -> None:
        if self._floor_position_sampler is None:
            return

        for track in tracks:
            if track.derived_features.get("floor_position_calibrated") != 1.0:
                continue
            visit = self._visit_sessions.active_visit_for_track(self.camera_id, track.track_id)
            if visit is None:
                continue

            event = self._floor_position_sampler.maybe_sample(
                store_id=store_id,
                camera_id=self.camera_id,
                zone_id=self._current_zone_id(track),
                track=track,
                visit=visit,
                emitted_at=timestamp,
            )
            if event is not None:
                self._event_hub.send(event)

    def _current_zone_id(self, track: Track) -> str | None:
        if not track.zone_entry_times:
            return None
        return max(track.zone_entry_times.items(), key=lambda item: item[1])[0]

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
        digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()
        return f"evt-{digest[:20]}"

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
            return "30-60s"
        if dwell_seconds < 120:
            return "60-120s"
        return ">120s"
