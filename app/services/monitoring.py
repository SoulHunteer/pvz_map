from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Callable

from app.core.exceptions import MonitoringError
from app.core.settings import Settings
from app.db.models import ChangeEventType, DetectedZone, SnapshotStatus
from app.db.repositories import ChangeEventRepository, SnapshotRepository, TrackedItemRepository, UserRepository
from app.db.session import SessionLocal
from app.services.image_detection import ZoneDetector
from app.services.notifications import NotificationService
from app.services.scraper import MapScraper
from app.services.types import MonitoringRunResult, ZoneGeometry
from app.services.zone_matching import ZoneMatcher

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[int, str], None]


class MonitoringService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.scraper = MapScraper(settings)
        self.detector = ZoneDetector(settings)
        self.matcher = ZoneMatcher(settings)
        self.notifications = NotificationService()

    def list_active_tracked_item_ids(self) -> list[int]:
        with SessionLocal() as session:
            tracked_repo = TrackedItemRepository(session)
            return [item.id for item in tracked_repo.list_active()]

    def mark_notification_sent(self, event_id: int) -> None:
        with SessionLocal() as session:
            change_repo = ChangeEventRepository(session)
            event = change_repo.get(event_id)
            if event is None:
                return
            change_repo.mark_notification_sent(event)
            session.commit()

    @staticmethod
    def _db_zone_to_geometry(db_zone: DetectedZone) -> ZoneGeometry:
        polygon = json.loads(db_zone.polygon_json) if db_zone.polygon_json else []
        contour = json.loads(db_zone.contour_json) if db_zone.contour_json else []
        return ZoneGeometry(
            centroid_x=db_zone.centroid_x,
            centroid_y=db_zone.centroid_y,
            bbox_x=db_zone.bbox_x,
            bbox_y=db_zone.bbox_y,
            bbox_w=db_zone.bbox_w,
            bbox_h=db_zone.bbox_h,
            area=db_zone.area,
            perimeter=db_zone.perimeter,
            polygon=polygon,
            contour=contour,
            shape_hash=db_zone.shape_hash,
        )

    @staticmethod
    def _decide_event_type(previous_count: int, current_count: int, added_count: int, removed_count: int) -> ChangeEventType | None:
        if previous_count == current_count and added_count == 0 and removed_count == 0:
            return None
        if previous_count > 0 and current_count == 0:
            return ChangeEventType.BECAME_EMPTY
        if previous_count == 0 and current_count > 0:
            return ChangeEventType.RESTORED
        if added_count > 0 and removed_count > 0:
            return ChangeEventType.CHANGED
        if added_count > 0:
            return ChangeEventType.NEW_ZONES
        if removed_count > 0:
            return ChangeEventType.ZONES_REMOVED
        return None

    @staticmethod
    def _emit_progress(progress_callback: ProgressCallback | None, percent: int, status: str) -> None:
        if progress_callback is None:
            return
        try:
            bounded = max(0, min(100, int(percent)))
            progress_callback(bounded, status)
        except Exception:
            logger.debug("Progress callback failed", exc_info=True)

    def run_for_tracked_item(
        self,
        tracked_item_id: int,
        progress_callback: ProgressCallback | None = None,
    ) -> MonitoringRunResult:
        checked_at = datetime.now(timezone.utc)
        self._emit_progress(progress_callback, 5, "Инициализирую проверку")

        with SessionLocal() as session:
            tracked_repo = TrackedItemRepository(session)
            snapshot_repo = SnapshotRepository(session)
            change_repo = ChangeEventRepository(session)
            user_repo = UserRepository(session)

            item = tracked_repo.get(tracked_item_id)
            if item is None:
                self._emit_progress(progress_callback, 100, "Ошибка: отслеживание не найдено")
                return MonitoringRunResult(
                    tracked_item_id=tracked_item_id,
                    checked_at=checked_at,
                    status="error",
                    error_message="Tracked item not found",
                )

            logger.info("Monitoring check started tracked_item_id=%s title=%s", item.id, item.title)
            screenshot_path = ""
            processed_path = ""

            try:
                self._emit_progress(progress_callback, 15, "Открываю карту")
                screenshot = self.scraper.capture_map(item.map_link, tracked_item_id)
                screenshot_path = screenshot.screenshot_path
                self._emit_progress(progress_callback, 35, "Делаю скриншот")

                self._emit_progress(progress_callback, 50, "Размечаю зоны")
                zones = self.detector.detect_zones(screenshot.image)
                processed_path = self.detector.render_processed_image(screenshot.image, zones, tracked_item_id)
                self._emit_progress(progress_callback, 65, f"Зоны найдены: {len(zones)}")

                status = SnapshotStatus.SUCCESS if zones else SnapshotStatus.EMPTY
                snapshot = snapshot_repo.create_snapshot(
                    tracked_item_id=tracked_item_id,
                    status=status,
                    screenshot_path=screenshot_path,
                    processed_image_path=processed_path,
                    zone_count=len(zones),
                )

                for zone in zones:
                    polygon_json, contour_json = self.detector.zones_to_json(zone)
                    snapshot_repo.add_detected_zone(
                        snapshot_id=snapshot.id,
                        centroid_x=zone.centroid_x,
                        centroid_y=zone.centroid_y,
                        bbox_x=zone.bbox_x,
                        bbox_y=zone.bbox_y,
                        bbox_w=zone.bbox_w,
                        bbox_h=zone.bbox_h,
                        area=zone.area,
                        perimeter=zone.perimeter,
                        polygon_json=polygon_json,
                        contour_json=contour_json,
                        shape_hash=zone.shape_hash,
                    )

                previous_snapshot = snapshot_repo.latest_success_snapshot(
                    tracked_item_id=tracked_item_id,
                    exclude_snapshot_id=snapshot.id,
                )

                added_count = 0
                removed_count = 0
                event = None
                notification_payload = None

                if previous_snapshot is not None:
                    self._emit_progress(progress_callback, 75, "Сравниваю с прошлой проверкой")
                    previous_db_zones = snapshot_repo.get_detected_zones(previous_snapshot.id)
                    previous_zones = [self._db_zone_to_geometry(zone) for zone in previous_db_zones]
                    match_result = self.matcher.match(previous_zones, zones)
                    added_count = len(match_result.added_current_indices)
                    removed_count = len(match_result.removed_previous_indices)

                    event_type = self._decide_event_type(
                        previous_count=previous_snapshot.zone_count,
                        current_count=len(zones),
                        added_count=added_count,
                        removed_count=removed_count,
                    )

                    if event_type is not None:
                        if added_count > 0 or removed_count > 0:
                            removed_zones = [previous_zones[index] for index in match_result.removed_previous_indices]
                            diff_path = self.detector.render_diff_image(
                                base_image=screenshot.image,
                                current_zones=zones,
                                added_indexes=match_result.added_current_indices,
                                removed_zones=removed_zones,
                                tracked_item_id=tracked_item_id,
                            )
                            snapshot.diff_image_path = diff_path

                        event = change_repo.create(
                            tracked_item_id=tracked_item_id,
                            previous_snapshot_id=previous_snapshot.id,
                            current_snapshot_id=snapshot.id,
                            event_type=event_type,
                            added_count=added_count,
                            removed_count=removed_count,
                        )

                        user = user_repo.get(item.user_id)
                        if user is not None:
                            notification_payload = self.notifications.build_payload(user, item, snapshot, event)

                self._emit_progress(progress_callback, 90, "Сохраняю результат")
                tracked_repo.update_status(
                    tracked_item_id=tracked_item_id,
                    status=status.value,
                    zone_count=len(zones),
                    checked_at=checked_at,
                    success=True,
                )

                session.commit()
                logger.info(
                    "Monitoring check finished tracked_item_id=%s status=%s zones=%s added=%s removed=%s",
                    tracked_item_id,
                    status.value,
                    len(zones),
                    added_count,
                    removed_count,
                )
                self._emit_progress(progress_callback, 100, "Проверка завершена")
                return MonitoringRunResult(
                    tracked_item_id=tracked_item_id,
                    checked_at=checked_at,
                    status=status.value,
                    snapshot_id=snapshot.id,
                    zone_count=len(zones),
                    added_count=added_count,
                    removed_count=removed_count,
                    event_id=event.id if event else None,
                    notification_payload=notification_payload,
                )

            except MonitoringError as exc:
                snapshot = snapshot_repo.create_snapshot(
                    tracked_item_id=tracked_item_id,
                    status=SnapshotStatus.ERROR,
                    screenshot_path=screenshot_path,
                    processed_image_path=processed_path,
                    zone_count=0,
                    error_message=str(exc),
                )
                tracked_repo.update_status(
                    tracked_item_id=tracked_item_id,
                    status=SnapshotStatus.ERROR.value,
                    zone_count=0,
                    checked_at=checked_at,
                    success=False,
                )
                session.commit()
                logger.warning(
                    "Monitoring check failed tracked_item_id=%s reason=%s",
                    tracked_item_id,
                    exc,
                )
                self._emit_progress(progress_callback, 100, f"Ошибка: {exc}")
                return MonitoringRunResult(
                    tracked_item_id=tracked_item_id,
                    checked_at=checked_at,
                    status=SnapshotStatus.ERROR.value,
                    snapshot_id=snapshot.id,
                    error_message=str(exc),
                )
            except Exception as exc:
                logger.exception("Unexpected monitoring failure for tracked item %s", tracked_item_id)
                snapshot = snapshot_repo.create_snapshot(
                    tracked_item_id=tracked_item_id,
                    status=SnapshotStatus.ERROR,
                    screenshot_path=screenshot_path,
                    processed_image_path=processed_path,
                    zone_count=0,
                    error_message=f"Unexpected error: {exc}",
                )
                tracked_repo.update_status(
                    tracked_item_id=tracked_item_id,
                    status=SnapshotStatus.ERROR.value,
                    zone_count=0,
                    checked_at=checked_at,
                    success=False,
                )
                session.commit()
                self._emit_progress(progress_callback, 100, f"Ошибка: {exc}")
                return MonitoringRunResult(
                    tracked_item_id=tracked_item_id,
                    checked_at=checked_at,
                    status=SnapshotStatus.ERROR.value,
                    snapshot_id=snapshot.id,
                    error_message=str(exc),
                )
