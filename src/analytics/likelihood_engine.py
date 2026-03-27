from __future__ import annotations

import math
from dataclasses import dataclass

from src.analytics.feature_extractor import EmployeeFeatures


@dataclass
class RoleWeights:
    pre_open_entry_flag: float = 2.5
    first_n_entries_flag: float = 1.8
    repeat_presence_days_norm: float = 2.2
    staff_zone_visit_ratio: float = 3.0
    counter_presence_ratio: float = 2.1
    long_duration_norm: float = 1.6
    reentry_pattern_score: float = 1.2
    uniform_similarity: float = 1.3
    apron_similarity: float = 1.0
    badge_similarity: float = 0.8
    shift_pattern_score: float = 1.7
    customer_similarity: float = -1.6
    shopping_group_likelihood: float = -1.2
    browse_like_score: float = -1.8
    short_visit_score: float = -1.4
    customer_aisle_entropy: float = -1.3


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


class EmployeeLikelihoodEngine:
    def __init__(self, weights: RoleWeights | None = None):
        self.weights = weights or RoleWeights()

    def score(self, features: EmployeeFeatures) -> dict:
        w = self.weights
        logit = (
            w.pre_open_entry_flag * features.pre_open_entry_flag +
            w.first_n_entries_flag * features.first_n_entries_flag +
            w.repeat_presence_days_norm * features.repeat_presence_days_norm +
            w.staff_zone_visit_ratio * features.staff_zone_visit_ratio +
            w.counter_presence_ratio * features.counter_presence_ratio +
            w.long_duration_norm * features.long_duration_norm +
            w.reentry_pattern_score * features.reentry_pattern_score +
            w.uniform_similarity * features.uniform_similarity +
            w.apron_similarity * features.apron_similarity +
            w.badge_similarity * features.badge_similarity +
            w.shift_pattern_score * features.shift_pattern_score +
            w.customer_similarity * features.customer_similarity +
            w.shopping_group_likelihood * features.shopping_group_likelihood +
            w.browse_like_score * features.browse_like_score +
            w.short_visit_score * features.short_visit_score +
            w.customer_aisle_entropy * features.customer_aisle_entropy
        )

        employee_probability = sigmoid(logit)

        margin = abs(employee_probability - 0.5)
        if margin < 0.10:
            unknown_probability = 1.0 - (margin * 2.0)
        else:
            unknown_probability = 0.0

        unknown_probability = max(0.0, min(1.0, unknown_probability))
        customer_probability = max(0.0, 1.0 - employee_probability - unknown_probability)

        total = employee_probability + customer_probability + unknown_probability
        employee_probability /= total
        customer_probability /= total
        unknown_probability /= total

        return {
            "employee_probability": employee_probability,
            "customer_probability": customer_probability,
            "unknown_probability": unknown_probability,
            "logit": logit,
        }