"""
ByteTrack wrapper — persistent multi-object tracking via Ultralytics.

Maintains Track objects with stable IDs across frames.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

import numpy as np
from ultralytics import YOLO

from src.config import DetectionConfig, TrackingConfig
from src.tracking.track import Track

logger = logging.getLogger(__name__)

PERSON_CLASS_ID = 0


class PersonTracker:
    """
    Combined YOLOv8 detection + ByteTrack tracking.

    Uses `model.track()` which internally runs detection then applies the
    chosen tracker (ByteTrack or BoT-SORT) to assign persistent IDs.
    """

    def __init__(
        self,
        detection_config: DetectionConfig,
        tracking_config: TrackingConfig,
        device: str = "cpu",
        camera_id: str = "cam",
    ):
        self._det_config = detection_config
        self._trk_config = tracking_config
        self._device = device
        self._camera_id = camera_id
        self._model: Optional[YOLO] = None
        self._tracks: dict[int, Track] = {}
        self._new_track_ids: set[int] = set()
        self._lost_track_ids: set[int] = set()

    def load(self) -> None:
        logger.info("Loading model %s for tracking on %s", self._det_config.model, self._device)
        self._model = YOLO(self._det_config.model)
        self._model.to(self._device)
        logger.info("Tracker model loaded")

    @property
    def tracks(self) -> dict[int, Track]:
        return self._tracks

    def active_tracks(self) -> list[Track]:
        return [t for t in self._tracks.values() if t.is_active]

    @property
    def new_track_ids(self) -> set[int]:
        return set(self._new_track_ids)

    @property
    def lost_track_ids(self) -> set[int]:
        return set(self._lost_track_ids)

    def update(self, frame: np.ndarray, frame_id: int) -> list[Track]:
        """
        Run detection + tracking on a frame.

        Returns the list of currently active tracks (updated with new positions).
        """
        if self._model is None:
            raise RuntimeError("Model not loaded. Call load() first.")

        ts = time.time()
        self._new_track_ids.clear()
        self._lost_track_ids.clear()

        results = self._model.track(
            frame,
            classes=[PERSON_CLASS_ID],
            conf=self._det_config.confidence,
            iou=self._det_config.iou_threshold,
            tracker=f"{self._trk_config.tracker}.yaml",
            persist=True,
            verbose=False,
        )

        seen_ids: set[int] = set()

        for result in results:
            if result.boxes is None or result.boxes.id is None:
                continue
            track_ids = result.boxes.id.cpu().numpy().astype(int)
            boxes = result.boxes.xyxy.cpu().numpy().astype(int)

            for tid, box in zip(track_ids, boxes):
                tid = int(tid)
                seen_ids.add(tid)
                bbox = (int(box[0]), int(box[1]), int(box[2]), int(box[3]))

                if tid not in self._tracks:
                    track = Track(track_id=tid, camera_id=self._camera_id, first_seen=ts)
                    self._tracks[tid] = track
                    self._new_track_ids.add(tid)
                    logger.debug("[%s] New track %d", self._camera_id, tid)

                self._tracks[tid].add_point(bbox, frame_id, ts)
                self._tracks[tid].is_active = True

        self._cleanup_lost_tracks(seen_ids, frame_id)
        return self.active_tracks()

    def _cleanup_lost_tracks(self, seen_ids: set[int], current_frame: int) -> None:
        """Mark tracks as inactive if they haven't been seen for max_lost_frames."""
        max_lost = self._trk_config.max_lost_frames
        for tid, track in list(self._tracks.items()):
            if tid in seen_ids:
                continue
            if not track.history:
                continue
            frames_since = current_frame - track.history[-1].frame_id
            if frames_since > max_lost:
                track.is_active = False
                self._lost_track_ids.add(tid)

    def retire_track(self, track_id: int) -> None:
        """Remove a track from the tracker's registry immediately.

        This is a lightweight safe removal used when a session has been
        completed and we want to stop tracking the person. It leaves the
        Track object for any external references but removes it from
        active tracking to avoid further processing.
        """
        try:
            if track_id in self._tracks:
                # mark inactive and remove
                t = self._tracks.pop(track_id)
                try:
                    t.is_active = False
                except Exception:
                    pass
                logger.debug("[%s] Retired track %d", self._camera_id, track_id)
        except Exception:
            logger.exception("Failed to retire track %s", track_id)
