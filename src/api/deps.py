"""
Dependency injection — shared state accessible by API routes.
"""

from __future__ import annotations

from typing import Optional

from src.camera.manager import CameraManager
from src.config import ConfigManager
from src.counting.footfall_counter import FootfallCounter
from src.pipeline import CameraPipeline
from src.position.homography_mapper import HomographyFloorCoordinateMapper
from src.zones.zone_manager import ZoneManager


class AppState:
    """Holds shared references to all runtime components."""

    def __init__(self):
        self.config_manager: Optional[ConfigManager] = None
        self.camera_manager: Optional[CameraManager] = None
        self.zone_manager: Optional[ZoneManager] = None
        self.footfall_counter: Optional[FootfallCounter] = None
        self.floor_coordinate_mapper: Optional[HomographyFloorCoordinateMapper] = None
        self.pipelines: dict[str, CameraPipeline] = {}


app_state = AppState()
