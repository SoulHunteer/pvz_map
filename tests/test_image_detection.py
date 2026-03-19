from __future__ import annotations

from dataclasses import replace

import cv2
import numpy as np

from app.services.image_detection import ZoneDetector


def _fill_gradient_zone(
    image: np.ndarray,
    polygon_points: np.ndarray,
    edge_bgr: tuple[int, int, int],
    center_bgr: tuple[int, int, int],
) -> None:
    mask = np.zeros(image.shape[:2], dtype=np.uint8)
    cv2.fillPoly(mask, [polygon_points], 255)

    distance = cv2.distanceTransform(mask, cv2.DIST_L2, 5)
    max_dist = float(distance.max())
    if max_dist <= 1e-9:
        return

    ratio = np.clip(distance / max_dist, 0.0, 1.0)
    edge = np.array(edge_bgr, dtype=np.float32).reshape((1, 1, 3))
    center = np.array(center_bgr, dtype=np.float32).reshape((1, 1, 3))
    gradient = edge + (center - edge) * ratio[:, :, None]

    region = mask > 0
    image[region] = np.clip(gradient[region], 0, 255).astype(np.uint8)


def _draw_circle_marker(
    image: np.ndarray,
    center: tuple[int, int],
    radius: int,
    bgr: tuple[int, int, int],
) -> None:
    """Draw a filled circle simulating a map pin or marker icon."""
    cv2.circle(image, center, radius, bgr, -1)


def test_detects_contour_based_zones(settings):
    detector = ZoneDetector(settings)

    image = np.zeros((260, 260, 3), dtype=np.uint8)

    first = np.array([[30, 40], [110, 35], [120, 120], [40, 130]], dtype=np.int32)
    second = np.array([[150, 150], [220, 150], [220, 230], [150, 230]], dtype=np.int32)

    _fill_gradient_zone(
        image,
        first,
        edge_bgr=(126, 42, 122),
        center_bgr=(221, 152, 217),
    )

    _fill_gradient_zone(
        image,
        second,
        edge_bgr=(228, 180, 212),
        center_bgr=(244, 204, 228),
    )

    zones = detector.detect_zones(image)

    assert len(zones) == 2
    assert all(zone.area > settings.cv_min_area for zone in zones)
    assert all(zone.perimeter > settings.cv_min_perimeter for zone in zones)
    assert all(len(zone.polygon) >= 3 for zone in zones)
    assert all(len(zone.contour) >= 3 for zone in zones)
    assert all(zone.shape_hash for zone in zones)


def test_detects_zone_with_subtle_gradient(settings):
    detector = ZoneDetector(settings)

    image = np.full((400, 400, 3), (220, 215, 210), dtype=np.uint8)

    poly = np.array([[120, 120], [280, 120], [280, 280], [120, 280]], dtype=np.int32)
    _fill_gradient_zone(
        image,
        poly,
        edge_bgr=(200, 120, 195),
        center_bgr=(225, 165, 220),
    )

    zones = detector.detect_zones(image)
    assert len(zones) == 1


def test_detects_small_rectangular_zones(settings):
    detector = ZoneDetector(settings)

    image = np.full((300, 400, 3), (230, 225, 220), dtype=np.uint8)

    rects = [
        np.array([[50, 50], [65, 50], [65, 68], [50, 68]], dtype=np.int32),
        np.array([[100, 80], [125, 80], [125, 100], [100, 100]], dtype=np.int32),
        np.array([[180, 120], [205, 120], [205, 142], [180, 142]], dtype=np.int32),
    ]
    for rect in rects:
        _fill_gradient_zone(
            image,
            rect,
            edge_bgr=(196, 77, 190),
            center_bgr=(221, 152, 217),
        )

    zones = detector.detect_zones(image)
    assert len(zones) == 3, f"Expected 3 small rectangular zones, got {len(zones)}"


def test_detects_zones_at_image_edges(settings):
    detector = ZoneDetector(settings)

    image = np.full((300, 400, 3), (230, 225, 220), dtype=np.uint8)

    bottom = np.array([[150, 270], [170, 270], [170, 300], [150, 300]], dtype=np.int32)
    _fill_gradient_zone(image, bottom, edge_bgr=(196, 77, 190), center_bgr=(221, 152, 217))

    top = np.array([[100, 0], [120, 0], [120, 25], [100, 25]], dtype=np.int32)
    _fill_gradient_zone(image, top, edge_bgr=(196, 77, 190), center_bgr=(221, 152, 217))

    left = np.array([[0, 130], [18, 130], [18, 165], [0, 165]], dtype=np.int32)
    _fill_gradient_zone(image, left, edge_bgr=(196, 77, 190), center_bgr=(221, 152, 217))

    zones = detector.detect_zones(image)
    assert len(zones) == 3, f"Expected 3 edge-touching zones, got {len(zones)}"


def test_rejects_giant_background_contour(settings):
    detector = ZoneDetector(settings)

    rng = np.random.RandomState(42)
    image = np.full((720, 1280, 3), (235, 230, 225), dtype=np.uint8)

    noise_mask = rng.rand(720, 1280) < 0.03
    image[noise_mask] = (195, 75, 189)

    zones = detector.detect_zones(image)
    for zone in zones:
        assert zone.area < 0.15 * 1280 * 720, f"Giant contour with area {zone.area} should have been rejected"


def test_rejects_perfect_circles(settings):
    """Perfect circles are rejected when compactness threshold is strict."""
    strict_settings = replace(settings, cv_max_compactness=0.5)
    detector = ZoneDetector(strict_settings)

    image = np.full((300, 300, 3), (240, 235, 230), dtype=np.uint8)

    cv2.circle(image, (150, 150), 60, (195, 75, 189), -1)
    cv2.circle(image, (150, 150), 30, (221, 152, 217), -1)

    zones = detector.detect_zones(image)
    assert len(zones) == 0, f"Perfect circle should be rejected by compactness filter, got {len(zones)} zones"


def test_rejects_circular_marker_pins(settings):
    detector = ZoneDetector(settings)

    image = np.full((300, 300, 3), (240, 235, 230), dtype=np.uint8)

    for cx, cy in [(60, 60), (150, 80), (100, 200), (220, 150)]:
        _draw_circle_marker(image, (cx, cy), radius=14, bgr=(200, 70, 195))

    zones = detector.detect_zones(image)
    assert len(zones) == 0, f"Expected 0 zones for marker pins, got {len(zones)}"
