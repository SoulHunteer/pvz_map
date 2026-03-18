from __future__ import annotations

import hashlib
import json
import logging
import math
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import cv2
import numpy as np

from app.core.exceptions import ImageDetectionError
from app.core.settings import Settings
from app.services.types import ZoneGeometry

logger = logging.getLogger(__name__)


class ZoneDetector:
    def __init__(self, settings: Settings):
        self.settings = settings

        # BGR palette for the two priority zone styles.
        # Colors are taken from the product examples provided by the user.
        saturated = np.array(
            [
                [126, 42, 122],
                [195, 75, 189],
                [221, 152, 217],
                [196, 77, 190],
                [207, 109, 202],
                [237, 206, 233],
            ],
            dtype=np.float32,
        )
        soft = np.array(
            [
                [244, 204, 228],
                [244, 200, 228],
                [228, 180, 212],
            ],
            dtype=np.float32,
        )
        target = np.array([list(settings.cv_target_bgr)], dtype=np.float32)

        self._saturated_palette = saturated
        self._soft_palette = soft
        self._palette = np.vstack([saturated, soft, target])

    def _build_mask(self, image: np.ndarray) -> np.ndarray:
        if self.settings.cv_mask_mode == "hsv":
            # Legacy mode for compatibility if explicitly requested via env.
            hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
            lower = np.array(
                [self.settings.cv_hue_min, self.settings.cv_sat_min, self.settings.cv_val_min],
                dtype=np.uint8,
            )
            upper = np.array(
                [self.settings.cv_hue_max, self.settings.cv_sat_max, self.settings.cv_val_max],
                dtype=np.uint8,
            )
            mask = cv2.inRange(hsv, lower, upper)
        else:
            tolerance = max(18, int(self.settings.cv_tolerance))
            mask = np.zeros(image.shape[:2], dtype=np.uint8)
            for color in self._palette:
                lower = np.clip(color - tolerance, 0, 255).astype(np.uint8)
                upper = np.clip(color + tolerance, 0, 255).astype(np.uint8)
                color_mask = cv2.inRange(image, lower, upper)
                mask = cv2.bitwise_or(mask, color_mask)

            b = image[:, :, 0].astype(np.int16)
            g = image[:, :, 1].astype(np.int16)
            r = image[:, :, 2].astype(np.int16)
            purple = (r - g >= 4) & (b - g >= 4)
            chroma = (np.maximum(np.maximum(r, g), b) - np.minimum(np.minimum(r, g), b) >= 8)
            tone = (r + b) >= (2 * g + 18)
            gate = (purple & chroma & tone).astype(np.uint8) * 255
            mask = cv2.bitwise_and(mask, gate)

        kernel_size = max(1, int(self.settings.cv_morph_kernel_size))
        kernel = np.ones((kernel_size, kernel_size), dtype=np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        return mask

    @staticmethod
    def _contour_to_list(contour: np.ndarray) -> list[list[int]]:
        return [[int(point[0][0]), int(point[0][1])] for point in contour]

    @staticmethod
    def _polygon_to_list(polygon: np.ndarray) -> list[list[int]]:
        return [[int(point[0][0]), int(point[0][1])] for point in polygon]

    @staticmethod
    def _shape_hash(contour: np.ndarray, area: float, perimeter: float) -> str:
        moments = cv2.moments(contour)
        hu = cv2.HuMoments(moments).flatten()
        hu_log = [(-1 if v < 0 else 1) * math.log10(abs(v) + 1e-12) for v in hu]
        signature = f"{area:.2f}|{perimeter:.2f}|" + "|".join(f"{v:.5f}" for v in hu_log)
        return hashlib.sha1(signature.encode("utf-8")).hexdigest()

    @staticmethod
    def _is_probable_ui_contour(
        image_width: int,
        image_height: int,
        bbox_x: int,
        bbox_y: int,
        bbox_w: int,
        bbox_h: int,
        area: float,
    ) -> bool:
        if image_width < 1000 or image_height < 500:
            return False

        # Touches image edges — likely part of the browser chrome or map UI.
        if bbox_x <= 1 or bbox_y <= 1:
            return True
        if bbox_x + bbox_w >= image_width - 1 or bbox_y + bbox_h >= image_height - 1:
            return True

        # Top-left corner (zoom controls, map logo).
        if bbox_x < 90 and bbox_y < 90:
            return True
        # Right edge strip (legend, controls) — only thin elements that look
        # like UI widgets, not map zones that happen to be near the edge.
        right_margin = image_width - (bbox_x + bbox_w)
        if right_margin < 5:
            return True
        if right_margin < 70 and bbox_w < 80 and bbox_h < 80:
            return True

        # Top-right strip (navigation widgets).
        if bbox_y < 80 and bbox_x > image_width * 0.55 and bbox_h < 90:
            return True

        # Bottom strip — cookie banner buttons, attribution bar.
        if bbox_y + bbox_h > image_height - 85 and bbox_w > 120:
            return True
        # Narrower bottom elements (small buttons like "Разрешить" / "Отказаться").
        if bbox_y > image_height * 0.75 and bbox_h < 60 and bbox_w < 200 and area < 4000:
            aspect = bbox_w / max(bbox_h, 1)
            if 1.8 <= aspect <= 6.0:
                return True

        # Very elongated thin bars near image edges (toolbars, status bars).
        # Do NOT apply in the interior — thin rectangles are valid building zones.
        aspect_ratio = max(bbox_w / max(bbox_h, 1), bbox_h / max(bbox_w, 1))
        near_edge = (
            bbox_x < 30
            or bbox_y < 30
            or bbox_x + bbox_w > image_width - 30
            or bbox_y + bbox_h > image_height - 30
        )
        if aspect_ratio > 4.0 and area < 800 and near_edge:
            return True

        # Giant contour spanning most of the image — map background artifact.
        if area > 0.25 * image_width * image_height:
            return True

        return False

    @staticmethod
    def _is_probable_marker_contour(
        area: float,
        compactness: float,
        bbox_w: int,
        bbox_h: int,
        polygon_vertices: int,
    ) -> bool:
        min_side = min(bbox_w, bbox_h)
        max_side = max(bbox_w, bbox_h)
        aspect_ratio = max(bbox_w / max(bbox_h, 1), bbox_h / max(bbox_w, 1))
        fill_ratio = area / (bbox_w * bbox_h + 1e-9)

        # Primary path: classic round markers (map pins, dots).
        if (
            12 <= min_side
            and max_side <= 55
            and area <= 1200
            and polygon_vertices >= 6
            and aspect_ratio <= 1.5
            and compactness >= 0.55
            and fill_ratio <= 0.88
        ):
            return True

        # Secondary path: very compact small blobs that are almost certainly
        # icons or pin clusters, even if they fail fill_ratio / vertex checks.
        if (
            max_side <= 40
            and area <= 800
            and compactness >= 0.75
            and aspect_ratio <= 1.3
        ):
            return True

        return False

    @staticmethod
    def _distance_to_palette(mean_bgr: np.ndarray, palette: np.ndarray) -> float:
        return float(np.linalg.norm(palette - mean_bgr.reshape(1, 3), axis=1).min())

    def _has_zone_gradient(self, image: np.ndarray, contour: np.ndarray, palette_mask: np.ndarray) -> bool:
        contour_mask = np.zeros(image.shape[:2], dtype=np.uint8)
        cv2.fillPoly(contour_mask, [contour], 255)

        contour_pixels = cv2.countNonZero(contour_mask)
        if contour_pixels < 60:
            return False

        palette_inside = cv2.countNonZero(cv2.bitwise_and(contour_mask, palette_mask))
        coverage_ratio = palette_inside / max(contour_pixels, 1)
        if coverage_ratio < 0.22:
            return False

        # Reject very large contours with low coverage — they are map-background
        # blobs merged by morphology, not real zones.
        if contour_pixels > 40000 and coverage_ratio < 0.55:
            return False

        dist = cv2.distanceTransform(contour_mask, cv2.DIST_L2, 5)
        max_dist = float(dist.max())
        if max_dist < 2.0:
            return False

        border_threshold = max(1.5, 0.20 * max_dist)
        center_threshold = max(2.5, 0.45 * max_dist)

        border_mask = (dist > 0.0) & (dist <= border_threshold)
        center_mask = dist >= center_threshold

        border_count = int(border_mask.sum())
        center_count = int(center_mask.sum())
        if border_count < 15 or center_count < 15:
            return False

        border_pixels = image[border_mask]
        center_pixels = image[center_mask]

        border_mean = border_pixels.mean(axis=0)
        center_mean = center_pixels.mean(axis=0)

        border_luma = float(0.114 * border_mean[0] + 0.587 * border_mean[1] + 0.299 * border_mean[2])
        center_luma = float(0.114 * center_mean[0] + 0.587 * center_mean[1] + 0.299 * center_mean[2])
        # Real map zones may be lighter at the centre (classic gradient) OR
        # darker at the centre (more saturated purple inside).  Use the
        # absolute brightness difference so both directions pass.
        luma_diff = abs(center_luma - border_luma)

        sat_border = self._distance_to_palette(border_mean, self._saturated_palette)
        sat_center = self._distance_to_palette(center_mean, self._saturated_palette)
        soft_border = self._distance_to_palette(border_mean, self._soft_palette)
        soft_center = self._distance_to_palette(center_mean, self._soft_palette)

        saturated_like = sat_border <= 85.0 and sat_center <= 95.0 and luma_diff >= 2.0
        soft_like = soft_border <= 70.0 and soft_center <= 70.0 and luma_diff >= 0.5
        mixed_like = (
            min(sat_border, soft_border) <= 80.0
            and min(sat_center, soft_center) <= 80.0
            and luma_diff >= 1.0
        )

        if saturated_like or soft_like or mixed_like:
            return True

        # Hue-based fallback: if both border and center sit in the purple hue
        # range (H 120-170 in OpenCV scale), accept the contour even when palette
        # Euclidean distance is high (e.g. zone over a coloured map background).
        border_hsv = cv2.cvtColor(
            border_mean.reshape(1, 1, 3).astype(np.uint8), cv2.COLOR_BGR2HSV
        )[0, 0]
        center_hsv = cv2.cvtColor(
            center_mean.reshape(1, 1, 3).astype(np.uint8), cv2.COLOR_BGR2HSV
        )[0, 0]
        hue_purple = (
            120 <= border_hsv[0] <= 170
            and 120 <= center_hsv[0] <= 170
            and border_hsv[1] >= 15
            and center_hsv[1] >= 15
            and coverage_ratio >= 0.35
        )
        if hue_purple:
            return True

        # Fallback for stable color-profile polygons where the gradient is subtle
        # on a compressed screenshot.
        best_border = min(sat_border, soft_border)
        best_center = min(sat_center, soft_center)
        area = float(cv2.contourArea(contour))
        perimeter = float(cv2.arcLength(contour, True))
        compactness = (4 * math.pi * area) / (perimeter * perimeter + 1e-9)
        return (
            coverage_ratio >= 0.70
            and best_border <= 30.0
            and best_center <= 30.0
            and area >= 200.0
            and compactness <= 0.86
        )

    def detect_zones(self, image: np.ndarray) -> list[ZoneGeometry]:
        try:
            mask = self._build_mask(image)
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            image_height, image_width = image.shape[:2]
            zones: list[ZoneGeometry] = []

            for contour in contours:
                area = float(cv2.contourArea(contour))
                perimeter = float(cv2.arcLength(contour, True))
                if area < self.settings.cv_min_area:
                    continue
                if perimeter < self.settings.cv_min_perimeter:
                    continue

                compactness = (4 * math.pi * area) / (perimeter * perimeter + 1e-9)
                if compactness < self.settings.cv_min_compactness:
                    continue
                if compactness > self.settings.cv_max_compactness:
                    continue

                moments = cv2.moments(contour)
                if abs(moments["m00"]) < 1e-9:
                    continue

                centroid_x = float(moments["m10"] / moments["m00"])
                centroid_y = float(moments["m01"] / moments["m00"])
                bbox_x, bbox_y, bbox_w, bbox_h = cv2.boundingRect(contour)

                if bbox_w < 10 or bbox_h < 10:
                    continue

                if self._is_probable_ui_contour(
                    image_width=image_width,
                    image_height=image_height,
                    bbox_x=bbox_x,
                    bbox_y=bbox_y,
                    bbox_w=bbox_w,
                    bbox_h=bbox_h,
                    area=area,
                ):
                    continue

                epsilon = 0.015 * perimeter
                polygon = cv2.approxPolyDP(contour, epsilon, True)

                if self._is_probable_marker_contour(
                    area=area,
                    compactness=compactness,
                    bbox_w=bbox_w,
                    bbox_h=bbox_h,
                    polygon_vertices=len(polygon),
                ):
                    continue

                if not self._has_zone_gradient(image, contour, mask):
                    continue

                zones.append(
                    ZoneGeometry(
                        centroid_x=centroid_x,
                        centroid_y=centroid_y,
                        bbox_x=int(bbox_x),
                        bbox_y=int(bbox_y),
                        bbox_w=int(bbox_w),
                        bbox_h=int(bbox_h),
                        area=area,
                        perimeter=perimeter,
                        polygon=self._polygon_to_list(polygon),
                        contour=self._contour_to_list(contour),
                        shape_hash=self._shape_hash(contour, area, perimeter),
                    )
                )

            zones.sort(key=lambda z: (z.centroid_x, z.centroid_y))
            return zones
        except Exception as exc:
            raise ImageDetectionError("Failed to detect zones") from exc

    def render_processed_image(self, image: np.ndarray, zones: list[ZoneGeometry], tracked_item_id: int) -> str:
        output = image.copy()
        for zone in zones:
            polygon = np.array(zone.polygon, dtype=np.int32).reshape((-1, 1, 2))
            cv2.polylines(output, [polygon], isClosed=True, color=(0, 255, 0), thickness=2)
            cv2.circle(output, (int(zone.centroid_x), int(zone.centroid_y)), 2, (255, 255, 255), -1)

        filename = (
            f"processed_{tracked_item_id}_"
            f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}_"
            f"{uuid4().hex[:8]}.png"
        )
        output_path = Path(self.settings.processed_dir) / filename
        cv2.imwrite(str(output_path), output)
        return str(output_path)

    def render_diff_image(
        self,
        base_image: np.ndarray,
        current_zones: list[ZoneGeometry],
        added_indexes: list[int],
        removed_zones: list[ZoneGeometry],
        tracked_item_id: int,
    ) -> str:
        output = base_image.copy()

        for index, zone in enumerate(current_zones):
            color = (0, 255, 0)
            if index in added_indexes:
                color = (0, 0, 255)
            polygon = np.array(zone.polygon, dtype=np.int32).reshape((-1, 1, 2))
            cv2.polylines(output, [polygon], isClosed=True, color=color, thickness=2)

        for zone in removed_zones:
            polygon = np.array(zone.polygon, dtype=np.int32).reshape((-1, 1, 2))
            cv2.polylines(output, [polygon], isClosed=True, color=(0, 0, 0), thickness=2)
            x1 = zone.bbox_x
            y1 = zone.bbox_y
            x2 = zone.bbox_x + zone.bbox_w
            y2 = zone.bbox_y + zone.bbox_h
            cv2.line(output, (x1, y1), (x2, y2), (0, 0, 0), 2)
            cv2.line(output, (x2, y1), (x1, y2), (0, 0, 0), 2)

        filename = (
            f"diff_{tracked_item_id}_"
            f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}_"
            f"{uuid4().hex[:8]}.png"
        )
        diff_path = Path(self.settings.diffs_dir) / filename
        cv2.imwrite(str(diff_path), output)
        return str(diff_path)

    @staticmethod
    def zones_to_json(zone: ZoneGeometry) -> tuple[str, str]:
        return json.dumps(zone.polygon), json.dumps(zone.contour)
