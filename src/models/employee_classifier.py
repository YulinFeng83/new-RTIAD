"""
Employee/Customer classifier — feature-based likelihood engine.

Runs CLIP appearance scoring, builds session-level features, computes
employee/customer/unknown probabilities, and applies sticky labels.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import numpy as np

from src.analytics.decision_formatter import RoleDecisionFormatter
from src.config import EmployeeDetectionConfig, StrategyConfig
from src.analytics.feature_extractor import EmployeeFeatureExtractor
from src.analytics.likelihood_engine import EmployeeLikelihoodEngine
from src.strategies.base import ClassificationStrategy
from src.strategies.dress_code import DressCodeStrategy
from src.tracking.track import PersonLabel, Track

logger = logging.getLogger(__name__)


class EmployeeClassifier:
    """Feature-based employee/customer classifier with sticky labels."""

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
            logger.warning("Unknown strategy: %s", cfg.name)
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
    ) -> list[dict[str, Any]]:
        """
        Classify a batch of tracks. Modifies tracks in-place.

        Respects sticky labels, classify_every_n_frames, and batch CLIP.
        """
        tracks_to_classify = [
            t for t in tracks
            if self._should_classify(t, frame_id)
        ]

        if not tracks_to_classify:
            return []

        context.setdefault("classification_events", [])
        classification_events: list[dict[str, Any]] = []
        for track in tracks_to_classify:
            previous_label = track.label.value
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
                "pre_open_entry_flag": float(
                    track.derived_features.get("pre_open_entry_flag", context.get("pre_open_entry_flag", 0.0))
                ),
                "first_n_entries_flag": float(
                    track.derived_features.get("first_n_entries_flag", context.get("first_n_entries_flag", 0.0))
                ),
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
            track.max_employee_probability = max(track.max_employee_probability, track.employee_probability)
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
                current_label_probability = self._label_probability(track.label, track)
                new_label_probability = self._label_probability_from_name(new_label, track)
                should_override_sticky = (
                    new_label != track.label.value and
                    new_label_probability >= self._config.threshold
                )

                if current_label_probability < self._config.re_eval_threshold or should_override_sticky:
                    track.label_sticky = False

            if not track.label_sticky or track.label == PersonLabel.UNKNOWN:
                if new_label == "employee":
                    track.label = PersonLabel.EMPLOYEE
                elif new_label == "customer":
                    track.label = PersonLabel.CUSTOMER
                else:
                    track.label = PersonLabel.UNKNOWN

                high_conf = track.label_confidence >= self._config.threshold
                if self._config.sticky_labels and high_conf:
                    track.label_sticky = True

            if previous_label != track.label.value:
                payload = {
                    "track_id": track.track_id,
                    "classification_label": track.label.value,
                    "employee_probability": track.employee_probability,
                    "customer_probability": track.customer_probability,
                    "unknown_probability": track.unknown_probability,
                }
                classification_events.append(payload)
                context["classification_events"].append(payload)

        return classification_events

    def _should_classify(self, track: Track, frame_id: int) -> bool:
        active_staff_zone = float(track.derived_features.get("active_staff_zone", 0.0)) > 0.0
        strong_contradicting_evidence = (
            (track.label == PersonLabel.CUSTOMER and track.employee_probability >= self._config.threshold) or
            (track.label == PersonLabel.EMPLOYEE and track.customer_probability >= self._config.threshold)
        )
        if track.label_sticky and track.label != PersonLabel.UNKNOWN and not active_staff_zone and not strong_contradicting_evidence:
            return False
        frames_since = frame_id - track._last_classified_frame
        return frames_since >= self._config.classify_every_n_frames

    def _label_probability(self, label: PersonLabel, track: Track) -> float:
        if label == PersonLabel.EMPLOYEE:
            return track.employee_probability
        if label == PersonLabel.CUSTOMER:
            return track.customer_probability
        return track.unknown_probability

    def _label_probability_from_name(self, label_name: str, track: Track) -> float:
        if label_name == "employee":
            return track.employee_probability
        if label_name == "customer":
            return track.customer_probability
        return track.unknown_probability

    def on_config_change(self, config: EmployeeDetectionConfig) -> None:
        self._config = config
        for s_cfg in config.strategies:
            for strategy, _ in self._strategies:
                if strategy.name == s_cfg.name:
                    strategy.on_config_change(s_cfg.model_dump())
