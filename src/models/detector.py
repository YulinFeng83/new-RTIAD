"""
YOLOv8 person detector wrapper.

Uses Ultralytics YOLOv8, filtered to COCO class 0 (person) only.
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
from ultralytics import YOLO

from src.config import DetectionConfig

logger = logging.getLogger(__name__)

PERSON_CLASS_ID = 0


class PersonDetector:
    """Thin wrapper around YOLOv8 that returns only person detections."""

    def __init__(self, config: DetectionConfig, device: str = "cpu"):
        self._config = config
        self._device = device
        self._model: Optional[YOLO] = None

    def load(self) -> None:
        logger.info("Loading detection model: %s on %s", self._config.model, self._device)
        self._model = YOLO(self._config.model)
        self._model.to(self._device)
        logger.info("Detection model loaded")

    def detect(self, frame: np.ndarray) -> list[dict]:
        """
        Run detection on a single frame.

        Returns list of dicts:
            [{"bbox": (x1,y1,x2,y2), "confidence": float}, ...]
        """
        if self._model is None:
            raise RuntimeError("Model not loaded. Call load() first.")

        results = self._model.predict(
            frame,
            classes=[PERSON_CLASS_ID],
            conf=self._config.confidence,
            iou=self._config.iou_threshold,
            verbose=False,
        )

        detections = []
        for result in results:
            if result.boxes is None:
                continue
            for box in result.boxes:
                x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().astype(int)
                conf = float(box.conf[0].cpu().numpy())
                detections.append({
                    "bbox": (int(x1), int(y1), int(x2), int(y2)),
                    "confidence": conf,
                })

        return detections
