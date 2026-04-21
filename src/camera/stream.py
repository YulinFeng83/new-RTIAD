"""
Threaded video stream reader.

Supports three source types (auto-detected from the URL string):
  - RTSP/HTTP URL  → live camera
  - Integer string → local webcam index
  - File path      → video file simulator with FPS throttling + optional loop
"""

from __future__ import annotations

import logging
import queue as _queue_mod
import threading
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, urlunparse, quote

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
        rotation_degrees: int = 0,
        max_queue_size: int = 1500,
        reconnect_delay: float = 5.0,
    ):
        self.camera_id = camera_id
        self._source = source
        self._target_fps = target_fps
        self._loop = loop
        self._reconnect_delay = reconnect_delay
        self._rotation_degrees = rotation_degrees % 360

        self._source_type = self._detect_source_type(source)
        queue_size = max_queue_size
        if self._source_type in {"rtsp", "webcam"}:
            queue_size = min(max_queue_size, 4)
        self._cap: Optional[cv2.VideoCapture] = None
        self._frame: Optional[np.ndarray] = None
        self._frame_id: int = 0
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._frame_queue: _queue_mod.Queue = _queue_mod.Queue(maxsize=queue_size)

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

    def read_queued(self) -> tuple[bool, Optional[np.ndarray], int]:
        """Return the next buffered frame.

        File sources preserve queued order to simulate real-time playback. Live
        RTSP and webcam sources drain intermediate frames and return the newest
        available frame to keep end-to-end latency bounded.
        """
        try:
            item = self._frame_queue.get(timeout=2.0)
        except _queue_mod.Empty:
            return False, None, -1
        if item is None:
            return False, None, -1

        if self._source_type in {"rtsp", "webcam"}:
            while True:
                try:
                    next_item = self._frame_queue.get_nowait()
                except _queue_mod.Empty:
                    break
                if next_item is None:
                    return False, None, -1
                item = next_item

        return True, item[0], item[1]

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

        # For RTSP sources try multiple OpenCV backends (FFMPEG, GStreamer, then default)
        if self._source_type == "rtsp":
            src_to_open = self._sanitize_rtsp_url(src)
            backends = [getattr(cv2, "CAP_FFMPEG", None), getattr(cv2, "CAP_GSTREAMER", None), None]
            self._cap = None
            for backend in backends:
                try:
                    logger.debug("[%s] Attempting open (backend=%s) %s", self.camera_id, backend, src_to_open)
                    if backend is None:
                        cap = cv2.VideoCapture(src_to_open)
                    else:
                        cap = cv2.VideoCapture(src_to_open, backend)
                    if cap is not None and cap.isOpened():
                        self._cap = cap
                        logger.debug("[%s] Open succeeded with backend=%s", self.camera_id, backend)
                        break
                    else:
                        if cap is not None:
                            cap.release()
                except Exception as exc:  # noqa: BLE001 - capture backend may raise
                    logger.debug("[%s] Open attempt raised: %s", self.camera_id, exc)

            if self._cap is None or not self._cap.isOpened():
                logger.error("[%s] Failed to open source: %s", self.camera_id, src)
                return False
        else:
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

    def _sanitize_rtsp_url(self, url: str) -> str:
        parsed = urlparse(url)
        if not parsed.scheme or parsed.scheme.lower() not in {"rtsp", "http", "https"}:
            return url

        netloc = parsed.netloc
        if "@" not in netloc:
            return url

        userinfo, hostport = netloc.split("@", 1)
        if ":" in userinfo:
            user, pwd = userinfo.split(":", 1)
        else:
            user, pwd = userinfo, ""

        user_q = quote(user, safe="")
        pwd_q = quote(pwd, safe="")
        new_netloc = f"{user_q}:{pwd_q}@{hostport}" if pwd else f"{user_q}@{hostport}"
        new = parsed._replace(netloc=new_netloc)
        return urlunparse(new)

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
                        try:
                            self._frame_queue.put(None, timeout=5.0)
                        except _queue_mod.Full:
                            pass
                        self._running = False
                        return
                else:
                    logger.warning("[%s] Lost stream, reconnecting…", self.camera_id)
                    self._release()
                    time.sleep(self._reconnect_delay)
                    continue

            frame = self._rotate_frame(frame)

            with self._lock:
                self._frame = frame
                self._frame_id += 1
                fid = self._frame_id

            try:
                self._frame_queue.put((frame, fid), timeout=2.0)
            except _queue_mod.Full:
                if self._source_type in {"rtsp", "webcam"}:
                    try:
                        self._frame_queue.get_nowait()
                        self._frame_queue.put_nowait((frame, fid))
                    except (_queue_mod.Empty, _queue_mod.Full):
                        pass

            if self._source_type == "file":
                time.sleep(frame_interval)

    def _rotate_frame(self, frame: np.ndarray) -> np.ndarray:
        if self._rotation_degrees == 90:
            return cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
        if self._rotation_degrees == 180:
            return cv2.rotate(frame, cv2.ROTATE_180)
        if self._rotation_degrees == 270:
            return cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
        return frame
