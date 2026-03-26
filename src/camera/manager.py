"""
Multi-camera lifecycle manager.

Creates / starts / stops VideoStream instances based on config.
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np

from src.camera.stream import VideoStream
from src.config import AppConfig, CameraConfig

logger = logging.getLogger(__name__)


class CameraManager:
    """Manages all camera streams for the application."""

    def __init__(self, config: AppConfig):
        self._streams: dict[str, VideoStream] = {}
        self._apply_config(config)

    def _apply_config(self, config: AppConfig) -> None:
        for cam_cfg in config.cameras:
            if cam_cfg.id not in self._streams:
                self._streams[cam_cfg.id] = self._create_stream(cam_cfg, config)

    def _create_stream(self, cam: CameraConfig, app_cfg: AppConfig) -> VideoStream:
        return VideoStream(
            source=cam.url,
            camera_id=cam.id,
            target_fps=app_cfg.system.fps_target,
            loop=cam.loop,
        )

    def start_all(self) -> None:
        for cam_id, stream in self._streams.items():
            logger.info("Starting camera %s", cam_id)
            stream.start()

    def stop_all(self) -> None:
        for cam_id, stream in self._streams.items():
            logger.info("Stopping camera %s", cam_id)
            stream.stop()

    def get_stream(self, camera_id: str) -> Optional[VideoStream]:
        return self._streams.get(camera_id)

    def read_frame(self, camera_id: str) -> tuple[bool, Optional[np.ndarray], int]:
        stream = self._streams.get(camera_id)
        if stream is None:
            return False, None, 0
        return stream.read()

    def list_cameras(self) -> list[str]:
        return list(self._streams.keys())

    def add_camera(self, cam_cfg: CameraConfig, app_cfg: AppConfig) -> None:
        if cam_cfg.id in self._streams:
            logger.warning("Camera %s already exists", cam_cfg.id)
            return
        stream = self._create_stream(cam_cfg, app_cfg)
        self._streams[cam_cfg.id] = stream
        stream.start()

    def remove_camera(self, camera_id: str) -> None:
        stream = self._streams.pop(camera_id, None)
        if stream:
            stream.stop()

    def on_config_change(self, config: AppConfig) -> None:
        """Handle hot-reload: add new cameras, keep existing ones running."""
        configured_ids = {c.id for c in config.cameras}
        current_ids = set(self._streams.keys())

        for cam_cfg in config.cameras:
            if cam_cfg.id not in current_ids:
                self.add_camera(cam_cfg, config)

        for cam_id in current_ids - configured_ids:
            self.remove_camera(cam_id)
