"""
Configuration system for RetailVision.

Pydantic models for type-safe config, YAML loader, and file-watcher
for hot-reload on config changes.
"""

from __future__ import annotations

import logging
import re
import threading
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

import yaml
from pydantic import BaseModel, Field
from watchdog.events import FileSystemEventHandler, FileModifiedEvent
from watchdog.observers import Observer

logger = logging.getLogger(__name__)

_VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".m4v", ".wmv"}

# ---------------------------------------------------------------------------
# Pydantic config models
# ---------------------------------------------------------------------------


class SystemConfig(BaseModel):
    fps_target: int = 15
    frame_skip: int = 2
    device: str = "cpu"
    model_precision: str = "fp32"
    log_level: str = "INFO"
    max_duration_seconds: int = 0  # 0 = unlimited
    record_output: bool = False
    output_dir: str = "outputs"


class ZoneConfig(BaseModel):
    id: str
    type: str = "bidirectional"
    polygon: list[list[int]] = Field(default_factory=list)
    direction: list[float] = Field(default_factory=lambda: [0.0, -1.0])
    name: str = ""
    promo_zone_flag: bool = False


class CameraConfig(BaseModel):
    id: str
    url: str = ""
    scene_type: str = "indoor"
    loop: bool = True
    zones: list[ZoneConfig] = Field(default_factory=list)


class DetectionConfig(BaseModel):
    model: str = "yolov8s.pt"
    confidence: float = 0.5
    iou_threshold: float = 0.45
    imgsz: int = 640


class TrackingConfig(BaseModel):
    tracker: str = "bytetrack"
    max_lost_frames: int = 30
    group_rejoin_grace_seconds: int = 180
    exit_confirmation_cooldown_seconds: int = 30
    track_lost_timeout_seconds: int = 120


class DressCodePrompts(BaseModel):
    positive: list[str] = Field(default_factory=list)
    negative: list[str] = Field(default_factory=list)


class StrategyConfig(BaseModel):
    name: str
    enabled: bool = True
    weight: float = 0.0
    model: str = ""
    prompts: Optional[DressCodePrompts] = None
    pre_open_window_minutes: int = 60
    max_first_arrivals: int = 20


class EmployeeDetectionConfig(BaseModel):
    threshold: float = 0.55
    sticky_labels: bool = True
    re_eval_threshold: float = 0.3
    classify_every_n_frames: int = 15
    max_employees: int = 0  # 0 = unlimited
    strategies: list[StrategyConfig] = Field(default_factory=list)


class StoreConfig(BaseModel):
    tenant_id: str = "tenant_1"
    store_id: str = "store_1"
    name: str = "Store Alpha"
    open_time: str = "09:00"
    close_time: str = "21:00"
    promo_zone_ids: list[str] = Field(default_factory=list)


class EventHubConfig(BaseModel):
    enabled: bool = False
    connection_string: str = ""
    event_hub_name: str = ""
    batch_size: int = 10
    send_interval_seconds: int = 5

    def resolve_connection_string(self) -> str:
        """Return env-var override if set, otherwise fall back to YAML value."""
        import os
        return os.getenv("EVENTHUB_CONNECTION_STRING", self.connection_string)


class OverlayColors(BaseModel):
    employee: list[int] = Field(default_factory=lambda: [0, 200, 0])
    customer: list[int] = Field(default_factory=lambda: [200, 100, 0])
    unknown: list[int] = Field(default_factory=lambda: [128, 128, 128])
    entry_zone: list[int] = Field(default_factory=lambda: [0, 200, 0])
    exit_zone: list[int] = Field(default_factory=lambda: [0, 0, 200])
    bidirectional_zone: list[int] = Field(default_factory=lambda: [0, 200, 200])


class OverlayConfig(BaseModel):
    show_bboxes: bool = True
    show_labels: bool = True
    show_zones: bool = True
    show_stats_hud: bool = True
    bbox_thickness: int = 2
    font_scale: float = 0.6
    colors: OverlayColors = Field(default_factory=OverlayColors)


class AppConfig(BaseModel):
    system: SystemConfig = Field(default_factory=SystemConfig)
    cameras: list[CameraConfig] = Field(default_factory=list)
    detection: DetectionConfig = Field(default_factory=DetectionConfig)
    tracking: TrackingConfig = Field(default_factory=TrackingConfig)
    employee_detection: EmployeeDetectionConfig = Field(
        default_factory=EmployeeDetectionConfig
    )
    store: StoreConfig = Field(default_factory=StoreConfig)
    event_hub: EventHubConfig = Field(default_factory=EventHubConfig)
    overlay: OverlayConfig = Field(default_factory=OverlayConfig)


def discover_video_files(video_dir: Path | str) -> list[Path]:
    path = Path(video_dir).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Video directory not found: {path}")
    if not path.is_dir():
        raise NotADirectoryError(f"Video path is not a directory: {path}")

    videos = sorted(p for p in path.iterdir() if p.is_file() and p.suffix.lower() in _VIDEO_EXTENSIONS)
    if not videos:
        raise FileNotFoundError(f"No video files found in {path}")
    return videos


def build_test_video_config(
    base_config: AppConfig,
    video_paths: Iterable[Path | str],
    *,
    loop: bool = True,
    record_output: bool = True,
    output_dir: str = "outputs",
) -> AppConfig:
    cfg = base_config.model_copy(deep=True)
    resolved_paths = [Path(p).resolve() for p in video_paths]
    if not resolved_paths:
        raise ValueError("At least one video path is required")

    cfg.cameras = [
        CameraConfig(
            id=_make_camera_id(path, index),
            url=str(path),
            scene_type=_infer_scene_type(path),
            loop=loop,
            zones=[],
        )
        for index, path in enumerate(resolved_paths, start=1)
    ]
    cfg.event_hub.enabled = False
    cfg.system.max_duration_seconds = 0
    cfg.system.record_output = record_output
    cfg.system.output_dir = output_dir
    return cfg


def _make_camera_id(path: Path, index: int) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", path.stem.lower()).strip("_")
    slug = slug or f"video_{index}"
    return f"cam_{slug}"


def _infer_scene_type(path: Path) -> str:
    name = path.stem.lower()
    outdoor_tokens = ("outdoor", "outside", "exterior", "parking", "street")
    return "outdoor" if any(token in name for token in outdoor_tokens) else "indoor"


# ---------------------------------------------------------------------------
# YAML loader
# ---------------------------------------------------------------------------

_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "default_config.yaml"


def load_config(path: Path | str | None = None) -> AppConfig:
    """Load config from a YAML file. Falls back to default_config.yaml."""
    path = Path(path) if path else _DEFAULT_CONFIG_PATH
    if not path.exists():
        logger.warning("Config file %s not found, using defaults", path)
        return AppConfig()

    with open(path, "r", encoding="utf-8") as f:
        raw: dict[str, Any] = yaml.safe_load(f) or {}

    return AppConfig(**raw)


def save_config(config: AppConfig, path: Path | str | None = None) -> None:
    """Persist config back to YAML (used by zone CRUD, admin UI, etc.)."""
    path = Path(path) if path else _DEFAULT_CONFIG_PATH
    data = config.model_dump(mode="json")
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)
    logger.info("Config saved to %s", path)


# ---------------------------------------------------------------------------
# Hot-reload watcher
# ---------------------------------------------------------------------------


class _ConfigReloadHandler(FileSystemEventHandler):
    """Watches the config YAML and triggers a callback on modification."""

    def __init__(self, config_path: Path, callback: Callable[[AppConfig], None]):
        super().__init__()
        self._config_path = config_path.resolve()
        self._callback = callback

    def on_modified(self, event: FileModifiedEvent) -> None:  # type: ignore[override]
        if Path(event.src_path).resolve() == self._config_path:
            logger.info("Config file changed, reloading…")
            try:
                new_config = load_config(self._config_path)
                self._callback(new_config)
            except Exception:
                logger.exception("Failed to reload config")


class ConfigManager:
    """
    Holds the live config, watches for file changes, and notifies subscribers.

    Usage:
        mgr = ConfigManager("config/default_config.yaml")
        mgr.on_change(lambda cfg: print("new config!", cfg.system.device))
        mgr.start_watching()
        cfg = mgr.config   # always the latest
    """

    def __init__(self, path: Path | str | None = None):
        self._path = Path(path).resolve() if path else _DEFAULT_CONFIG_PATH.resolve()
        self._config = load_config(self._path)
        self._lock = threading.Lock()
        self._callbacks: list[Callable[[AppConfig], None]] = []
        self._observer = None

    @property
    def config(self) -> AppConfig:
        with self._lock:
            return self._config

    def update_config(self, new_config: AppConfig, persist: bool = True) -> None:
        """Programmatically update config (e.g. from API PUT)."""
        with self._lock:
            self._config = new_config
        if persist:
            save_config(new_config, self._path)
        self._notify(new_config)

    def on_change(self, callback: Callable[[AppConfig], None]) -> None:
        self._callbacks.append(callback)

    def start_watching(self) -> None:
        if self._observer is not None:
            return
        handler = _ConfigReloadHandler(self._path, self._on_file_change)
        self._observer = Observer()
        self._observer.schedule(handler, str(self._path.parent), recursive=False)
        self._observer.daemon = True
        self._observer.start()
        logger.info("Watching config file: %s", self._path)

    def stop_watching(self) -> None:
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=2)
            self._observer = None

    def _on_file_change(self, new_config: AppConfig) -> None:
        with self._lock:
            self._config = new_config
        self._notify(new_config)

    def _notify(self, config: AppConfig) -> None:
        for cb in self._callbacks:
            try:
                cb(config)
            except Exception:
                logger.exception("Error in config change callback")
