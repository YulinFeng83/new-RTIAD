"""
Camera and zone CRUD endpoints.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.api.deps import app_state
from src.api.schemas import CameraResponse, ZoneCreateRequest, ZoneResponse
from src.config import ZoneConfig
from src.zones.zone import Zone, ZoneType

router = APIRouter()


@router.get("/cameras", response_model=list[CameraResponse])
async def list_cameras():
    config = app_state.config_manager.config
    cameras = []
    for cam in config.cameras:
        zones = app_state.zone_manager.get_zones_for_camera(cam.id) if app_state.zone_manager else []
        store_id = cam.store_id or config.store.store_id
        store_name = cam.store_name or config.store.name
        cameras.append(CameraResponse(
            id=cam.id,
            url=cam.url,
            store_id=store_id,
            store_name=store_name,
            scene_type=cam.scene_type,
            zones=[
                ZoneResponse(
                    id=z.zone_id,
                    camera_id=z.camera_id,
                    type=z.zone_type.value,
                    polygon=[[p[0], p[1]] for p in z.polygon],
                    direction=list(z.direction_vector),
                    name=z.name,
                )
                for z in zones
            ],
        ))
    return cameras


@router.post("/cameras/{camera_id}/zones", response_model=ZoneResponse)
async def create_zone(camera_id: str, req: ZoneCreateRequest):
    config = app_state.config_manager.config
    cam_ids = [c.id for c in config.cameras]
    if camera_id not in cam_ids:
        raise HTTPException(status_code=404, detail=f"Camera {camera_id} not found")

    zone = Zone(
        zone_id=req.id,
        camera_id=camera_id,
        polygon=[(p[0], p[1]) for p in req.polygon],
        zone_type=ZoneType(req.type),
        direction_vector=(req.direction[0], req.direction[1]) if len(req.direction) >= 2 else (0.0, -1.0),
        name=req.name,
    )
    app_state.zone_manager.add_zone(zone)

    z_cfg = ZoneConfig(
        id=req.id,
        type=req.type,
        polygon=req.polygon,
        direction=req.direction,
        name=req.name,
    )
    for cam in config.cameras:
        if cam.id == camera_id:
            cam.zones = [z for z in cam.zones if z.id != req.id]
            cam.zones.append(z_cfg)
            break

    app_state.config_manager.update_config(config)

    return ZoneResponse(
        id=zone.zone_id,
        camera_id=zone.camera_id,
        type=zone.zone_type.value,
        polygon=req.polygon,
        direction=list(zone.direction_vector),
        name=zone.name,
    )


@router.delete("/cameras/{camera_id}/zones/{zone_id}")
async def delete_zone(camera_id: str, zone_id: str):
    removed = app_state.zone_manager.remove_zone(zone_id)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Zone {zone_id} not found")

    config = app_state.config_manager.config
    for cam in config.cameras:
        if cam.id == camera_id:
            cam.zones = [z for z in cam.zones if z.id != zone_id]
            break
    app_state.config_manager.update_config(config)

    return {"detail": f"Zone {zone_id} deleted"}
