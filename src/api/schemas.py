"""
Pydantic request/response schemas for the REST API.
"""

from __future__ import annotations

import math
from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator

ZONE_TYPES = {"entry", "exit", "bidirectional", "staff_only"}
BUSINESS_ZONE_TYPES = {
    "aisle",
    "counter",
    "checkout",
    "entrance",
    "promo",
    "service_counter",
    "staff",
    "back_of_house",
}
FLOOR_ZONE_SOURCE_MODES = {"projected", "manual", "refined"}


class ZoneCreateRequest(BaseModel):
    id: str
    type: str = "bidirectional"
    business_zone_type: str = "aisle"
    polygon: list[list[int]]
    direction: list[float] = Field(default_factory=lambda: [0.0, -1.0])
    name: str = ""
    promo_zone_flag: bool = False

    @field_validator("type")
    @classmethod
    def validate_runtime_zone_type(cls, value: str) -> str:
        if value not in ZONE_TYPES:
            raise ValueError(f"type must be one of: {', '.join(sorted(ZONE_TYPES))}")
        return value

    @field_validator("business_zone_type")
    @classmethod
    def validate_business_zone_type(cls, value: str) -> str:
        if value not in BUSINESS_ZONE_TYPES:
            raise ValueError(
                f"business_zone_type must be one of: {', '.join(sorted(BUSINESS_ZONE_TYPES))}"
            )
        return value

    @field_validator("polygon")
    @classmethod
    def validate_polygon(cls, value: list[list[int]]) -> list[list[int]]:
        if len(value) < 3:
            raise ValueError("polygon must contain at least 3 points")
        for point in value:
            if len(point) < 2:
                raise ValueError("each polygon point must contain x and y")
        return value


class ZoneResponse(BaseModel):
    id: str
    camera_id: str
    type: str
    business_zone_type: str = "aisle"
    polygon: list[list[int]]
    direction: list[float]
    name: str
    promo_zone_flag: bool = False


class CameraResponse(BaseModel):
    id: str
    url: str
    store_id: str
    store_name: str
    scene_type: str
    zones: list[ZoneResponse]


class StoreFloorPlanRequest(BaseModel):
    canvas_width: int = Field(default=1200, gt=0)
    canvas_height: int = Field(default=800, gt=0)
    store_width_meters: float | None = Field(default=None, gt=0)
    store_height_meters: float | None = Field(default=None, gt=0)
    scale_meters_per_pixel: float | None = Field(default=None, gt=0)
    origin: str = "bottom_left"

    @model_validator(mode="after")
    def validate_scale(self) -> "StoreFloorPlanRequest":
        if self.store_width_meters is not None and self.canvas_width <= 0:
            raise ValueError("canvas_width must be positive when store_width_meters is set")
        return self


class CameraArrangementRequest(BaseModel):
    camera_id: str
    canvas_x: float = Field(ge=0)
    canvas_y: float = Field(ge=0)
    canvas_width: float = Field(default=160.0, gt=0)
    canvas_height: float = Field(default=100.0, gt=0)
    floor_x: float | None = None
    floor_y: float | None = None
    position: str = ""
    coverage_area: str = ""
    rotation_degrees: float = 0.0
    opacity: float = Field(default=0.75, ge=0.0, le=1.0)
    z_index: int = 0
    source_frame_width: int | None = Field(default=None, gt=0)
    source_frame_height: int | None = Field(default=None, gt=0)


class CameraAdjacencyRequest(BaseModel):
    camera_a_id: str
    camera_b_id: str
    edge_a: str = ""
    edge_b: str = ""
    distance_pixels: float = Field(default=0.0, ge=0)
    distance_meters: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def reject_self_edge(self) -> "CameraAdjacencyRequest":
        if self.camera_a_id == self.camera_b_id:
            raise ValueError("camera adjacency cannot reference the same camera twice")
        return self


class CameraOverlapRequest(BaseModel):
    camera_a_id: str
    camera_b_id: str
    confirmed_overlap: bool = False
    primary_camera_id: str = ""

    @model_validator(mode="after")
    def reject_self_overlap(self) -> "CameraOverlapRequest":
        if self.camera_a_id == self.camera_b_id:
            raise ValueError("camera overlap cannot reference the same camera twice")
        if self.primary_camera_id and self.primary_camera_id not in {self.camera_a_id, self.camera_b_id}:
            raise ValueError("primary_camera_id must be one of the overlap cameras")
        return self


class FloorPlanZoneRequest(BaseModel):
    id: str
    zone_name: str = ""
    zone_type: str = "aisle"
    source_mode: str = "manual"
    promo_zone_flag: bool = False
    map_x: float = Field(default=0.0, ge=0)
    map_y: float = Field(default=0.0, ge=0)
    map_width: float = Field(default=0.0, gt=0)
    map_height: float = Field(default=0.0, gt=0)
    source_camera_id: str | None = None
    source_zone_id: str | None = None
    map_polygon: list[list[float]] = Field(default_factory=list)

    @field_validator("zone_type")
    @classmethod
    def validate_floor_zone_type(cls, value: str) -> str:
        if value not in BUSINESS_ZONE_TYPES:
            raise ValueError(f"zone_type must be one of: {', '.join(sorted(BUSINESS_ZONE_TYPES))}")
        return value

    @field_validator("source_mode")
    @classmethod
    def validate_source_mode(cls, value: str) -> str:
        if value not in FLOOR_ZONE_SOURCE_MODES:
            raise ValueError(
                f"source_mode must be one of: {', '.join(sorted(FLOOR_ZONE_SOURCE_MODES))}"
            )
        return value


class SpatialConfigRequest(BaseModel):
    floor_plan: StoreFloorPlanRequest
    camera_arrangement: list[CameraArrangementRequest] = Field(default_factory=list)
    camera_adjacency: list[CameraAdjacencyRequest] = Field(default_factory=list)
    camera_overlaps: list[CameraOverlapRequest] = Field(default_factory=list)
    floor_zones: list[FloorPlanZoneRequest] = Field(default_factory=list)

    @field_validator("camera_arrangement")
    @classmethod
    def reject_duplicate_camera_ids(
        cls,
        cameras: list[CameraArrangementRequest],
    ) -> list[CameraArrangementRequest]:
        seen: set[str] = set()
        duplicates: set[str] = set()
        for camera in cameras:
            if camera.camera_id in seen:
                duplicates.add(camera.camera_id)
            seen.add(camera.camera_id)
        if duplicates:
            raise ValueError(f"duplicate camera IDs: {', '.join(sorted(duplicates))}")
        return cameras

    @field_validator("floor_zones")
    @classmethod
    def reject_duplicate_zone_ids(
        cls,
        zones: list[FloorPlanZoneRequest],
    ) -> list[FloorPlanZoneRequest]:
        seen: set[str] = set()
        duplicates: set[str] = set()
        for zone in zones:
            if zone.id in seen:
                duplicates.add(zone.id)
            seen.add(zone.id)
        if duplicates:
            raise ValueError(f"duplicate floor zone IDs: {', '.join(sorted(duplicates))}")
        return zones


class FootfallStatsResponse(BaseModel):
    store_id: str | None = None
    total_entries: int
    total_exits: int
    current_in_store: int
    employees_filtered: int
    total_group_entries: int
    total_group_exits: int
    current_groups_in_store: int


class ConfigUpdateRequest(BaseModel):
    """Accepts partial or full config updates as a raw dict."""
    config: dict


class CalibrationPreviewRequest(BaseModel):
    reference_points_image: list[list[float]]
    reference_points_floor: list[list[float]]
    image_width: int = Field(gt=0)
    image_height: int = Field(gt=0)

    @field_validator("reference_points_image", "reference_points_floor")
    @classmethod
    def validate_reference_points(cls, value: list[list[float]]) -> list[list[float]]:
        if not 4 <= len(value) <= 6:
            raise ValueError("exactly 4 to 6 reference points are required")
        for point in value:
            if len(point) != 2:
                raise ValueError("each reference point must contain exactly x and y")
            if not all(math.isfinite(coord) for coord in point):
                raise ValueError("reference points must be finite numbers")
        return value

    @model_validator(mode="after")
    def validate_matching_counts(self) -> "CalibrationPreviewRequest":
        if len(self.reference_points_image) != len(self.reference_points_floor):
            raise ValueError("reference_points_image and reference_points_floor must have matching counts")
        return self


class CameraCalibrationRequest(CalibrationPreviewRequest):
    active_flag: bool = True


class CameraCalibrationResponse(BaseModel):
    camera_id: str
    reference_points_image: list[list[float]]
    reference_points_floor: list[list[float]]
    homography_matrix: list[list[float]]
    calibrated_at: datetime | None = None
    active_flag: bool = False


class CalibrationPreviewResponse(BaseModel):
    camera_id: str
    homography_matrix: list[list[float]]
    reference_points_image: list[list[float]]
    reference_points_floor: list[list[float]]
    reprojection_error_pixels: float
    projected_floor_points: list[list[float]]
    valid: bool
    messages: list[str] = Field(default_factory=list)
