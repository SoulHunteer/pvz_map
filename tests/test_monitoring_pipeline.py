from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

from app.db.models import ChangeEvent, ChangeEventType, ZoneSnapshot
from app.db.repositories import TrackedItemRepository, UserRepository
from app.db.session import SessionLocal
from app.services.monitoring import MonitoringService
from app.services.types import ScreenshotResult, ZoneGeometry


class DummyScraper:
    def __init__(self, screenshots_dir: Path):
        self.screenshots_dir = screenshots_dir
        self.calls = 0

    def capture_map(self, map_link: str, tracked_item_id: int) -> ScreenshotResult:
        self.calls += 1
        image = np.zeros((240, 240, 3), dtype=np.uint8)
        path = self.screenshots_dir / f"dummy_{tracked_item_id}_{self.calls}.png"
        cv2.imwrite(str(path), image)
        return ScreenshotResult(image=image, screenshot_path=str(path))


class DummyDetector:
    def __init__(self, processed_dir: Path, diff_dir: Path):
        self.processed_dir = processed_dir
        self.diff_dir = diff_dir
        self.calls = 0

    def detect_zones(self, image: np.ndarray) -> list[ZoneGeometry]:
        self.calls += 1
        base = ZoneGeometry(
            centroid_x=90.0,
            centroid_y=90.0,
            bbox_x=70,
            bbox_y=70,
            bbox_w=40,
            bbox_h=40,
            area=1600.0,
            perimeter=160.0,
            polygon=[[70, 70], [110, 70], [110, 110], [70, 110]],
            contour=[[70, 70], [110, 70], [110, 110], [70, 110]],
            shape_hash="shape-a",
        )
        if self.calls == 1:
            return [base]

        shifted = ZoneGeometry(
            centroid_x=95.0,
            centroid_y=92.0,
            bbox_x=75,
            bbox_y=72,
            bbox_w=40,
            bbox_h=40,
            area=1590.0,
            perimeter=160.0,
            polygon=[[75, 72], [115, 72], [115, 112], [75, 112]],
            contour=[[75, 72], [115, 72], [115, 112], [75, 112]],
            shape_hash="shape-a",
        )
        added = ZoneGeometry(
            centroid_x=180.0,
            centroid_y=170.0,
            bbox_x=165,
            bbox_y=155,
            bbox_w=30,
            bbox_h=30,
            area=900.0,
            perimeter=120.0,
            polygon=[[165, 155], [195, 155], [195, 185], [165, 185]],
            contour=[[165, 155], [195, 155], [195, 185], [165, 185]],
            shape_hash="shape-b",
        )
        return [shifted, added]

    def render_processed_image(self, image: np.ndarray, zones: list[ZoneGeometry], tracked_item_id: int) -> str:
        path = self.processed_dir / f"processed_{tracked_item_id}_{self.calls}.png"
        cv2.imwrite(str(path), image)
        return str(path)

    @staticmethod
    def zones_to_json(zone: ZoneGeometry) -> tuple[str, str]:
        return json.dumps(zone.polygon), json.dumps(zone.contour)

    def render_diff_image(
        self,
        base_image: np.ndarray,
        current_zones: list[ZoneGeometry],
        added_indexes: list[int],
        removed_zones: list[ZoneGeometry],
        tracked_item_id: int,
    ) -> str:
        path = self.diff_dir / f"diff_{tracked_item_id}_{self.calls}.png"
        cv2.imwrite(str(path), base_image)
        return str(path)


def test_monitoring_creates_snapshots_and_change_event(settings):
    with SessionLocal() as session:
        user_repo = UserRepository(session)
        tracked_repo = TrackedItemRepository(session)

        user = user_repo.create_or_update(telegram_user_id=101, username="user", full_name="User")
        tracked_item = tracked_repo.create(user_id=user.id, title="Test map", map_link="https://example.com/map")
        session.commit()

        tracked_item_id = tracked_item.id

    service = MonitoringService(settings)
    service.scraper = DummyScraper(Path(settings.screenshots_dir))
    service.detector = DummyDetector(Path(settings.processed_dir), Path(settings.diffs_dir))

    first = service.run_for_tracked_item(tracked_item_id)
    second = service.run_for_tracked_item(tracked_item_id)

    assert first.status == "success"
    assert first.snapshot_id is not None
    assert first.event_id is None

    assert second.status == "success"
    assert second.snapshot_id is not None
    assert second.event_id is not None
    assert second.added_count == 1
    assert second.removed_count == 0
    assert second.notification_payload is not None

    with SessionLocal() as session:
        snapshots = session.query(ZoneSnapshot).filter(ZoneSnapshot.tracked_item_id == tracked_item_id).all()
        assert len(snapshots) == 2

        event = session.query(ChangeEvent).one()
        assert event.event_type == ChangeEventType.NEW_ZONES
        assert event.previous_snapshot_id == first.snapshot_id
        assert event.current_snapshot_id == second.snapshot_id
