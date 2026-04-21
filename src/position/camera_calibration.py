from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from src.config import StoreFloorPlanConfig

MIN_REFERENCE_POINTS = 4
MAX_REFERENCE_POINTS = 6
MAX_REPROJECTION_ERROR_PIXELS = 20.0
MAX_REPROJECTION_ERROR_METERS = 0.75
MIN_HULL_AREA_RATIO = 0.0025


@dataclass
class CalibrationComputationResult:
    homography_matrix: list[list[float]] = field(default_factory=list)
    reference_points_image: list[list[float]] = field(default_factory=list)
    reference_points_floor: list[list[float]] = field(default_factory=list)
    reprojection_error_pixels: float = 0.0
    projected_floor_points: list[list[float]] = field(default_factory=list)
    valid: bool = False
    messages: list[str] = field(default_factory=list)


def compute_calibration_preview(
    *,
    reference_points_image: list[list[float]],
    reference_points_floor: list[list[float]],
    image_width: int,
    image_height: int,
    floor_plan: StoreFloorPlanConfig,
) -> CalibrationComputationResult:
    _validate_point_sets(
        reference_points_image=reference_points_image,
        reference_points_floor=reference_points_floor,
        image_width=image_width,
        image_height=image_height,
        floor_plan=floor_plan,
    )

    src = np.asarray(reference_points_image, dtype=np.float32)
    dst = np.asarray(reference_points_floor, dtype=np.float32)

    matrix, _mask = cv2.findHomography(src, dst, method=cv2.RANSAC)
    if matrix is None or matrix.shape != (3, 3):
        return CalibrationComputationResult(
            reference_points_image=reference_points_image,
            reference_points_floor=reference_points_floor,
            valid=False,
            messages=["Could not compute a valid homography matrix from the selected points."],
        )
    if not np.isfinite(matrix).all():
        return CalibrationComputationResult(
            reference_points_image=reference_points_image,
            reference_points_floor=reference_points_floor,
            valid=False,
            messages=["Homography matrix contains non-finite values."],
        )

    projected = cv2.perspectiveTransform(src.reshape(-1, 1, 2), matrix).reshape(-1, 2)
    if not np.isfinite(projected).all():
        return CalibrationComputationResult(
            homography_matrix=matrix.tolist(),
            reference_points_image=reference_points_image,
            reference_points_floor=reference_points_floor,
            valid=False,
            messages=["Projected floor points contain non-finite values."],
        )

    errors = np.linalg.norm(projected - dst, axis=1)
    reprojection_error_pixels = float(np.mean(errors))
    messages: list[str] = []
    valid = True

    max_error_pixels = MAX_REPROJECTION_ERROR_PIXELS
    if reprojection_error_pixels > max_error_pixels:
        valid = False
        messages.append(
            f"Reprojection error {reprojection_error_pixels:.2f}px exceeds {max_error_pixels:.2f}px."
        )

    if floor_plan.scale_meters_per_pixel is not None:
        reprojection_error_meters = reprojection_error_pixels * float(floor_plan.scale_meters_per_pixel)
        if reprojection_error_meters > MAX_REPROJECTION_ERROR_METERS:
            valid = False
            messages.append(
                f"Reprojection error {reprojection_error_meters:.2f}m exceeds {MAX_REPROJECTION_ERROR_METERS:.2f}m."
            )

    for idx, point in enumerate(projected.tolist(), start=1):
        x_coord, y_coord = point
        if x_coord < 0 or x_coord > floor_plan.canvas_width or y_coord < 0 or y_coord > floor_plan.canvas_height:
            valid = False
            messages.append(
                f"Projected floor point {idx} falls outside the shared floor plan bounds."
            )
            break

    return CalibrationComputationResult(
        homography_matrix=matrix.tolist(),
        reference_points_image=reference_points_image,
        reference_points_floor=reference_points_floor,
        reprojection_error_pixels=reprojection_error_pixels,
        projected_floor_points=[[float(x_coord), float(y_coord)] for x_coord, y_coord in projected.tolist()],
        valid=valid,
        messages=messages,
    )


def _validate_point_sets(
    *,
    reference_points_image: list[list[float]],
    reference_points_floor: list[list[float]],
    image_width: int,
    image_height: int,
    floor_plan: StoreFloorPlanConfig,
) -> None:
    if not 4 <= len(reference_points_image) <= 6:
        raise ValueError(
            f"reference_points_image must contain between {MIN_REFERENCE_POINTS} and {MAX_REFERENCE_POINTS} points"
        )
    if len(reference_points_image) != len(reference_points_floor):
        raise ValueError("reference point counts must match")

    if floor_plan.scale_meters_per_pixel is None:
        raise ValueError("Stage 1 floor plan scale_meters_per_pixel is required before calibration")

    _validate_points_in_bounds(reference_points_image, float(image_width), float(image_height), "image")
    _validate_points_in_bounds(
        reference_points_floor,
        float(floor_plan.canvas_width),
        float(floor_plan.canvas_height),
        "floor",
    )

    _validate_point_spread(reference_points_image, float(image_width * image_height), "image")
    _validate_point_spread(
        reference_points_floor,
        float(floor_plan.canvas_width * floor_plan.canvas_height),
        "floor",
    )


def _validate_points_in_bounds(
    points: list[list[float]],
    max_width: float,
    max_height: float,
    label: str,
) -> None:
    for idx, point in enumerate(points, start=1):
        if len(point) != 2:
            raise ValueError(f"{label} point {idx} must contain exactly 2 coordinates")
        x_coord = float(point[0])
        y_coord = float(point[1])
        if not np.isfinite([x_coord, y_coord]).all():
            raise ValueError(f"{label} point {idx} must contain finite numbers")
        if x_coord < 0 or x_coord > max_width or y_coord < 0 or y_coord > max_height:
            raise ValueError(
                f"{label} point {idx} lies outside the valid bounds ({max_width:.0f}x{max_height:.0f})"
            )


def _validate_point_spread(
    points: list[list[float]],
    reference_area: float,
    label: str,
) -> None:
    unique_points = {(round(point[0], 3), round(point[1], 3)) for point in points}
    if len(unique_points) < 4:
        raise ValueError(f"{label} reference points must contain at least 4 unique positions")

    contour = np.asarray(points, dtype=np.float32)
    hull = cv2.convexHull(contour)
    hull_area = float(cv2.contourArea(hull))
    if hull_area <= 0:
        raise ValueError(f"{label} reference points are degenerate or nearly collinear")
    if reference_area > 0 and (hull_area / reference_area) < MIN_HULL_AREA_RATIO:
        raise ValueError(f"{label} reference points are too tightly clustered to compute a stable calibration")
