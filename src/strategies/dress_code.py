"""
CLIP zero-shot dress code classification strategy.

Uses CLIP ViT-B/32 to compare person crops against configurable text
prompts (positive = employee, negative = customer). Text embeddings
are pre-computed and cached; only the image encoder runs per frame.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import numpy as np
import torch
from PIL import Image
from transformers import CLIPModel, CLIPProcessor

from src.strategies.base import ClassificationStrategy
from src.tracking.track import Track

logger = logging.getLogger(__name__)


class DressCodeStrategy(ClassificationStrategy):

    def __init__(
        self,
        model_name: str = "openai/clip-vit-base-patch32",
        positive_prompts: list[str] | None = None,
        negative_prompts: list[str] | None = None,
        device: str = "cpu",
    ):
        self._model_name = model_name
        self._positive_prompts = positive_prompts or ["person wearing store uniform"]
        self._negative_prompts = negative_prompts or ["person in casual clothes"]
        self._device = device

        self._model: Optional[CLIPModel] = None
        self._processor: Optional[CLIPProcessor] = None
        self._text_embeds: Optional[torch.Tensor] = None
        self._n_positive: int = 0

    @property
    def name(self) -> str:
        return "dress_code"

    def initialize(self) -> None:
        logger.info("Loading CLIP model: %s on %s", self._model_name, self._device)
        self._processor = CLIPProcessor.from_pretrained(self._model_name)
        self._model = CLIPModel.from_pretrained(self._model_name).to(self._device)
        self._model.eval()
        self._precompute_text_embeddings()
        logger.info("CLIP model ready")

    def _precompute_text_embeddings(self) -> None:
        """Encode all text prompts once. Re-run on prompt change."""
        all_prompts = self._positive_prompts + self._negative_prompts
        self._n_positive = len(self._positive_prompts)

        inputs = self._processor(text=all_prompts, return_tensors="pt", padding=True)
        inputs = {k: v.to(self._device) for k, v in inputs.items()}

        with torch.no_grad():
            self._text_embeds = self._model.get_text_features(**inputs)
            if not isinstance(self._text_embeds, torch.Tensor):
                if hasattr(self._text_embeds, "text_embeds"):
                    self._text_embeds = self._text_embeds.text_embeds
                elif hasattr(self._text_embeds, "pooler_output") and hasattr(self._model, "text_projection"):
                    pooled = self._text_embeds.pooler_output
                    projection = self._model.text_projection
                    if pooled.shape[-1] == projection.in_features:
                        self._text_embeds = projection(pooled)
                    else:
                        self._text_embeds = pooled
                else:
                    raise TypeError("Unsupported output type from CLIP text encoder")
            self._text_embeds = self._text_embeds / self._text_embeds.norm(dim=-1, keepdim=True)

        logger.info(
            "Pre-computed text embeddings: %d positive, %d negative",
            self._n_positive,
            len(self._negative_prompts),
        )

    def score(
        self,
        crop: Optional[np.ndarray],
        track: Track,
        context: dict[str, Any],
    ) -> float:
        if crop is None or self._model is None or self._processor is None:
            return 0.5

        return self._score_single(crop)

    def score_batch(self, crops: list[np.ndarray]) -> list[float]:
        """Batch-score multiple person crops in a single forward pass."""
        if not crops or self._model is None or self._processor is None:
            return [0.5] * len(crops)

        pil_images = [Image.fromarray(cv2_to_rgb(c)) for c in crops]
        inputs = self._processor(images=pil_images, return_tensors="pt", padding=True)
        inputs = {k: v.to(self._device) for k, v in inputs.items()}

        with torch.no_grad():
            image_embeds = self._model.get_image_features(**inputs)
            if not isinstance(image_embeds, torch.Tensor):
                if hasattr(image_embeds, "image_embeds"):
                    image_embeds = image_embeds.image_embeds
                elif hasattr(image_embeds, "pooler_output") and hasattr(self._model, "visual_projection"):
                    pooled = image_embeds.pooler_output
                    projection = self._model.visual_projection
                    if pooled.shape[-1] == projection.in_features:
                        image_embeds = projection(pooled)
                    else:
                        image_embeds = pooled
                else:
                    raise TypeError("Unsupported output type from CLIP image encoder")
            image_embeds = image_embeds / image_embeds.norm(dim=-1, keepdim=True)

            logit_scale = self._model.logit_scale.exp()
            logits = (image_embeds @ self._text_embeds.T) * logit_scale  # (B, N_prompts)

        scores = []
        for i in range(logits.shape[0]):
            probs = torch.softmax(logits[i], dim=0).cpu().numpy()
            employee_score = float(probs[: self._n_positive].sum())
            scores.append(max(0.0, min(1.0, employee_score)))

        return scores

    def _score_single(self, crop: np.ndarray) -> float:
        return self.score_batch([crop])[0]
    
    def score_signals(self, crop: Optional[np.ndarray]) -> dict[str, float]:
        if crop is None or self._model is None or self._processor is None:
            return {
                "uniform_similarity": 0.5,
                "apron_similarity": 0.5,
                "badge_similarity": 0.5,
                "customer_similarity": 0.5,
            }

        employee_score = self._score_single(crop)
        customer_score = 1.0 - employee_score

        return {
            "uniform_similarity": employee_score,
            "apron_similarity": employee_score,
            "badge_similarity": employee_score,
            "customer_similarity": customer_score,
        }

    def on_config_change(self, strategy_config: dict) -> None:
        prompts = strategy_config.get("prompts", {})
        new_pos = prompts.get("positive", self._positive_prompts)
        new_neg = prompts.get("negative", self._negative_prompts)

        if new_pos != self._positive_prompts or new_neg != self._negative_prompts:
            self._positive_prompts = new_pos
            self._negative_prompts = new_neg
            logger.info("Dress code prompts changed, recomputing text embeddings")
            self._precompute_text_embeddings()


def cv2_to_rgb(img: np.ndarray) -> np.ndarray:
    """Convert BGR (OpenCV) to RGB."""
    return img[:, :, ::-1]
