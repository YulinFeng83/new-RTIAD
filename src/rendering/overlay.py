"""
Video overlay renderer.

Draws bounding boxes, person labels, zone polygons, direction arrows,
and a stats HUD onto each frame using OpenCV drawing primitives.
"""

from __future__ import annotations

import cv2
import numpy as np

from src.config import OverlayConfig
from src.counting.footfall_counter import FootfallStats
from src.tracking.track import PersonLabel, Track
from src.zones.zone import Zone, ZoneType


class OverlayRenderer:
    """Renders all visual annotations onto a video frame."""

    def __init__(self, config: OverlayConfig):
        self._config = config

    def render(
        self,
        frame: np.ndarray,
        tracks: list[Track],
        zones: list[Zone],
        stats: FootfallStats,
    ) -> np.ndarray:
        """Draw all overlays on a copy of the frame and return it."""
        out = frame.copy()

        if self._config.show_zones:
            self._draw_zones(out, zones)

        if self._config.show_bboxes:
            self._draw_tracks(out, tracks)

        if self._config.show_stats_hud:
            self._draw_stats_hud(out, stats, tracks)

        return out

    def _draw_zones(self, frame: np.ndarray, zones: list[Zone]) -> None:
        for zone in zones:
            pts = np.array(zone.polygon, dtype=np.int32)
            if len(pts) < 3:
                continue

            color = self._zone_color(zone.zone_type)

            overlay = frame.copy()
            cv2.fillPoly(overlay, [pts], color)
            cv2.addWeighted(overlay, 0.2, frame, 0.8, 0, frame)

            cv2.polylines(frame, [pts], isClosed=True, color=color, thickness=2)

            centroid = pts.mean(axis=0).astype(int)
            label = f"{zone.name or zone.zone_id} ({zone.zone_type.value})"
            cv2.putText(
                frame, label, tuple(centroid),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA,
            )

            self._draw_direction_arrow(frame, centroid, zone.direction_vector, color)

    def _draw_direction_arrow(
        self,
        frame: np.ndarray,
        origin: np.ndarray,
        direction: tuple[float, float],
        color: tuple[int, ...],
    ) -> None:
        arrow_length = 40
        dx, dy = direction
        mag = (dx**2 + dy**2) ** 0.5
        if mag == 0:
            return
        ndx, ndy = dx / mag, dy / mag

        # IN arrow (green) — entering direction
        in_pt = (int(origin[0] + ndx * arrow_length), int(origin[1] + ndy * arrow_length))
        cv2.arrowedLine(frame, tuple(origin), in_pt, (0, 255, 136), 2, tipLength=0.3)
        cv2.putText(frame, "IN", (in_pt[0] + int(ndx * 12), in_pt[1] + int(ndy * 12)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 136), 2)

        # OUT arrow (red) — exact opposite
        out_pt = (int(origin[0] - ndx * arrow_length), int(origin[1] - ndy * arrow_length))
        cv2.arrowedLine(frame, tuple(origin), out_pt, (100, 100, 255), 2, tipLength=0.3)
        cv2.putText(frame, "OUT", (out_pt[0] - int(ndx * 12) - 15, out_pt[1] - int(ndy * 12)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (100, 100, 255), 2)

    def _draw_tracks(self, frame: np.ndarray, tracks: list[Track]) -> None:
        for track in tracks:
            bbox = track.current_bbox
            if bbox is None:
                continue
            x1, y1, x2, y2 = bbox
            color = self._label_color(track.label)

            cv2.rectangle(frame, (x1, y1), (x2, y2), color, self._config.bbox_thickness)

            if self._config.show_labels:
                label_text = f"#{track.track_id} {track.label.value}"
                if track.label != PersonLabel.UNKNOWN:
                    label_text += f" {track.label_confidence:.0%}"
                self._draw_label_bg(frame, label_text, (x1, y1 - 5), color)

    def _draw_label_bg(
        self,
        frame: np.ndarray,
        text: str,
        origin: tuple[int, int],
        color: tuple[int, ...],
    ) -> None:
        """Draw text with a filled background rectangle for readability."""
        font = cv2.FONT_HERSHEY_SIMPLEX
        scale = self._config.font_scale
        thickness = 1

        (tw, th), baseline = cv2.getTextSize(text, font, scale, thickness)
        x, y = origin
        y = max(y, th + 4)

        cv2.rectangle(frame, (x, y - th - 4), (x + tw + 4, y + 2), color, -1)
        cv2.putText(frame, text, (x + 2, y - 2), font, scale, (255, 255, 255), thickness, cv2.LINE_AA)

    def _draw_stats_hud(
        self,
        frame: np.ndarray,
        stats: FootfallStats,
        tracks: list[Track],
    ) -> None:
        """Draw a stats panel in the top-left corner."""
        employee_count = sum(1 for t in tracks if t.label == PersonLabel.EMPLOYEE)
        customer_count = sum(1 for t in tracks if t.label == PersonLabel.CUSTOMER)

        lines = [
            f"Entries: {stats.total_entries}  |  Exits: {stats.total_exits}",
            f"In Store: {stats.current_in_store}",
            f"Visible: {len(tracks)} (Emp: {employee_count}, Cust: {customer_count})",
            f"Employees Filtered: {stats.employees_filtered}",
        ]

        font = cv2.FONT_HERSHEY_SIMPLEX
        scale = 0.6
        thickness = 1
        padding = 10
        line_height = 25
        max_w = 0
        for line in lines:
            (tw, _), _ = cv2.getTextSize(line, font, scale, thickness)
            max_w = max(max_w, tw)

        box_w = max_w + 2 * padding
        box_h = len(lines) * line_height + padding

        overlay = frame.copy()
        cv2.rectangle(overlay, (0, 0), (box_w, box_h), (0, 0, 0), -1)
        cv2.addWeighted(overlay, 0.6, frame, 0.4, 0, frame)

        for i, line in enumerate(lines):
            y = padding + (i + 1) * line_height - 5
            cv2.putText(frame, line, (padding, y), font, scale, (255, 255, 255), thickness, cv2.LINE_AA)

    def _label_color(self, label: PersonLabel) -> tuple[int, ...]:
        c = self._config.colors
        if label == PersonLabel.EMPLOYEE:
            return tuple(c.employee)
        elif label == PersonLabel.CUSTOMER:
            return tuple(c.customer)
        return tuple(c.unknown)

    def _zone_color(self, zone_type: ZoneType) -> tuple[int, ...]:
        c = self._config.colors
        if zone_type == ZoneType.ENTRY:
            return tuple(c.entry_zone)
        elif zone_type == ZoneType.EXIT:
            return tuple(c.exit_zone)
        return tuple(c.bidirectional_zone)

    def on_config_change(self, config: OverlayConfig) -> None:
        self._config = config
