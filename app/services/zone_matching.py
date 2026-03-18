from __future__ import annotations

from dataclasses import dataclass

from app.core.settings import Settings
from app.services.types import ZoneGeometry


@dataclass(slots=True)
class ZoneMatch:
    previous_index: int
    current_index: int
    score: float


@dataclass(slots=True)
class ZoneMatchResult:
    matches: list[ZoneMatch]
    added_current_indices: list[int]
    removed_previous_indices: list[int]


class ZoneMatcher:
    def __init__(self, settings: Settings):
        self.settings = settings

    @staticmethod
    def _centroid_distance(prev: ZoneGeometry, curr: ZoneGeometry) -> float:
        dx = prev.centroid_x - curr.centroid_x
        dy = prev.centroid_y - curr.centroid_y
        return (dx * dx + dy * dy) ** 0.5

    @staticmethod
    def _iou(prev: ZoneGeometry, curr: ZoneGeometry) -> float:
        ax1, ay1, aw, ah = prev.bbox
        bx1, by1, bw, bh = curr.bbox
        ax2, ay2 = ax1 + aw, ay1 + ah
        bx2, by2 = bx1 + bw, by1 + bh

        inter_x1 = max(ax1, bx1)
        inter_y1 = max(ay1, by1)
        inter_x2 = min(ax2, bx2)
        inter_y2 = min(ay2, by2)
        inter_w = max(0, inter_x2 - inter_x1)
        inter_h = max(0, inter_y2 - inter_y1)
        inter_area = inter_w * inter_h

        area_a = aw * ah
        area_b = bw * bh
        union = area_a + area_b - inter_area
        if union <= 0:
            return 0.0
        return inter_area / union

    @staticmethod
    def _area_delta_ratio(prev: ZoneGeometry, curr: ZoneGeometry) -> float:
        denominator = max(prev.area, curr.area, 1.0)
        return abs(prev.area - curr.area) / denominator

    def _pair_score(self, prev: ZoneGeometry, curr: ZoneGeometry) -> float | None:
        distance = self._centroid_distance(prev, curr)
        iou = self._iou(prev, curr)
        area_delta_ratio = self._area_delta_ratio(prev, curr)

        if distance > self.settings.zone_match_max_centroid_distance:
            return None

        shape_bonus = 0.0
        if prev.shape_hash and curr.shape_hash and prev.shape_hash == curr.shape_hash:
            shape_bonus = 0.15

        if iou < self.settings.zone_match_min_iou and area_delta_ratio > self.settings.zone_match_max_area_delta_ratio:
            if shape_bonus == 0.0:
                return None

        distance_score = 1.0 - min(1.0, distance / self.settings.zone_match_max_centroid_distance)
        iou_score = min(1.0, iou / max(self.settings.zone_match_min_iou, 1e-6))
        area_score = 1.0 - min(1.0, area_delta_ratio / max(self.settings.zone_match_max_area_delta_ratio, 1e-6))

        return 0.45 * distance_score + 0.35 * iou_score + 0.20 * area_score + shape_bonus

    def match(self, previous: list[ZoneGeometry], current: list[ZoneGeometry]) -> ZoneMatchResult:
        if not previous and not current:
            return ZoneMatchResult(matches=[], added_current_indices=[], removed_previous_indices=[])

        candidates: list[ZoneMatch] = []
        for prev_idx, prev_zone in enumerate(previous):
            for curr_idx, curr_zone in enumerate(current):
                score = self._pair_score(prev_zone, curr_zone)
                if score is None:
                    continue
                candidates.append(ZoneMatch(previous_index=prev_idx, current_index=curr_idx, score=score))

        candidates.sort(key=lambda item: item.score, reverse=True)

        used_previous: set[int] = set()
        used_current: set[int] = set()
        matches: list[ZoneMatch] = []

        for candidate in candidates:
            if candidate.previous_index in used_previous:
                continue
            if candidate.current_index in used_current:
                continue
            used_previous.add(candidate.previous_index)
            used_current.add(candidate.current_index)
            matches.append(candidate)

        added_current_indices = [idx for idx in range(len(current)) if idx not in used_current]
        removed_previous_indices = [idx for idx in range(len(previous)) if idx not in used_previous]

        return ZoneMatchResult(
            matches=matches,
            added_current_indices=added_current_indices,
            removed_previous_indices=removed_previous_indices,
        )
