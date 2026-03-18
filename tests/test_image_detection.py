from __future__ import annotations

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
    """Draw a filled circle simulating a map pin / marker icon."""
    cv2.circle(image, center, radius, bgr, -1)


# ── Detection of real zones ──────────────────────────────────────────


def test_detects_contour_based_zones(settings):
    detector = ZoneDetector(settings)

    image = np.zeros((260, 260, 3), dtype=np.uint8)

    first = np.array([[30, 40], [110, 35], [120, 120], [40, 130]], dtype=np.int32)
    second = np.array([[150, 150], [220, 150], [220, 230], [150, 230]], dtype=np.int32)

    # Saturated zone profile.
    _fill_gradient_zone(
        image,
        first,
        edge_bgr=(126, 42, 122),
        center_bgr=(221, 152, 217),
    )

    # Less saturated zone profile.
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
    """Zone on a coloured map background where luma delta is small."""
    detector = ZoneDetector(settings)

    image = np.full((200, 200, 3), (220, 215, 210), dtype=np.uint8)  # greyish bg

    poly = np.array([[40, 40], [160, 40], [160, 160], [40, 160]], dtype=np.int32)
    # Subtle purple tones — lighter than typical, weak gradient.
    _fill_gradient_zone(
        image,
        poly,
        edge_bgr=(200, 120, 195),
        center_bgr=(225, 165, 220),
    )

    zones = detector.detect_zones(image)
    assert len(zones) == 1


# ── False-positive suppression ───────────────────────────────────────


def test_rejects_circular_marker_pins(settings):
    """Round map-pin markers must not be detected as zones."""
    detector = ZoneDetector(settings)

    image = np.full((300, 300, 3), (240, 235, 230), dtype=np.uint8)

    # Scatter several bright-pink marker dots.
    for cx, cy in [(60, 60), (150, 80), (100, 200), (220, 150)]:
        _draw_circle_marker(image, (cx, cy), radius=14, bgr=(200, 70, 195))

    zones = detector.detect_zones(image)
    assert len(zones) == 0, f"Expected 0 zones for marker pins, got {len(zones)}"


def test_rejects_giant_background_contour(settings):
    """A huge low-coverage contour must be rejected (map background artefact)."""
    detector = ZoneDetector(settings)

    # 1280×720 image with scattered faint purple noise — simulates map tiles
    # that merge into one giant contour after morphological close.
    rng = np.random.RandomState(42)
    image = np.full((720, 1280, 3), (235, 230, 225), dtype=np.uint8)

    # Sprinkle sparse purple pixels (low coverage).
    noise_mask = rng.rand(720, 1280) < 0.03
    image[noise_mask] = (195, 75, 189)

    zones = detector.detect_zones(image)
    # Should either produce no zones or only tiny incidental ones, never a
    # full-image contour.
    for z in zones:
        assert z.area < 0.15 * 1280 * 720, (
            f"Giant contour with area {z.area} should have been rejected"
        )


def test_rejects_ui_cookie_banner_buttons(settings):
    """Purple-ish buttons in the bottom part of the page must be filtered."""
    detector = ZoneDetector(settings)

    image = np.full((720, 1280, 3), (240, 235, 230), dtype=np.uint8)

    # Simulate two cookie-banner buttons at the bottom of the screen.
    for bx in [480, 660]:
        btn = np.array(
            [[bx, 660], [bx + 140, 660], [bx + 140, 700], [bx, 700]],
            dtype=np.int32,
        )
        _fill_gradient_zone(
            image,
            btn,
            edge_bgr=(195, 80, 190),
            center_bgr=(210, 120, 205),
        )

    zones = detector.detect_zones(image)
    assert len(zones) == 0, f"Cookie-banner buttons detected as zones: {len(zones)}"


def test_max_compactness_rejects_perfect_circles(settings):
    """Perfect circles (compactness ≈ 1.0) exceed cv_max_compactness (0.86)."""
    detector = ZoneDetector(settings)

    image = np.full((300, 300, 3), (240, 235, 230), dtype=np.uint8)

    # Draw a large filled purple circle — compactness should be close to 1.0.
    cv2.circle(image, (150, 150), 60, (195, 75, 189), -1)
    # Add gradient to pass the gradient check (if it ever got there).
    cv2.circle(image, (150, 150), 30, (221, 152, 217), -1)

    zones = detector.detect_zones(image)
    assert len(zones) == 0, (
        f"Perfect circle should be rejected by max_compactness, got {len(zones)} zones"
    )
