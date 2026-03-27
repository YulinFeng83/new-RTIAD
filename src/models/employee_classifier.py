"""
Employee/Customer classifier — weighted multi-strategy ensemble.

Orchestrates all classification strategies, combines their scores via
weighted average, applies sticky labels, and manages batch/skip logic.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import numpy as np
from ultralytics import cfg

from src.config import EmployeeDetectionConfig, StrategyConfig
from src.strategies.base import ClassificationStrategy
from src.strategies.dress_code import DressCodeStrategy
#from src.strategies.first_arrival import FirstArrivalStrategy
from src.analytics.feature_extractor import EmployeeFeatureExtractor
from src.analytics.likelihood_engine import EmployeeLikelihoodEngine
from src.analytics.decision_formatter import RoleDecisionFormatter
from src.tracking.track import PersonLabel, Track

logger = logging.getLogger(__name__)


class EmployeeClassifier:
    """
    Weighted ensemble classifier with sticky labels and batch inference.
    """

    def __init__(self, config: EmployeeDetectionConfig, device: str = "cpu", store_open_time: str = "09:00"):
        self._config = config
        self._device = device
        self._strategies: list[tuple[ClassificationStrategy, float]] = []
        self._dress_code: Optional[DressCodeStrategy] = None
        self._feature_extractor = EmployeeFeatureExtractor()
        self._likelihood_engine = EmployeeLikelihoodEngine()
        self._decision_formatter = RoleDecisionFormatter()

        self._build_strategies(config, store_open_time)

    def _build_strategies(self, config: EmployeeDetectionConfig, store_open_time: str) -> None:
        for s_cfg in config.strategies:
            if not s_cfg.enabled:
                continue
            strategy = self._create_strategy(s_cfg, store_open_time)
            if strategy:
                self._strategies.append((strategy, s_cfg.weight))

    # def _create_strategy(self, cfg: StrategyConfig, store_open_time: str) -> Optional[ClassificationStrategy]:
    #     if cfg.name == "dress_code":
    #         s = DressCodeStrategy(
    #             model_name=cfg.model or "openai/clip-vit-base-patch32",
    #             positive_prompts=cfg.prompts.positive if cfg.prompts else None,
    #             negative_prompts=cfg.prompts.negative if cfg.prompts else None,
    #             device=self._device,
    #         )
    #         self._dress_code = s
    #         return s
    #     elif cfg.name == "first_arrival":
    #         return FirstArrivalStrategy(
    #             store_open_time=store_open_time,
    #             pre_open_window_minutes=cfg.pre_open_window_minutes,
    #             max_first_arrivals=cfg.max_first_arrivals,
    #         )
    #     else:
    #         logger.warning("Unknown strategy: %s", cfg.name)
    #         return None
    def _create_strategy(self, cfg: StrategyConfig, store_open_time: str) -> Optional[ClassificationStrategy]:
        if cfg.name == "dress_code":
            s = DressCodeStrategy(
                model_name=cfg.model or "openai/clip-vit-base-patch32",
                positive_prompts=cfg.prompts.positive if cfg.prompts else None,
                negative_prompts=cfg.prompts.negative if cfg.prompts else None,
                device=self._device,
            )
            self._dress_code = s
            return s
        else:
            logger.warning("Unknown or unused strategy: %s", cfg.name)
            return None

    def load(self) -> None:
        """Initialize all strategies (load models, etc.)."""
        for strategy, _ in self._strategies:
            strategy.initialize()

    def classify_tracks(
        self,
        tracks: list[Track],
        frame: np.ndarray,
        frame_id: int,
        context: dict[str, Any],
    ) -> None:
        """
        Classify a batch of tracks. Modifies tracks in-place.

        Respects sticky labels, classify_every_n_frames, and batch CLIP.
        """
        tracks_to_classify = [
            t for t in tracks
            if self._should_classify(t, frame_id)
        ]

        if not tracks_to_classify:
            return

        # crops = []
        # crop_indices = []
        # for i, track in enumerate(tracks_to_classify):
        #     crop = track.crop_from_frame(frame)
        #     if crop is not None and crop.size > 0:
        #         crops.append(crop)
        #         crop_indices.append(i)

        # clip_scores: list[float] = []
        # if self._dress_code and crops:
        #     clip_scores = self._dress_code.score_batch(crops)

        # clip_score_map: dict[int, float] = {}
        # for idx, score in zip(crop_indices, clip_scores):
        #     clip_score_map[idx] = score

        # scored_tracks: list[tuple[Track, float, dict[str, float]]] = []

        # for i, track in enumerate(tracks_to_classify):
        #     strategy_scores: dict[str, float] = {}
        #     weighted_sum = 0.0
        #     total_weight = 0.0

        #     for strategy, weight in self._strategies:
        #         if strategy.name == "dress_code":
        #             s = clip_score_map.get(i, 0.5)
        #         else:
        #             crop = track.crop_from_frame(frame)
        #             s = strategy.score(crop, track, context)

        #         strategy_scores[strategy.name] = s
        #         weighted_sum += s * weight
        #         total_weight += weight

        #     combined = weighted_sum / total_weight if total_weight > 0 else 0.5
        #     scored_tracks.append((track, combined, strategy_scores))

        # # Count already-sticky employees not in this batch
        # existing_employees = sum(
        #     1 for t in tracks
        #     if t.label == PersonLabel.EMPLOYEE
        #     and t.label_sticky
        #     and t not in tracks_to_classify
        # )
        # max_emp = self._config.max_employees
        # remaining_slots = max(0, max_emp - existing_employees) if max_emp > 0 else len(scored_tracks)

        # # Sort candidates by score descending so highest-scoring get employee slots
        # scored_tracks.sort(key=lambda x: x[1], reverse=True)

        # for track, combined, strategy_scores in scored_tracks:
        #     track.label_strategy_scores = strategy_scores
        #     track.label_confidence = combined
        #     track._last_classified_frame = frame_id

        #     if combined >= self._config.threshold and remaining_slots > 0:
        #         new_label = PersonLabel.EMPLOYEE
        #         remaining_slots -= 1
        #     else:
        #         new_label = PersonLabel.CUSTOMER

        #     logger.info(
        #         "Track %d: scores=%s combined=%.3f → %s",
        #         track.track_id, strategy_scores, combined, new_label.value,
        #     )

        #     if track.label_sticky and track.label != PersonLabel.UNKNOWN:
        #         if track.label_confidence < self._config.re_eval_threshold:
        #             track.label_sticky = False
        #             track.label = new_label
        #     else:
        #         track.label = new_label
        #         high_conf = abs(combined - 0.5) > 0.15
        #         if self._config.sticky_labels and high_conf:
        #             track.label_sticky = True
        # for i, track in enumerate(tracks_to_classify):
        for track in tracks_to_classify:
            track._last_classified_frame = frame_id

            crop = track.crop_from_frame(frame)
            clip_signals = (
                self._dress_code.score_signals(crop)
                if self._dress_code and crop is not None and crop.size > 0
                else {
                    "uniform_similarity": 0.5,
                    "apron_similarity": 0.5,
                    "badge_similarity": 0.5,
                    "customer_similarity": 0.5,
                }
            )
            track.clip_signals = clip_signals

            feature_context = {
                "pre_open_entry_flag": float(context.get("pre_open_entry_flag", 0.0)),
                "first_n_entries_flag": float(context.get("first_n_entries_flag", 0.0)),
                "repeat_presence_days_norm": float(
                    track.derived_features.get("repeat_presence_days_norm", 0.0)
                ),
            }

            features = self._feature_extractor.extract(track, feature_context)
            probs = self._likelihood_engine.score(features)
            decision = self._decision_formatter.format(track.track_id, features, probs)

            track.employee_probability = decision["employee_probability"]
            track.customer_probability = decision["customer_probability"]
            track.unknown_probability = decision["unknown_probability"]
            track.decision_reasons = decision["top_signals"]
            track.derived_features["reason_summary"] = decision["reason_summary"]
            track.label_confidence = max(
                track.employee_probability,
                track.customer_probability,
                track.unknown_probability,
            )
            track.label_strategy_scores = clip_signals

            new_label = decision["role_label"]
            logger.info(
                "Track %d: clip=%s probs=(emp=%.3f cust=%.3f unk=%.3f) → %s",
                track.track_id,
                clip_signals,
                track.employee_probability,
                track.customer_probability,
                track.unknown_probability,
                new_label,
            )

            if track.label_sticky and track.label != PersonLabel.UNKNOWN:
                if track.label_confidence < self._config.re_eval_threshold:
                    track.label_sticky = False
            else:
                if new_label == "employee":
                    track.label = PersonLabel.EMPLOYEE
                elif new_label == "customer":
                    track.label = PersonLabel.CUSTOMER
                else:
                    track.label = PersonLabel.UNKNOWN

                high_conf = track.label_confidence >= self._config.threshold
                if self._config.sticky_labels and high_conf:
                    track.label_sticky = True

    def _should_classify(self, track: Track, frame_id: int) -> bool:
        if track.label_sticky and track.label != PersonLabel.UNKNOWN:
            return False
        frames_since = frame_id - track._last_classified_frame
        return frames_since >= self._config.classify_every_n_frames

    def on_config_change(self, config: EmployeeDetectionConfig) -> None:
        self._config = config
        for s_cfg in config.strategies:
            for strategy, _ in self._strategies:
                if strategy.name == s_cfg.name:
                    strategy.on_config_change(s_cfg.model_dump())
