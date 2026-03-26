"""
Zone crossing detection.

Detects when a track's centroid trajectory crosses a zone polygon boundary.
Determines direction (entering vs exiting) via dot product of the movement
vector against the zone's configured direction normal.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np

from src.zones.zone import Zone

logger = logging.getLogger(__name__)


@dataclass
class CrossingResult:
    zone_id: str
    direction: str   # "entering" or "exiting"


def detect_crossing(
    prev_centroid: tuple[int, int],
    curr_centroid: tuple[int, int],
    zone: Zone,
) -> Optional[CrossingResult]:
    """
    Check if the line segment (prev_centroid → curr_centroid) crosses the
    zone polygon boundary, and determine direction.

    Returns a CrossingResult if a crossing occurred, else None.
    """
    prev_inside = point_in_polygon(prev_centroid, zone.polygon)
    curr_inside = point_in_polygon(curr_centroid, zone.polygon)

    if prev_inside == curr_inside:
        return None  # no boundary crossing

    move_vec = (
        curr_centroid[0] - prev_centroid[0],
        curr_centroid[1] - prev_centroid[1],
    )

    dot = move_vec[0] * zone.direction_vector[0] + move_vec[1] * zone.direction_vector[1]

    if dot > 0:
        direction = "entering"
    else:
        direction = "exiting"

    return CrossingResult(zone_id=zone.zone_id, direction=direction)


def point_in_polygon(point: tuple[int, int], polygon: list[tuple[int, int]]) -> bool:
    """Ray-casting algorithm for point-in-polygon test."""
    x, y = point
    n = len(polygon)
    inside = False

    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]

        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside
        j = i

    return inside


def segment_intersects_polygon(
    p1: tuple[int, int],
    p2: tuple[int, int],
    polygon: list[tuple[int, int]],
) -> bool:
    """Check if line segment p1→p2 intersects any edge of the polygon."""
    n = len(polygon)
    for i in range(n):
        j = (i + 1) % n
        if _segments_intersect(p1, p2, polygon[i], polygon[j]):
            return True
    return False


def _segments_intersect(
    a1: tuple[int, int],
    a2: tuple[int, int],
    b1: tuple[int, int],
    b2: tuple[int, int],
) -> bool:
    """Check if segments a1a2 and b1b2 intersect using cross products."""
    d1 = _cross(b1, b2, a1)
    d2 = _cross(b1, b2, a2)
    d3 = _cross(a1, a2, b1)
    d4 = _cross(a1, a2, b2)

    if ((d1 > 0 and d2 < 0) or (d1 < 0 and d2 > 0)) and \
       ((d3 > 0 and d4 < 0) or (d3 < 0 and d4 > 0)):
        return True

    if d1 == 0 and _on_segment(b1, b2, a1):
        return True
    if d2 == 0 and _on_segment(b1, b2, a2):
        return True
    if d3 == 0 and _on_segment(a1, a2, b1):
        return True
    if d4 == 0 and _on_segment(a1, a2, b2):
        return True

    return False


def _cross(o: tuple[int, int], a: tuple[int, int], b: tuple[int, int]) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _on_segment(p: tuple[int, int], q: tuple[int, int], r: tuple[int, int]) -> bool:
    return (min(p[0], q[0]) <= r[0] <= max(p[0], q[0]) and
            min(p[1], q[1]) <= r[1] <= max(p[1], q[1]))
