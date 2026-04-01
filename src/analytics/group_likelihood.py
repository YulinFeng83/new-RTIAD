from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Any


@dataclass
class GroupDecision:
    probability: float
    should_group: bool
    signals: dict[str, float]


class GroupLikelihoodEngine:
    def __init__(self, threshold: float = 0.72):
        self._threshold = threshold

    def score_pair(self, track_a: Any, track_b: Any) -> GroupDecision:
        signals = self._score_pair_signals(track_a, track_b)
        positive_keys = [
            "entry_time_closeness_score",
            "same_entry_line_flag",
            "proximity_duration_norm",
            "proximity_ratio",
            "velocity_corr",
            "direction_similarity",
            "path_similarity",
            "zone_sequence_similarity",
            "shared_zone_dwell_score",
            "checkout_overlap_score",
        ]
        negative_keys = [
            "employee_customer_role_mismatch",
            "queue_overlap_only_flag",
            "long_split_duration_penalty",
            "divergent_path_score",
        ]

        positive = mean(signals[key] for key in positive_keys)
        negative = mean(signals[key] for key in negative_keys)
        probability = max(
            0.0,
            min(
                1.0,
                (0.8 * positive)
                + (0.2 * signals["entry_time_closeness_score"])
                - (0.45 * negative),
            ),
        )
        return GroupDecision(
            probability=probability,
            should_group=probability >= self._threshold,
            signals=signals,
        )

    def assign_groups(self, tracks: list[Any]) -> dict[int, dict[str, Any]]:
        assignments = {
            track.track_id: {
                "group_id": None,
                "group_probability": 0.0,
                "signals": {},
            }
            for track in tracks
        }
        if len(tracks) < 2:
            return assignments

        parent = {track.track_id: track.track_id for track in tracks}
        pair_decisions: dict[tuple[int, int], GroupDecision] = {}

        def find(track_id: int) -> int:
            while parent[track_id] != track_id:
                parent[track_id] = parent[parent[track_id]]
                track_id = parent[track_id]
            return track_id

        def union(a: int, b: int) -> None:
            ra = find(a)
            rb = find(b)
            if ra != rb:
                parent[rb] = ra

        for index, track_a in enumerate(tracks):
            for track_b in tracks[index + 1:]:
                decision = self.score_pair(track_a, track_b)
                pair_decisions[(track_a.track_id, track_b.track_id)] = decision
                if decision.should_group:
                    union(track_a.track_id, track_b.track_id)

        groups: dict[int, list[Any]] = {}
        for track in tracks:
            groups.setdefault(find(track.track_id), []).append(track)

        for members in groups.values():
            if len(members) < 2:
                continue
            member_ids = sorted(track.track_id for track in members)
            group_id = f"group-{members[0].camera_id}-{'-'.join(str(track_id) for track_id in member_ids)}"
            member_probabilities: list[float] = []
            signal_accumulator: dict[str, list[float]] = {}
            for index, track_a in enumerate(members):
                for track_b in members[index + 1:]:
                    key = (min(track_a.track_id, track_b.track_id), max(track_a.track_id, track_b.track_id))
                    decision = pair_decisions[key]
                    member_probabilities.append(decision.probability)
                    for name, value in decision.signals.items():
                        signal_accumulator.setdefault(name, []).append(value)

            group_probability = sum(member_probabilities) / len(member_probabilities) if member_probabilities else 0.0
            averaged_signals = {
                name: mean(values)
                for name, values in signal_accumulator.items()
            }
            for track in members:
                assignments[track.track_id] = {
                    "group_id": group_id,
                    "group_probability": group_probability,
                    "signals": averaged_signals,
                }

        return assignments

    def _score_pair_signals(self, track_a: Any, track_b: Any) -> dict[str, float]:
        overlap = min(len(track_a.history), len(track_b.history), 20)
        if overlap <= 1 or track_a.current_centroid is None or track_b.current_centroid is None:
            return {name: 0.0 for name in self._signal_names()}

        recent_a = track_a.history[-overlap:]
        recent_b = track_b.history[-overlap:]
        distances = [self._distance(point_a.centroid, point_b.centroid) for point_a, point_b in zip(recent_a, recent_b)]
        close_count = sum(1 for dist in distances if dist < 140.0)
        very_close_count = sum(1 for dist in distances if dist < 90.0)
        avg_distance = sum(distances) / len(distances)

        entry_delta = abs(track_a.first_seen - track_b.first_seen)
        entry_time_closeness = max(0.0, 1.0 - min(entry_delta / 20.0, 1.0))
        same_entry_line = 1.0 if (track_a.entry_count > 0 and track_b.entry_count > 0 and entry_delta <= 8.0) else 0.0

        direction_similarity = self._vector_similarity(
            self._movement_vector(recent_a),
            self._movement_vector(recent_b),
        )
        velocity_corr = self._velocity_similarity(recent_a, recent_b)
        path_similarity = max(0.0, 1.0 - min(avg_distance / 220.0, 1.0))
        zone_sequence_similarity = self._jaccard_similarity(track_a.zones_visited, track_b.zones_visited)
        shared_zone_dwell_score = self._shared_zone_dwell_score(track_a, track_b)
        checkout_overlap_score = min(
            float(track_a.derived_features.get("counter_presence_ratio", 0.0)),
            float(track_b.derived_features.get("counter_presence_ratio", 0.0)),
        )

        role_mismatch = 1.0 if self._role_mismatch(track_a, track_b) else 0.0
        queue_overlap_only = 1.0 if checkout_overlap_score > 0.5 and zone_sequence_similarity < 0.25 and path_similarity < 0.35 else 0.0
        long_split_penalty = 1.0 if entry_time_closeness > 0.7 and avg_distance > 260.0 else 0.0
        divergent_path_score = 1.0 - min(1.0, max(0.0, 0.5 * direction_similarity + 0.5 * path_similarity))

        return {
            "entry_time_closeness_score": entry_time_closeness,
            "same_entry_line_flag": same_entry_line,
            "proximity_duration_norm": min(1.0, very_close_count / max(1, overlap - 1)),
            "proximity_ratio": min(1.0, close_count / max(1, overlap - 1)),
            "velocity_corr": velocity_corr,
            "direction_similarity": direction_similarity,
            "path_similarity": path_similarity,
            "zone_sequence_similarity": zone_sequence_similarity,
            "shared_zone_dwell_score": shared_zone_dwell_score,
            "checkout_overlap_score": checkout_overlap_score,
            "employee_customer_role_mismatch": role_mismatch,
            "queue_overlap_only_flag": queue_overlap_only,
            "long_split_duration_penalty": long_split_penalty,
            "divergent_path_score": divergent_path_score,
        }

    def _signal_names(self) -> list[str]:
        return [
            "entry_time_closeness_score",
            "same_entry_line_flag",
            "proximity_duration_norm",
            "proximity_ratio",
            "velocity_corr",
            "direction_similarity",
            "path_similarity",
            "zone_sequence_similarity",
            "shared_zone_dwell_score",
            "checkout_overlap_score",
            "employee_customer_role_mismatch",
            "queue_overlap_only_flag",
            "long_split_duration_penalty",
            "divergent_path_score",
        ]

    def _movement_vector(self, history: list[Any]) -> tuple[float, float]:
        start = history[0].centroid
        end = history[-1].centroid
        return end[0] - start[0], end[1] - start[1]

    def _velocity_similarity(self, history_a: list[Any], history_b: list[Any]) -> float:
        velocities_a = [self._distance(history_a[i - 1].centroid, history_a[i].centroid) for i in range(1, len(history_a))]
        velocities_b = [self._distance(history_b[i - 1].centroid, history_b[i].centroid) for i in range(1, len(history_b))]
        if not velocities_a or not velocities_b:
            return 0.0

        diffs = [abs(value_a - value_b) for value_a, value_b in zip(velocities_a, velocities_b)]
        avg_diff = sum(diffs) / len(diffs)
        return max(0.0, 1.0 - min(avg_diff / 80.0, 1.0))

    def _shared_zone_dwell_score(self, track_a: Any, track_b: Any) -> float:
        shared_zones = set(track_a.zone_dwell_seconds) & set(track_b.zone_dwell_seconds)
        if not shared_zones:
            return 0.0

        scores: list[float] = []
        for zone_id in shared_zones:
            dwell_a = track_a.zone_dwell_seconds.get(zone_id, 0.0)
            dwell_b = track_b.zone_dwell_seconds.get(zone_id, 0.0)
            if max(dwell_a, dwell_b) <= 0.0:
                continue
            scores.append(min(dwell_a, dwell_b) / max(dwell_a, dwell_b))
        return mean(scores) if scores else 0.0

    def _role_mismatch(self, track_a: Any, track_b: Any) -> bool:
        return (
            track_a.employee_probability >= 0.75 and track_b.customer_probability >= 0.7
        ) or (
            track_b.employee_probability >= 0.75 and track_a.customer_probability >= 0.7
        )

    def _jaccard_similarity(self, seq_a: list[str], seq_b: list[str]) -> float:
        set_a = set(seq_a)
        set_b = set(seq_b)
        if not set_a and not set_b:
            return 0.0
        return len(set_a & set_b) / len(set_a | set_b)

    def _vector_similarity(self, vector_a: tuple[float, float], vector_b: tuple[float, float]) -> float:
        norm_a = (vector_a[0] ** 2 + vector_a[1] ** 2) ** 0.5
        norm_b = (vector_b[0] ** 2 + vector_b[1] ** 2) ** 0.5
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0

        cosine = ((vector_a[0] * vector_b[0]) + (vector_a[1] * vector_b[1])) / (norm_a * norm_b)
        return max(0.0, min(1.0, (cosine + 1.0) / 2.0))

    def _distance(self, point_a: tuple[int, int], point_b: tuple[int, int]) -> float:
        return ((point_a[0] - point_b[0]) ** 2 + (point_a[1] - point_b[1]) ** 2) ** 0.5