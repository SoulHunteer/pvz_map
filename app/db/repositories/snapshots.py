from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DetectedZone, SnapshotStatus, ZoneSnapshot


class SnapshotRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_snapshot(
        self,
        tracked_item_id: int,
        status: SnapshotStatus,
        screenshot_path: str,
        processed_image_path: str,
        zone_count: int,
        diff_image_path: str | None = None,
        error_message: str | None = None,
    ) -> ZoneSnapshot:
        snapshot = ZoneSnapshot(
            tracked_item_id=tracked_item_id,
            status=status,
            screenshot_path=screenshot_path,
            processed_image_path=processed_image_path,
            diff_image_path=diff_image_path,
            zone_count=zone_count,
            error_message=error_message,
        )
        self.session.add(snapshot)
        self.session.flush()
        return snapshot

    def get(self, snapshot_id: int) -> ZoneSnapshot | None:
        return self.session.get(ZoneSnapshot, snapshot_id)

    def list_for_tracked_item(self, tracked_item_id: int, limit: int = 10) -> list[ZoneSnapshot]:
        stmt = (
            select(ZoneSnapshot)
            .where(ZoneSnapshot.tracked_item_id == tracked_item_id)
            .order_by(ZoneSnapshot.checked_at.desc(), ZoneSnapshot.id.desc())
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all())

    def add_detected_zone(
        self,
        snapshot_id: int,
        centroid_x: float,
        centroid_y: float,
        bbox_x: int,
        bbox_y: int,
        bbox_w: int,
        bbox_h: int,
        area: float,
        perimeter: float,
        polygon_json: str | None,
        contour_json: str | None,
        shape_hash: str | None,
    ) -> DetectedZone:
        zone = DetectedZone(
            snapshot_id=snapshot_id,
            centroid_x=centroid_x,
            centroid_y=centroid_y,
            bbox_x=bbox_x,
            bbox_y=bbox_y,
            bbox_w=bbox_w,
            bbox_h=bbox_h,
            area=area,
            perimeter=perimeter,
            polygon_json=polygon_json,
            contour_json=contour_json,
            shape_hash=shape_hash,
        )
        self.session.add(zone)
        self.session.flush()
        return zone

    def latest_success_snapshot(self, tracked_item_id: int, exclude_snapshot_id: int | None = None) -> ZoneSnapshot | None:
        stmt = (
            select(ZoneSnapshot)
            .where(ZoneSnapshot.tracked_item_id == tracked_item_id)
            .where(ZoneSnapshot.status == SnapshotStatus.SUCCESS)
            .order_by(ZoneSnapshot.checked_at.desc(), ZoneSnapshot.id.desc())
        )
        rows = list(self.session.scalars(stmt).all())
        if not rows:
            return None
        if exclude_snapshot_id is None:
            return rows[0]
        for row in rows:
            if row.id != exclude_snapshot_id:
                return row
        return None

    def get_detected_zones(self, snapshot_id: int) -> list[DetectedZone]:
        stmt = select(DetectedZone).where(DetectedZone.snapshot_id == snapshot_id)
        return list(self.session.scalars(stmt).all())
