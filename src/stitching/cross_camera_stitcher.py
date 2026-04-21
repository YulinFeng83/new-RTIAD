from __future__ import annotations

import logging
import math
import threading
from dataclasses import dataclass
from typing import Iterable

from src.config import SpatialConfig
from src.sessions.visit_session_manager import VisitSessionManager
from src.tracking.track import Track

logger = logging.getLogger(__name__)


@dataclass
class LostTrackCandidate:
    store_visit_id: str
    camera_id: str
    track_id: int
    last_seen_at: float
    group_id: str | None
    appearance_embedding: list[float]
    appearance_embedding_model: str | None
    floor_x: float | None = None
    floor_y: float | None = None


@dataclass
class ActiveTrackCandidate:
    store_visit_id: str | None
    camera_id: str
    track_id: int
    observed_at: float
    group_id: str | None
    appearance_embedding: list[float]
    appearance_embedding_model: str | None
    floor_x: float | None = None
    floor_y: float | None = None


@dataclass
class StitchScore:
    candidate: LostTrackCandidate
    total: float
    osnet_similarity: float
    spatial_prior: float
    temporal_score: float
    floor_score: float | None = None
    floor_distance_meters: float | None = None


class CrossCameraStitcher:
    """Stage 1 spatial-config stitcher using OSNet appearance embeddings."""

    def __init__(
        self,
        spatial_config: SpatialConfig,
        visit_session_manager: VisitSessionManager,
        temporal_gate_seconds: float = 30.0,
        appearance_threshold: float = 0.78,
        min_score: float = 0.80,
        ambiguity_margin: float = 0.08,
    ):
        self._spatial_config = spatial_config
        self._visit_sessions = visit_session_manager
        self._temporal_gate_seconds = temporal_gate_seconds
        self._appearance_threshold = appearance_threshold
        self._min_score = min_score
        self._ambiguity_margin = ambiguity_margin
        self._lost: dict[tuple[str, int], LostTrackCandidate] = {}
        self._active: dict[tuple[str, int], ActiveTrackCandidate] = {}
        self._lock = threading.RLock()

    def on_config_change(self, spatial_config: SpatialConfig) -> None:
        with self._lock:
            self._spatial_config = spatial_config

    def on_reid_settings_change(
        self,
        temporal_gate_seconds: float,
        appearance_threshold: float,
        min_score: float,
        ambiguity_margin: float,
    ) -> None:
        with self._lock:
            self._temporal_gate_seconds = temporal_gate_seconds
            self._appearance_threshold = appearance_threshold
            self._min_score = min_score
            self._ambiguity_margin = ambiguity_margin

    def remember_lost_tracks(
        self,
        camera_id: str,
        tracks: Iterable[Track],
    ) -> None:
        with self._lock:
            for track in tracks:
                visit = self._visit_sessions.active_visit_for_track(camera_id, track.track_id)
                if visit is None:
                    continue
                if not track.appearance_embedding:
                    logger.debug(
                        "[%s] Not caching lost track %d for stitching: missing OSNet embedding",
                        camera_id,
                        track.track_id,
                    )
                    continue
                self._lost[(camera_id, track.track_id)] = LostTrackCandidate(
                    store_visit_id=visit.store_visit_id,
                    camera_id=camera_id,
                    track_id=track.track_id,
                    last_seen_at=track.last_seen,
                    group_id=track.group_id,
                    appearance_embedding=list(track.appearance_embedding),
                    appearance_embedding_model=track.appearance_embedding_model,
                    floor_x=self._track_floor_x(track),
                    floor_y=self._track_floor_y(track),
                )

    def try_link_new_tracks(
        self,
        camera_id: str,
        tracks: Iterable[Track],
        timestamp: float,
        group_visitor_count: int = 1,
    ) -> None:
        with self._lock:
            self._prune(timestamp)
            consumed: set[tuple[str, int]] = set()
            active_tracks = list(tracks)
            for track in active_tracks:
                if self._visit_sessions.active_visit_for_track(camera_id, track.track_id) is not None:
                    continue
                overlap_match = self._best_overlap_candidate(camera_id, track, timestamp, consumed)
                if overlap_match is not None:
                    candidate = overlap_match.candidate
                    if candidate.store_visit_id is not None:
                        visit = self._visit_sessions.link_segment(
                            candidate.store_visit_id,
                            camera_id,
                            track,
                            timestamp,
                            group_visitor_count=group_visitor_count,
                        )
                        if visit is not None:
                            consumed.add((candidate.camera_id, candidate.track_id))
                            logger.info(
                                "Overlap-stitched track %s:%d -> visit %s from active %s:%d "
                                "score=%.3f osnet=%.3f spatial=%.3f temporal=%.3f floor_dist=%.3f",
                                camera_id,
                                track.track_id,
                                visit.store_visit_id,
                                candidate.camera_id,
                                candidate.track_id,
                                overlap_match.total,
                                overlap_match.osnet_similarity,
                                overlap_match.spatial_prior,
                                overlap_match.temporal_score,
                                -1.0 if overlap_match.floor_distance_meters is None else overlap_match.floor_distance_meters,
                            )
                            continue
                match = self._best_candidate(camera_id, track, timestamp, consumed)
                if match is None:
                    continue
                candidate = match.candidate
                visit = self._visit_sessions.link_segment(
                    candidate.store_visit_id,
                    camera_id,
                    track,
                    timestamp,
                    group_visitor_count=group_visitor_count,
                )
                if visit is None:
                    continue
                key = (candidate.camera_id, candidate.track_id)
                consumed.add(key)
                self._lost.pop(key, None)
                logger.info(
                    "Stitched track %s:%d -> visit %s from %s:%d "
                    "score=%.3f osnet=%.3f spatial=%.3f temporal=%.3f floor_dist=%.3f",
                    camera_id,
                    track.track_id,
                    visit.store_visit_id,
                    candidate.camera_id,
                    candidate.track_id,
                    match.total,
                    match.osnet_similarity,
                    match.spatial_prior,
                    match.temporal_score,
                    -1.0 if match.floor_distance_meters is None else match.floor_distance_meters,
                )
            self._remember_active_tracks(camera_id, active_tracks, timestamp)

    def _best_candidate(
        self,
        camera_id: str,
        track: Track,
        timestamp: float,
        consumed: set[tuple[str, int]],
    ) -> StitchScore | None:
        if not track.appearance_embedding:
            return None

        scored: list[StitchScore] = []
        for key, candidate in self._lost.items():
            if key in consumed:
                continue
            if candidate.camera_id == camera_id:
                continue

            spatial_prior = self._spatial_prior(candidate.camera_id, camera_id)
            if spatial_prior is None:
                continue

            gap = timestamp - candidate.last_seen_at
            if gap < 0 or gap > self._temporal_gate_seconds:
                continue

            osnet_similarity = self._cosine_similarity(
                candidate.appearance_embedding,
                track.appearance_embedding,
            )
            if osnet_similarity < self._appearance_threshold:
                continue

            temporal_score = 1.0 - min(gap / self._temporal_gate_seconds, 1.0)
            floor_score, floor_distance = self._floor_signal(
                source_floor_x=candidate.floor_x,
                source_floor_y=candidate.floor_y,
                target_floor_x=self._track_floor_x(track),
                target_floor_y=self._track_floor_y(track),
                relation="adjacent_handoff",
            )
            total = (
                0.60 * osnet_similarity
                + 0.25 * spatial_prior
                + 0.15 * temporal_score
            )
            if floor_score is not None:
                total += 0.08 * floor_score
                total -= 0.08
            if total < self._min_score:
                continue

            scored.append(StitchScore(
                candidate=candidate,
                total=total,
                osnet_similarity=osnet_similarity,
                spatial_prior=spatial_prior,
                temporal_score=temporal_score,
                floor_score=floor_score,
                floor_distance_meters=floor_distance,
            ))

        if not scored:
            return None

        scored.sort(key=lambda item: item.total, reverse=True)
        if len(scored) > 1 and scored[0].total - scored[1].total < self._ambiguity_margin:
            logger.info(
                "[%s] Skipping stitch for track %d: ambiguous best scores %.3f vs %.3f",
                camera_id,
                track.track_id,
                scored[0].total,
                scored[1].total,
            )
            return None
        return scored[0]

    def _best_overlap_candidate(
        self,
        camera_id: str,
        track: Track,
        timestamp: float,
        consumed: set[tuple[str, int]],
    ) -> StitchScore | None:
        if not track.appearance_embedding:
            return None

        scored: list[StitchScore] = []
        fresh_window = min(2.0, self._temporal_gate_seconds)
        for key, candidate in self._active.items():
            if key in consumed:
                continue
            if candidate.camera_id == camera_id:
                continue
            if candidate.store_visit_id is None:
                continue
            if not self._has_confirmed_overlap(candidate.camera_id, camera_id):
                continue

            freshness_gap = abs(timestamp - candidate.observed_at)
            if freshness_gap > fresh_window:
                continue

            osnet_similarity = self._cosine_similarity(
                candidate.appearance_embedding,
                track.appearance_embedding,
            )
            if osnet_similarity < self._appearance_threshold:
                continue

            temporal_score = 1.0 - min(freshness_gap / fresh_window, 1.0)
            spatial_prior = 1.0
            floor_score, floor_distance = self._floor_signal(
                source_floor_x=candidate.floor_x,
                source_floor_y=candidate.floor_y,
                target_floor_x=self._track_floor_x(track),
                target_floor_y=self._track_floor_y(track),
                relation="overlap_active",
            )
            total = (
                0.75 * osnet_similarity
                + 0.15 * temporal_score
                + 0.10 * spatial_prior
            )
            if floor_score is not None:
                total += 0.10 * floor_score
                total -= 0.10
            if total < self._min_score:
                continue

            scored.append(StitchScore(
                candidate=LostTrackCandidate(
                    store_visit_id=candidate.store_visit_id,
                    camera_id=candidate.camera_id,
                    track_id=candidate.track_id,
                    last_seen_at=candidate.observed_at,
                    group_id=candidate.group_id,
                    appearance_embedding=candidate.appearance_embedding,
                    appearance_embedding_model=candidate.appearance_embedding_model,
                    floor_x=candidate.floor_x,
                    floor_y=candidate.floor_y,
                ),
                total=total,
                osnet_similarity=osnet_similarity,
                spatial_prior=spatial_prior,
                temporal_score=temporal_score,
                floor_score=floor_score,
                floor_distance_meters=floor_distance,
            ))

        if not scored:
            return None

        scored.sort(key=lambda item: item.total, reverse=True)
        if len(scored) > 1 and scored[0].total - scored[1].total < self._ambiguity_margin:
            logger.info(
                "[%s] Skipping overlap stitch for track %d: ambiguous best scores %.3f vs %.3f",
                camera_id,
                track.track_id,
                scored[0].total,
                scored[1].total,
            )
            return None
        return scored[0]

    def _spatial_prior(self, camera_a_id: str, camera_b_id: str) -> float | None:
        if self._has_confirmed_overlap(camera_a_id, camera_b_id):
            return 1.0
        adjacency_distance = self._adjacency_distance_meters(camera_a_id, camera_b_id)
        if adjacency_distance is not None:
            # Stage 1 blueprint coordinates are approximate, so keep adjacency as
            # the hard gate and use floor distance only to rank plausible handoffs.
            return max(0.35, 1.0 - min(adjacency_distance / 12.0, 1.0))
        return None

    def _has_confirmed_overlap(self, camera_a_id: str, camera_b_id: str) -> bool:
        for overlap in self._spatial_config.camera_overlaps:
            if not overlap.confirmed_overlap:
                continue
            if {overlap.camera_a_id, overlap.camera_b_id} == {camera_a_id, camera_b_id}:
                return True
        return False

    def _adjacency_distance_meters(self, camera_a_id: str, camera_b_id: str) -> float | None:
        for edge in self._spatial_config.camera_adjacency:
            if {edge.camera_a_id, edge.camera_b_id} == {camera_a_id, camera_b_id}:
                if edge.distance_meters is not None:
                    return edge.distance_meters
                floor_distance = self._camera_floor_distance_meters(camera_a_id, camera_b_id)
                if floor_distance is not None:
                    return floor_distance
                return 6.0
        return None

    def _camera_floor_distance_meters(self, camera_a_id: str, camera_b_id: str) -> float | None:
        camera_positions = {
            camera.camera_id: (camera.floor_x, camera.floor_y)
            for camera in self._spatial_config.camera_arrangement
        }
        pos_a = camera_positions.get(camera_a_id)
        pos_b = camera_positions.get(camera_b_id)
        if pos_a is None or pos_b is None:
            return None
        if pos_a[0] is None or pos_a[1] is None or pos_b[0] is None or pos_b[1] is None:
            return None
        return math.sqrt((pos_a[0] - pos_b[0]) ** 2 + (pos_a[1] - pos_b[1]) ** 2)

    def _cosine_similarity(self, a: list[float], b: list[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(y * y for y in b))
        if norm_a <= 0.0 or norm_b <= 0.0:
            return 0.0
        return dot / (norm_a * norm_b)

    def _remember_active_tracks(
        self,
        camera_id: str,
        tracks: Iterable[Track],
        timestamp: float,
    ) -> None:
        current_keys: set[tuple[str, int]] = set()
        for track in tracks:
            if not track.appearance_embedding:
                continue
            key = (camera_id, track.track_id)
            current_keys.add(key)
            visit = self._visit_sessions.active_visit_for_track(camera_id, track.track_id)
            self._active[key] = ActiveTrackCandidate(
                store_visit_id=None if visit is None else visit.store_visit_id,
                camera_id=camera_id,
                track_id=track.track_id,
                observed_at=timestamp,
                group_id=track.group_id,
                appearance_embedding=list(track.appearance_embedding),
                appearance_embedding_model=track.appearance_embedding_model,
                floor_x=self._track_floor_x(track),
                floor_y=self._track_floor_y(track),
            )

        stale_camera_keys = [
            key for key in self._active
            if key[0] == camera_id and key not in current_keys
        ]
        for key in stale_camera_keys:
            self._active.pop(key, None)

    def _prune(self, timestamp: float) -> None:
        stale = [
            key for key, candidate in self._lost.items()
            if timestamp - candidate.last_seen_at > self._temporal_gate_seconds
        ]
        for key in stale:
            self._lost.pop(key, None)
        stale_active = [
            key for key, candidate in self._active.items()
            if timestamp - candidate.observed_at > min(2.0, self._temporal_gate_seconds)
        ]
        for key in stale_active:
            self._active.pop(key, None)

    def _track_floor_x(self, track: Track) -> float | None:
        calibrated_flag = track.derived_features.get("floor_position_calibrated")
        if calibrated_flag != 1.0:
            return None
        floor_x = track.derived_features.get("floor_x")
        if floor_x is None or not math.isfinite(floor_x):
            return None
        return float(floor_x)

    def _track_floor_y(self, track: Track) -> float | None:
        calibrated_flag = track.derived_features.get("floor_position_calibrated")
        if calibrated_flag != 1.0:
            return None
        floor_y = track.derived_features.get("floor_y")
        if floor_y is None or not math.isfinite(floor_y):
            return None
        return float(floor_y)

    def _floor_signal(
        self,
        *,
        source_floor_x: float | None,
        source_floor_y: float | None,
        target_floor_x: float | None,
        target_floor_y: float | None,
        relation: str,
    ) -> tuple[float | None, float | None]:
        if (
            source_floor_x is None
            or source_floor_y is None
            or target_floor_x is None
            or target_floor_y is None
        ):
            return None, None

        distance = math.sqrt(
            (source_floor_x - target_floor_x) ** 2
            + (source_floor_y - target_floor_y) ** 2
        )
        if not math.isfinite(distance):
            return None, None

        if relation == "overlap_active":
            max_distance = 2.5
            if distance > max_distance:
                return None, distance
            return max(0.0, 1.0 - (distance / max_distance)), distance

        max_distance = 8.0
        if distance > max_distance:
            return None, distance
        return max(0.0, 1.0 - (distance / max_distance)), distance
