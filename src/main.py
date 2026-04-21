"""
RetailVision entry point.

Initializes config, loads models, starts camera pipelines, and launches
the FastAPI server.
"""

from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

import uvicorn

from src.api.app import create_app
from src.api.deps import app_state
from src.camera.manager import CameraManager
from src.config import ConfigManager
from src.counting.footfall_counter import FootfallCounter
from src.events.event_hub import EventHubProducer
from src.models.employee_classifier import EmployeeClassifier
from src.pipeline import CameraPipeline
from src.position.floor_position_sampler import FloorPositionSampler
from src.position.homography_mapper import HomographyFloorCoordinateMapper
from src.reid.appearance_embedder import OSNetAppearanceEmbedder
from src.rendering.overlay import OverlayRenderer
from src.sessions.visit_session_manager import VisitSessionManager
from src.stitching.cross_camera_stitcher import CrossCameraStitcher
from src.tracking.tracker import PersonTracker
from src.zones.zone_manager import ZoneManager

logger = logging.getLogger(__name__)


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )
    logging.getLogger("azure").setLevel(logging.WARNING)
    logging.getLogger("azure.eventhub").setLevel(logging.WARNING)
    logging.getLogger("azure.eventhub._pyamqp").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("huggingface_hub").setLevel(logging.WARNING)


def main(config_path: str | None = None) -> None:
    config_mgr = ConfigManager(config_path)
    cfg = config_mgr.config

    setup_logging(cfg.system.log_level)
    logger.info("Starting RetailVision — store: %s", cfg.store.name)

    # --- Camera manager ---
    camera_mgr = CameraManager(cfg)
    camera_mgr.start_all()

    # --- Zone manager ---
    zone_mgr = ZoneManager()
    zone_mgr.load_from_config(cfg)

    # --- Footfall counter ---
    footfall = FootfallCounter()

    # --- Store visit sessions ---
    visit_sessions = VisitSessionManager(
        exit_confirmation_cooldown_seconds=float(cfg.tracking.exit_confirmation_cooldown_seconds)
    )

    # --- Cross-camera stitching ---
    stitcher = CrossCameraStitcher(
        spatial_config=cfg.spatial,
        visit_session_manager=visit_sessions,
        temporal_gate_seconds=float(cfg.reid.temporal_gate_seconds),
        appearance_threshold=float(cfg.reid.appearance_similarity_threshold),
        min_score=float(cfg.reid.min_stitch_score),
        ambiguity_margin=float(cfg.reid.ambiguity_margin),
    )

    # --- OSNet appearance embeddings for cross-camera stitching ---
    appearance_embedder = OSNetAppearanceEmbedder(
        config=cfg.reid,
        device=cfg.system.device,
    )
    appearance_embedder.load()

    # --- Stage 2 calibrated image->floor mapping ---
    floor_coordinate_mapper = HomographyFloorCoordinateMapper(cfg.spatial)
    floor_position_sampler = FloorPositionSampler(
        mapper=floor_coordinate_mapper,
        movement_threshold=0.5,
    )

    # --- Event Hub ---
    event_hub = EventHubProducer(cfg.event_hub)
    event_hub.start()

    # --- Overlay renderer ---
    overlay = OverlayRenderer(cfg.overlay)

    # --- Employee classifier (shared across pipelines) ---
    classifier = EmployeeClassifier(
        config=cfg.employee_detection,
        device=cfg.system.device,
        store_open_time=cfg.store.open_time,
    )
    classifier.load()

    # --- Build per-camera pipelines ---
    pipelines: dict[str, CameraPipeline] = {}
    for cam_cfg in cfg.cameras:
        stream = camera_mgr.get_stream(cam_cfg.id)
        if stream is None:
            logger.warning("No stream for camera %s, skipping pipeline", cam_cfg.id)
            continue

        tracker = PersonTracker(
            detection_config=cfg.detection,
            tracking_config=cfg.tracking,
            device=cfg.system.device,
            camera_id=cam_cfg.id,
        )
        tracker.load()

        pipeline = CameraPipeline(
            camera_id=cam_cfg.id,
            stream=stream,
            tracker=tracker,
            classifier=classifier,
            zone_manager=zone_mgr,
            footfall_counter=footfall,
            overlay_renderer=overlay,
            event_hub=event_hub,
            visit_session_manager=visit_sessions,
            cross_camera_stitcher=stitcher,
            appearance_embedder=appearance_embedder,
            floor_coordinate_mapper=floor_coordinate_mapper,
            floor_position_sampler=floor_position_sampler,
            config=cfg,
        )
        pipelines[cam_cfg.id] = pipeline
        pipeline.start()

    # --- Populate shared state for API ---
    app_state.config_manager = config_mgr
    app_state.camera_manager = camera_mgr
    app_state.zone_manager = zone_mgr
    app_state.footfall_counter = footfall
    app_state.floor_coordinate_mapper = floor_coordinate_mapper
    app_state.pipelines = pipelines

    # --- Hot-reload callbacks ---
    config_mgr.on_change(lambda c: zone_mgr.on_config_change(c))
    config_mgr.on_change(lambda c: overlay.on_config_change(c.overlay))
    config_mgr.on_change(lambda c: classifier.on_config_change(c.employee_detection))
    config_mgr.on_change(lambda c: event_hub.on_config_change(c.event_hub))
    config_mgr.on_change(lambda c: visit_sessions.on_config_change(float(c.tracking.exit_confirmation_cooldown_seconds)))
    config_mgr.on_change(lambda c: stitcher.on_config_change(c.spatial))
    config_mgr.on_change(lambda c: floor_coordinate_mapper.on_config_change(c.spatial))
    config_mgr.on_change(lambda c: stitcher.on_reid_settings_change(
        temporal_gate_seconds=float(c.reid.temporal_gate_seconds),
        appearance_threshold=float(c.reid.appearance_similarity_threshold),
        min_score=float(c.reid.min_stitch_score),
        ambiguity_margin=float(c.reid.ambiguity_margin),
    ))
    config_mgr.on_change(lambda c: appearance_embedder.on_config_change(c.reid))
    config_mgr.on_change(lambda c: camera_mgr.on_config_change(c))
    config_mgr.start_watching()

    # --- Start FastAPI ---
    app = create_app()
    logger.info("Starting API server on http://0.0.0.0:8000")

    try:
        uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
    except KeyboardInterrupt:
        logger.info("Shutting down…")
    finally:
        for p in pipelines.values():
            p.stop()
        camera_mgr.stop_all()
        event_hub.stop()
        config_mgr.stop_watching()
        logger.info("Shutdown complete")


if __name__ == "__main__":
    config_file = sys.argv[1] if len(sys.argv) > 1 else None
    main(config_file)
