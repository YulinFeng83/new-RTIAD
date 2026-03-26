"""
Threaded video stream reader.

Supports three source types (auto-detected from the URL string):
  - RTSP/HTTP URL  → live camera
  - Integer string → local webcam index
  - File path      → video file simulator with FPS throttling + optional loop
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)


class VideoStream:
    """
    Reads frames from a video source in a background thread.

    The latest frame is always available via `read()`.  For video files the
    reader throttles to the file's native FPS (or a configured target) so
    downstream processing sees real-time–like playback speed.
    """

    def __init__(
        self,
        source: str,
        *,
        camera_id: str = "cam",
        target_fps: int = 15,
        loop: bool = True,
        max_queue_size: int = 2,
        reconnect_delay: float = 5.0,
    ):
        self.camera_id = camera_id
        self._source = source
        self._target_fps = target_fps
        self._loop = loop
        self._reconnect_delay = reconnect_delay

        self._source_type = self._detect_source_type(source)
        self._cap: Optional[cv2.VideoCapture] = None
        self._frame: Optional[np.ndarray] = None
        self._frame_id: int = 0
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None

        self._native_fps: float = 0.0
        self._frame_width: int = 0
        self._frame_height: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()
        logger.info(
            "[%s] Stream started — source=%s type=%s",
            self.camera_id,
            self._source,
            self._source_type,
        )

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        self._release()
        logger.info("[%s] Stream stopped", self.camera_id)

    def read(self) -> tuple[bool, Optional[np.ndarray], int]:
        """Return (success, frame, frame_id). Frame may be None if not yet available."""
        with self._lock:
            if self._frame is None:
                return False, None, self._frame_id
            return True, self._frame.copy(), self._frame_id

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def frame_size(self) -> tuple[int, int]:
        return self._frame_width, self._frame_height

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_source_type(source: str) -> str:
        if source.isdigit():
            return "webcam"
        if source.startswith(("rtsp://", "http://", "https://")):
            return "rtsp"
        return "file"

    def _open(self) -> bool:
        src = int(self._source) if self._source_type == "webcam" else self._source

        if self._source_type == "file" and not Path(str(src)).exists():
            logger.error("[%s] Video file not found: %s", self.camera_id, src)
            return False

        self._cap = cv2.VideoCapture(src)
        if not self._cap.isOpened():
            logger.error("[%s] Failed to open source: %s", self.camera_id, src)
            return False

        self._native_fps = self._cap.get(cv2.CAP_PROP_FPS) or self._target_fps
        self._frame_width = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self._frame_height = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        logger.info(
            "[%s] Opened — %dx%d @ %.1f FPS (target %d)",
            self.camera_id,
            self._frame_width,
            self._frame_height,
            self._native_fps,
            self._target_fps,
        )
        return True

    def _release(self) -> None:
        if self._cap:
            self._cap.release()
            self._cap = None

    def _read_loop(self) -> None:
        while self._running:
            if self._cap is None or not self._cap.isOpened():
                if not self._open():
                    if self._source_type == "rtsp":
                        logger.warning(
                            "[%s] Reconnecting in %.0fs…",
                            self.camera_id,
                            self._reconnect_delay,
                        )
                        time.sleep(self._reconnect_delay)
                        continue
                    else:
                        self._running = False
                        return

            effective_fps = min(self._native_fps, self._target_fps)
            frame_interval = 1.0 / effective_fps if effective_fps > 0 else 0.033

            ret, frame = self._cap.read()

            if not ret:
                if self._source_type == "file":
                    if self._loop:
                        logger.info("[%s] Video ended, looping…", self.camera_id)
                        self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        continue
                    else:
                        logger.info("[%s] Video ended (single pass)", self.camera_id)
                        self._running = False
                        return
                else:
                    logger.warning("[%s] Lost stream, reconnecting…", self.camera_id)
                    self._release()
                    time.sleep(self._reconnect_delay)
                    continue

            with self._lock:
                self._frame = frame
                self._frame_id += 1

            if self._source_type == "file":
                time.sleep(frame_interval)
