from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.api.deps import app_state
from src.api.schemas import SpatialConfigRequest
from src.config import (
    CameraAdjacencyConfig,
    CameraArrangementConfig,
    CameraOverlapConfig,
    FloorPlanZoneConfig,
    SpatialConfig,
    StoreFloorPlanConfig,
)

router = APIRouter()


@router.get("/stores/{store_id}/layout")
async def get_store_layout(store_id: str) -> dict:
    config = app_state.config_manager.config
    _ensure_store_exists(config, store_id)
    return config.spatial.model_dump(mode="json")


@router.put("/stores/{store_id}/layout")
async def update_store_layout(store_id: str, req: SpatialConfigRequest) -> dict:
    config = app_state.config_manager.config
    _ensure_store_exists(config, store_id)
    _validate_spatial_request(config, req)

    config.spatial = SpatialConfig(
        floor_plan=StoreFloorPlanConfig(**req.floor_plan.model_dump()),
        camera_arrangement=[
            CameraArrangementConfig(**item.model_dump())
            for item in req.camera_arrangement
        ],
        camera_adjacency=[
            CameraAdjacencyConfig(**item.model_dump())
            for item in req.camera_adjacency
        ],
        camera_overlaps=[
            CameraOverlapConfig(**item.model_dump())
            for item in req.camera_overlaps
        ],
        floor_zones=[
            FloorPlanZoneConfig(**item.model_dump())
            for item in req.floor_zones
        ],
        camera_calibrations=list(config.spatial.camera_calibrations),
    )
    app_state.config_manager.update_config(config)
    return config.spatial.model_dump(mode="json")


def _ensure_store_exists(config, store_id: str) -> None:
    valid_store_ids = {config.store.store_id}
    valid_store_ids.update(cam.store_id for cam in config.cameras if cam.store_id)
    if store_id not in valid_store_ids:
        raise HTTPException(status_code=404, detail=f"Store {store_id} not found")


def _validate_spatial_request(config, req: SpatialConfigRequest) -> None:
    configured_camera_ids = {cam.id for cam in config.cameras}
    layout_camera_ids = {camera.camera_id for camera in req.camera_arrangement}
    unknown_cameras = layout_camera_ids - configured_camera_ids
    if unknown_cameras:
        raise HTTPException(
            status_code=422,
            detail=f"Layout references unknown camera IDs: {', '.join(sorted(unknown_cameras))}",
        )

    for edge in req.camera_adjacency:
        _validate_camera_ref(edge.camera_a_id, layout_camera_ids, "adjacency")
        _validate_camera_ref(edge.camera_b_id, layout_camera_ids, "adjacency")

    for overlap in req.camera_overlaps:
        _validate_camera_ref(overlap.camera_a_id, layout_camera_ids, "overlap")
        _validate_camera_ref(overlap.camera_b_id, layout_camera_ids, "overlap")
        if overlap.primary_camera_id:
            _validate_camera_ref(overlap.primary_camera_id, layout_camera_ids, "overlap primary")

    floor = req.floor_plan
    if floor.store_width_meters is not None:
        expected_scale = floor.store_width_meters / floor.canvas_width
        if floor.scale_meters_per_pixel is None:
            raise HTTPException(
                status_code=422,
                detail="scale_meters_per_pixel is required when store_width_meters is set",
            )
        if abs(floor.scale_meters_per_pixel - expected_scale) > 0.0001:
            raise HTTPException(
                status_code=422,
                detail="scale_meters_per_pixel must match store_width_meters / canvas_width",
            )

    for camera in req.camera_arrangement:
        if camera.canvas_x + camera.canvas_width > floor.canvas_width:
            raise HTTPException(
                status_code=422,
                detail=f"Camera {camera.camera_id} extends beyond canvas width",
            )
        if camera.canvas_y + camera.canvas_height > floor.canvas_height:
            raise HTTPException(
                status_code=422,
                detail=f"Camera {camera.camera_id} extends beyond canvas height",
            )

    for zone in req.floor_zones:
        if zone.source_camera_id:
            _validate_camera_ref(zone.source_camera_id, layout_camera_ids, "floor zone source")
        if zone.map_polygon:
            for point in zone.map_polygon:
                if len(point) < 2:
                    raise HTTPException(
                        status_code=422,
                        detail=f"Zone {zone.id} has an invalid map polygon point",
                    )
                if point[0] < 0 or point[0] > floor.canvas_width or point[1] < 0 or point[1] > floor.canvas_height:
                    raise HTTPException(
                        status_code=422,
                        detail=f"Zone {zone.id} map polygon extends beyond canvas",
                    )
        if zone.map_x + zone.map_width > floor.canvas_width:
            raise HTTPException(
                status_code=422,
                detail=f"Zone {zone.id} extends beyond canvas width",
            )
        if zone.map_y + zone.map_height > floor.canvas_height:
            raise HTTPException(
                status_code=422,
                detail=f"Zone {zone.id} extends beyond canvas height",
            )


def _validate_camera_ref(camera_id: str, valid_camera_ids: set[str], context: str) -> None:
    if camera_id not in valid_camera_ids:
        raise HTTPException(
            status_code=422,
            detail=f"Bad {context} camera reference: {camera_id}",
        )
