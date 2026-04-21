from __future__ import annotations

import threading

import cv2
import numpy as np

from src.config import SpatialConfig


class HomographyFloorCoordinateMapper:
    """Maps camera image points into shared floor coordinates using saved homographies."""

    def __init__(self, spatial_config: SpatialConfig):
        self._lock = threading.RLock()
        self._spatial_config = spatial_config
        self._matrices_by_camera: dict[str, np.ndarray] = {}
        self._reload(spatial_config)

    def on_config_change(self, spatial_config: SpatialConfig) -> None:
        with self._lock:
            self._reload(spatial_config)

    def image_to_floor(
        self,
        camera_id: str,
        point: tuple[int, int],
    ) -> tuple[float, float] | None:
        with self._lock:
            matrix = self._matrices_by_camera.get(camera_id)
            floor_plan = self._spatial_config.floor_plan
            if matrix is None or floor_plan.scale_meters_per_pixel is None:
                return None

            projected = cv2.perspectiveTransform(
                np.asarray([[[float(point[0]), float(point[1])]]], dtype=np.float32),
                matrix,
            ).reshape(2)
            if not np.isfinite(projected).all():
                return None

            x_px = float(projected[0])
            y_px = float(projected[1])
            if x_px < 0 or x_px > floor_plan.canvas_width or y_px < 0 or y_px > floor_plan.canvas_height:
                return None

            scale = float(floor_plan.scale_meters_per_pixel)
            floor_x = x_px * scale
            if floor_plan.origin == "bottom_left":
                floor_y = (float(floor_plan.canvas_height) - y_px) * scale
            else:
                floor_y = y_px * scale
            return floor_x, floor_y

    def _reload(self, spatial_config: SpatialConfig) -> None:
        self._spatial_config = spatial_config
        matrices_by_camera: dict[str, np.ndarray] = {}
        for calibration in spatial_config.camera_calibrations:
            if not calibration.active_flag:
                continue
            matrix = np.asarray(calibration.homography_matrix, dtype=np.float64)
            if matrix.shape != (3, 3) or not np.isfinite(matrix).all():
                continue
            matrices_by_camera[calibration.camera_id] = matrix
        self._matrices_by_camera = matrices_by_camera
