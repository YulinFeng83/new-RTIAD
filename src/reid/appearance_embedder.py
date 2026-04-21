from __future__ import annotations

import logging
import threading
from typing import Iterable, Protocol

import numpy as np

from src.config import ReIDConfig
from src.tracking.track import Track

logger = logging.getLogger(__name__)


class AppearanceEmbedder(Protocol):
    model_name: str

    def load(self) -> None:
        ...

    def update_tracks(
        self,
        tracks: Iterable[Track],
        frame: np.ndarray,
        timestamp: float,
    ) -> None:
        ...

    def on_config_change(self, config: ReIDConfig) -> None:
        ...


class OSNetAppearanceEmbedder:
    """OSNet-backed appearance embedding adapter.

    The adapter uses torchreid when it is available. If the runtime does not
    have OSNet/torchreid installed, it leaves tracks without embeddings so the
    cross-camera stitcher safely refuses to link them.
    """

    def __init__(self, config: ReIDConfig, device: str = "cpu"):
        self._config = config
        self._device = device
        self._extractor = None
        self._loaded = False
        self._lock = threading.RLock()
        self.model_name = config.model

    def load(self) -> None:
        with self._lock:
            self._loaded = True
            self.model_name = self._config.model
            if not self._config.enabled:
                logger.info("OSNet appearance embedding disabled")
                return

            try:
                from torchreid.utils import FeatureExtractor  # type: ignore
            except Exception:
                logger.warning(
                    "OSNet appearance embedding requested, but torchreid is not installed; "
                    "cross-camera stitching will skip tracks without embeddings."
                )
                return

            try:
                self._extractor = FeatureExtractor(
                    model_name=self._config.model,
                    model_path=self._config.model_path or "",
                    device=self._device,
                )
                logger.info("Loaded OSNet appearance embedder: %s", self._config.model)
            except Exception:
                logger.exception("Failed to load OSNet appearance embedder")
                self._extractor = None

    def update_tracks(
        self,
        tracks: Iterable[Track],
        frame: np.ndarray,
        timestamp: float,
    ) -> None:
        with self._lock:
            if not self._config.enabled:
                return
            if not self._loaded:
                self.load()
            if self._extractor is None:
                return

            tracks_with_crops: list[tuple[Track, np.ndarray]] = []
            for track in tracks:
                crop = track.crop_from_frame(frame)
                if crop is None or crop.size == 0:
                    continue
                tracks_with_crops.append((track, crop[:, :, ::-1]))

            if not tracks_with_crops:
                return

            try:
                features = self._extractor([crop for _, crop in tracks_with_crops])
            except Exception:
                logger.exception("OSNet embedding extraction failed")
                return

            try:
                feature_array = features.detach().cpu().numpy()
            except AttributeError:
                feature_array = np.asarray(features)

            for (track, _), vector in zip(tracks_with_crops, feature_array):
                embedding = np.asarray(vector, dtype=float).reshape(-1)
                norm = float(np.linalg.norm(embedding))
                if norm <= 0.0:
                    continue
                track.appearance_embedding = (embedding / norm).tolist()
                track.appearance_embedding_updated_at = timestamp
                track.appearance_embedding_model = self._config.model

    def on_config_change(self, config: ReIDConfig) -> None:
        with self._lock:
            should_reload = (
                config.enabled != self._config.enabled
                or config.model != self._config.model
                or config.model_path != self._config.model_path
            )
            self._config = config
            if not should_reload:
                return
            self.model_name = config.model
            self._extractor = None
            self._loaded = False
        self.load()
