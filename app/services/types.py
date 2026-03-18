from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np


@dataclass(slots=True)
class ScreenshotResult:
    image: np.ndarray
    screenshot_path: str


@dataclass(slots=True)
class ZoneGeometry:
    centroid_x: float
    centroid_y: float
    bbox_x: int
    bbox_y: int
    bbox_w: int
    bbox_h: int
    area: float
    perimeter: float
    polygon: list[list[int]]
    contour: list[list[int]]
    shape_hash: str | None

    @property
    def bbox(self) -> tuple[int, int, int, int]:
        return self.bbox_x, self.bbox_y, self.bbox_w, self.bbox_h


@dataclass(slots=True)
class NotificationPayload:
    event_id: int
    telegram_user_id: int
    tracked_item_id: int
    tracked_item_title: str
    event_type: str
    added_count: int
    removed_count: int
    snapshot_id: int
    diff_image_path: str | None


@dataclass(slots=True)
class MonitoringRunResult:
    tracked_item_id: int
    checked_at: datetime
    status: str
    snapshot_id: int | None = None
    zone_count: int = 0
    added_count: int = 0
    removed_count: int = 0
    event_id: int | None = None
    error_message: str | None = None
    notification_payload: NotificationPayload | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "tracked_item_id": self.tracked_item_id,
            "checked_at": self.checked_at.isoformat(),
            "status": self.status,
            "snapshot_id": self.snapshot_id,
            "zone_count": self.zone_count,
            "added_count": self.added_count,
            "removed_count": self.removed_count,
            "event_id": self.event_id,
            "error_message": self.error_message,
            "event_type": self.notification_payload.event_type if self.notification_payload else None,
            "tracked_item_title": self.notification_payload.tracked_item_title if self.notification_payload else None,
            "diff_image_path": self.notification_payload.diff_image_path if self.notification_payload else None,
        }
