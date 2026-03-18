from __future__ import annotations

from app.services.types import ZoneGeometry
from app.services.zone_matching import ZoneMatcher


def make_zone(cx: float, cy: float, x: int, y: int, w: int, h: int, area: float, shape_hash: str) -> ZoneGeometry:
    return ZoneGeometry(
        centroid_x=cx,
        centroid_y=cy,
        bbox_x=x,
        bbox_y=y,
        bbox_w=w,
        bbox_h=h,
        area=area,
        perimeter=2 * (w + h),
        polygon=[[x, y], [x + w, y], [x + w, y + h], [x, y + h]],
        contour=[[x, y], [x + w, y], [x + w, y + h], [x, y + h]],
        shape_hash=shape_hash,
    )


def test_zone_matcher_handles_small_jitter_and_new_zone(settings):
    matcher = ZoneMatcher(settings)

    previous = [make_zone(100.0, 100.0, 80, 80, 40, 40, 1600, "shape-a")]
    current = [
        make_zone(106.0, 103.0, 86, 83, 40, 40, 1580, "shape-a"),
        make_zone(200.0, 210.0, 180, 190, 36, 36, 1296, "shape-b"),
    ]

    result = matcher.match(previous, current)

    assert len(result.matches) == 1
    assert result.matches[0].previous_index == 0
    assert result.matches[0].current_index == 0
    assert result.added_current_indices == [1]
    assert result.removed_previous_indices == []
