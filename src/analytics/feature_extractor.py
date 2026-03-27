from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.tracking.track import Track


@dataclass
class EmployeeFeatures:
    pre_open_entry_flag: float = 0.0
    first_n_entries_flag: float = 0.0
    repeat_presence_days_norm: float = 0.0
    staff_zone_visit_ratio: float = 0.0
    counter_presence_ratio: float = 0.0
    long_duration_norm: float = 0.0
    reentry_pattern_score: float = 0.0
    uniform_similarity: float = 0.5
    apron_similarity: float = 0.5
    badge_similarity: float = 0.5
    shift_pattern_score: float = 0.0
    customer_similarity: float = 0.5
    shopping_group_likelihood: float = 0.0
    browse_like_score: float = 0.0
    short_visit_score: float = 0.0
    customer_aisle_entropy: float = 0.0


class EmployeeFeatureExtractor:
    def extract(self, track: Track, context: dict[str, Any]) -> EmployeeFeatures:
        duration = track.session_duration_seconds
        clip = track.clip_signals or {}

        return EmployeeFeatures(
            pre_open_entry_flag=float(context.get("pre_open_entry_flag", 0.0)),
            first_n_entries_flag=float(context.get("first_n_entries_flag", 0.0)),
            repeat_presence_days_norm=float(context.get("repeat_presence_days_norm", 0.0)),
            staff_zone_visit_ratio=float(track.derived_features.get("staff_zone_visit_ratio", 0.0)),
            counter_presence_ratio=float(track.derived_features.get("counter_presence_ratio", 0.0)),
            long_duration_norm=min(duration / 14400.0, 1.0),
            reentry_pattern_score=float(track.derived_features.get("reentry_pattern_score", 0.0)),
            uniform_similarity=float(clip.get("uniform_similarity", 0.5)),
            apron_similarity=float(clip.get("apron_similarity", 0.5)),
            badge_similarity=float(clip.get("badge_similarity", 0.5)),
            shift_pattern_score=float(track.derived_features.get("shift_pattern_score", 0.0)),
            customer_similarity=float(clip.get("customer_similarity", 0.5)),
            shopping_group_likelihood=float(track.group_probability),
            browse_like_score=float(track.derived_features.get("browse_like_score", 0.0)),
            short_visit_score=1.0 if duration < 300 else 0.0,
            customer_aisle_entropy=float(track.derived_features.get("customer_aisle_entropy", 0.0)),
        )