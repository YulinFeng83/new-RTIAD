from __future__ import annotations


class GroupLikelihoodEngine:
    def score_pair(self, track_a, track_b) -> float:
        if track_a.current_centroid is None or track_b.current_centroid is None:
            return 0.0

        ax, ay = track_a.current_centroid
        bx, by = track_b.current_centroid
        dist = ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5

        if dist < 100:
            return 0.7
        if dist < 180:
            return 0.4
        return 0.0