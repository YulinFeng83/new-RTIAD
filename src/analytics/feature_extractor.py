from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from src.tracking.track import Track


@dataclass
class EmployeeFeatures:
    pre_open_entry_flag: float = 0.0
    first_n_entries_flag: float = 0.0
    repeat_presence_days_norm: float = 0.0
    staff_zone_visit_ratio: float = 0.0
    staff_zone_dwell_ratio: float = 0.0
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
        repeat_presence_days_norm = float(
            track.derived_features.get(
                "repeat_presence_days_norm",
                min(1.0, max(0.0, (sum(track.zone_visit_counts.values()) - len(set(track.zones_visited))) / 3.0)),
            )
        )
        browse_like_score = float(
            track.derived_features.get(
                "browse_like_score",
                self._browse_like_score(track, duration),
            )
        )
        customer_aisle_entropy = float(
            track.derived_features.get(
                "customer_aisle_entropy",
                self._customer_aisle_entropy(track),
            )
        )
        shift_pattern_score = float(
            track.derived_features.get(
                "shift_pattern_score",
                self._shift_pattern_score(track, context, duration),
            )
        )

        return EmployeeFeatures(
            pre_open_entry_flag=float(context.get("pre_open_entry_flag", track.derived_features.get("pre_open_entry_flag", 0.0))),
            first_n_entries_flag=float(context.get("first_n_entries_flag", track.derived_features.get("first_n_entries_flag", 0.0))),
            repeat_presence_days_norm=repeat_presence_days_norm,
            staff_zone_visit_ratio=float(track.derived_features.get("staff_zone_visit_ratio", 0.0)),
            staff_zone_dwell_ratio=float(track.derived_features.get("staff_zone_dwell_ratio", 0.0)),
            counter_presence_ratio=float(track.derived_features.get("counter_presence_ratio", 0.0)),
            long_duration_norm=min(duration / 14400.0, 1.0),
            reentry_pattern_score=float(track.derived_features.get("reentry_pattern_score", 0.0)),
            uniform_similarity=float(clip.get("uniform_similarity", 0.5)),
            apron_similarity=float(clip.get("apron_similarity", 0.5)),
            badge_similarity=float(clip.get("badge_similarity", 0.5)),
            shift_pattern_score=shift_pattern_score,
            customer_similarity=float(clip.get("customer_similarity", 0.5)),
            shopping_group_likelihood=float(track.group_probability),
            browse_like_score=browse_like_score,
            short_visit_score=1.0 if duration < 300 else 0.0,
            customer_aisle_entropy=customer_aisle_entropy,
        )

    def _shift_pattern_score(self, track: Track, context: dict[str, Any], duration: float) -> float:
        pre_open = float(context.get("pre_open_entry_flag", track.derived_features.get("pre_open_entry_flag", 0.0)))
        long_duration = min(duration / 14400.0, 1.0)
        staff_ratio = float(track.derived_features.get("staff_zone_visit_ratio", 0.0))
        counter_ratio = float(track.derived_features.get("counter_presence_ratio", 0.0))
        return min(1.0, 0.35 * pre_open + 0.35 * long_duration + 0.2 * staff_ratio + 0.1 * counter_ratio)

    def _browse_like_score(self, track: Track, duration: float) -> float:
        zone_count = len(track.zone_visit_counts)
        low_counter = 1.0 - float(track.derived_features.get("counter_presence_ratio", 0.0))
        entropy = self._customer_aisle_entropy(track)
        shortish = max(0.0, 1.0 - min(duration / 1800.0, 1.0))
        return min(1.0, 0.4 * min(zone_count / 4.0, 1.0) + 0.35 * entropy + 0.25 * low_counter * shortish)

    def _customer_aisle_entropy(self, track: Track) -> float:
        visit_counts = [count for zone_id, count in track.zone_visit_counts.items() if "staff" not in zone_id.lower()]
        total = sum(visit_counts)
        if total <= 0 or len(visit_counts) <= 1:
            return 0.0

        entropy = 0.0
        for count in visit_counts:
            p = count / total
            entropy -= p * math.log(p)
        return min(1.0, entropy / math.log(len(visit_counts)))