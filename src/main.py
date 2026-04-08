"""
RetailVision entry point.

Initializes config, loads models, starts camera pipelines, and launches
the FastAPI server.
"""

from __future__ import annotations

import argparse
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
from src.config import ConfigManager, build_test_video_config, discover_video_files
from src.counting.footfall_counter import FootfallCounter
from src.events.event_hub import EventHubProducer
from src.models.employee_classifier import EmployeeClassifier
from src.pipeline import CameraPipeline
from src.rendering.overlay import OverlayRenderer
from src.tracking.tracker import PersonTracker
from src.zones.zone_manager import ZoneManager

logger = logging.getLogger(__name__)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run RetailVision")
    parser.add_argument("config_path", nargs="?", help="Path to a YAML config file")
    parser.add_argument("--video-dir", help="Load all videos from a directory as test cameras")
    parser.add_argument("--video", action="append", default=[], help="Add a specific test video path")
    parser.add_argument("--single-pass", action="store_true", help="Do not loop test videos")
    parser.add_argument("--output-dir", default="outputs", help="Directory for saved annotated video outputs")
    save_group = parser.add_mutually_exclusive_group()
    save_group.add_argument("--save-output", dest="save_output", action="store_true", help="Save annotated video outputs")
    save_group.add_argument("--no-save-output", dest="save_output", action="store_false", help="Disable saving annotated video outputs")
    parser.set_defaults(save_output=None)
    return parser.parse_args(argv)


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )


def main(
    config_path: str | None = None,
    *,
    video_dir: str | None = None,
    video_paths: list[str] | None = None,
    loop_videos: bool = True,
    record_output: bool | None = None,
    output_dir: str = "outputs",
) -> None:
    config_mgr = ConfigManager(config_path)

    selected_videos: list[Path] = []
    if video_dir:
        selected_videos.extend(discover_video_files(video_dir))
    if video_paths:
        selected_videos.extend(Path(p).resolve() for p in video_paths)
    if selected_videos:
        cfg = build_test_video_config(
            config_mgr.config,
            selected_videos,
            loop=loop_videos,
            record_output=True if record_output is None else record_output,
            output_dir=output_dir,
        )
        config_mgr.update_config(cfg, persist=False)

    cfg = config_mgr.config
    if not selected_videos:
        if record_output is not None:
            cfg.system.record_output = record_output
        cfg.system.output_dir = output_dir

    setup_logging(cfg.system.log_level)
    logger.info("Starting RetailVision — store: %s", cfg.store.name)
    if selected_videos:
        logger.info("Loaded %d test videos", len(selected_videos))
        if cfg.system.record_output:
            logger.info("Saving annotated outputs to %s", cfg.system.output_dir)
        for camera in cfg.cameras:
            logger.info("Test camera %s -> %s", camera.id, camera.url)

    # --- Camera manager ---
    camera_mgr = CameraManager(cfg)
    camera_mgr.start_all()

    # --- Zone manager ---
    zone_mgr = ZoneManager()
    zone_mgr.load_from_config(cfg)

    # --- Footfall counter ---
    footfall = FootfallCounter()

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
            config=cfg,
        )
        pipelines[cam_cfg.id] = pipeline
        pipeline.start()

    # --- Populate shared state for API ---
    app_state.config_manager = config_mgr
    app_state.camera_manager = camera_mgr
    app_state.zone_manager = zone_mgr
    app_state.footfall_counter = footfall
    app_state.pipelines = pipelines

    # --- Hot-reload callbacks ---
    config_mgr.on_change(lambda c: zone_mgr.on_config_change(c))
    config_mgr.on_change(lambda c: overlay.on_config_change(c.overlay))
    config_mgr.on_change(lambda c: classifier.on_config_change(c.employee_detection))
    config_mgr.on_change(lambda c: event_hub.on_config_change(c.event_hub))
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
    args = parse_args(sys.argv[1:])
    main(
        args.config_path,
        video_dir=args.video_dir,
        video_paths=args.video,
        loop_videos=not args.single_pass,
        record_output=args.save_output,
        output_dir=args.output_dir,
    )
