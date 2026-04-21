from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from src.api.deps import app_state
from src.api.schemas import (
    CalibrationPreviewRequest,
    CalibrationPreviewResponse,
    CameraCalibrationRequest,
    CameraCalibrationResponse,
)
from src.config import CameraCalibrationConfig
from src.position.camera_calibration import compute_calibration_preview

router = APIRouter()


@router.get("/cameras/{camera_id}/calibration", response_model=CameraCalibrationResponse)
async def get_camera_calibration(camera_id: str) -> CameraCalibrationResponse:
    config = app_state.config_manager.config
    _ensure_camera_exists(config, camera_id)
    calibration = next(
        (item for item in config.spatial.camera_calibrations if item.camera_id == camera_id),
        None,
    )
    if calibration is None:
        raise HTTPException(status_code=404, detail=f"Calibration for camera {camera_id} not found")
    return CameraCalibrationResponse(**calibration.model_dump())


@router.post("/cameras/{camera_id}/calibration/preview", response_model=CalibrationPreviewResponse)
async def preview_camera_calibration(
    camera_id: str,
    req: CalibrationPreviewRequest,
) -> CalibrationPreviewResponse:
    config = app_state.config_manager.config
    _ensure_camera_exists(config, camera_id)
    try:
        preview = compute_calibration_preview(
            reference_points_image=req.reference_points_image,
            reference_points_floor=req.reference_points_floor,
            image_width=req.image_width,
            image_height=req.image_height,
            floor_plan=config.spatial.floor_plan,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return CalibrationPreviewResponse(
        camera_id=camera_id,
        homography_matrix=preview.homography_matrix,
        reference_points_image=preview.reference_points_image,
        reference_points_floor=preview.reference_points_floor,
        reprojection_error_pixels=preview.reprojection_error_pixels,
        projected_floor_points=preview.projected_floor_points,
        valid=preview.valid,
        messages=preview.messages,
    )


@router.put("/cameras/{camera_id}/calibration", response_model=CameraCalibrationResponse)
async def save_camera_calibration(
    camera_id: str,
    req: CameraCalibrationRequest,
) -> CameraCalibrationResponse:
    config = app_state.config_manager.config
    _ensure_camera_exists(config, camera_id)
    try:
        preview = compute_calibration_preview(
            reference_points_image=req.reference_points_image,
            reference_points_floor=req.reference_points_floor,
            image_width=req.image_width,
            image_height=req.image_height,
            floor_plan=config.spatial.floor_plan,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if not preview.valid:
        raise HTTPException(
            status_code=422,
            detail="; ".join(preview.messages) or "Calibration preview is invalid",
        )

    calibration = CameraCalibrationConfig(
        camera_id=camera_id,
        reference_points_image=preview.reference_points_image,
        reference_points_floor=preview.reference_points_floor,
        homography_matrix=preview.homography_matrix,
        calibrated_at=datetime.now(timezone.utc),
        active_flag=req.active_flag,
    )
    existing = [
        item for item in config.spatial.camera_calibrations
        if item.camera_id != camera_id
    ]
    existing.append(calibration)
    config.spatial.camera_calibrations = existing
    app_state.config_manager.update_config(config)
    return CameraCalibrationResponse(**calibration.model_dump())


def _ensure_camera_exists(config, camera_id: str) -> None:
    configured_camera_ids = {camera.id for camera in config.cameras}
    if camera_id not in configured_camera_ids:
        raise HTTPException(status_code=404, detail=f"Camera {camera_id} not found")
