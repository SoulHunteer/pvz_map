from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Callable
from urllib.parse import urlparse

from sqlalchemy import func, select

from app.core.exceptions import AccessDeniedError, NotFoundError, TariffLimitError, ValidationError
from app.core.settings import Settings
from app.db.models import ChangeEvent, DetectedZone, SnapshotStatus, TrackedItem, User, ZoneSnapshot
from app.db.repositories import ChangeEventRepository, SnapshotRepository, TrackedItemRepository, UserRepository
from app.db.session import SessionLocal
from app.services.monitoring import MonitoringService
from app.services.types import ZoneGeometry

logger = logging.getLogger(__name__)


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return _as_utc(dt).isoformat()


class MvpService:
    def __init__(self, settings: Settings, monitoring_service: MonitoringService | None = None):
        self.settings = settings
        self.monitoring_service = monitoring_service or MonitoringService(settings)

    def _is_admin_telegram_user(self, telegram_user_id: int) -> bool:
        return telegram_user_id in self.settings.admin_telegram_user_ids

    def _is_admin_user(self, user: User) -> bool:
        return (user.role or "").lower() == "admin" or self._is_admin_telegram_user(user.telegram_user_id)

    def _tracked_item_limit(self, user: User) -> int:
        if self.settings.admin_bypass_tariff_limits and self._is_admin_user(user):
            return 999_999

        plan = (user.tariff_plan or "trial").lower()
        if plan in {"trial", "free"}:
            return self.settings.max_items_trial_free
        if plan == "base":
            return self.settings.max_items_base
        if plan == "pro":
            return self.settings.max_items_pro
        return self.settings.max_items_trial_free

    def _assert_tariff_active(self, user: User) -> None:
        if self.settings.admin_bypass_tariff_limits and self._is_admin_user(user):
            return

        if not user.is_active:
            raise TariffLimitError("User is inactive")

        tariff_end_at = _as_utc(user.tariff_end_at)
        if tariff_end_at is not None and tariff_end_at < datetime.now(timezone.utc):
            raise TariffLimitError("Tariff period expired")

    @staticmethod
    def _default_title_from_link(map_link: str) -> str:
        parsed = urlparse(map_link)
        host = parsed.netloc or "map"
        return f"Мониторинг {host}"

    @staticmethod
    def _validate_map_link(map_link: str) -> None:
        parsed = urlparse(map_link)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValidationError("Map link must be a valid http(s) URL")

    def _assert_user_allowed(self, telegram_user_id: int) -> None:
        allowed = self.settings.allowed_telegram_user_ids
        if allowed and telegram_user_id not in allowed:
            raise AccessDeniedError("User is not allowed in current test mode")

    def _ensure_user(
        self,
        session,
        telegram_user_id: int,
        username: str | None = None,
        full_name: str | None = None,
    ) -> User:
        self._assert_user_allowed(telegram_user_id)

        user_repo = UserRepository(session)
        user = user_repo.get_by_telegram_id(telegram_user_id)

        is_admin = self._is_admin_telegram_user(telegram_user_id)
        default_role = "admin" if is_admin else "user"
        default_tariff_plan = "pro" if is_admin else "trial"
        default_tariff_end_at = None if is_admin else (datetime.now(timezone.utc) + timedelta(days=self.settings.trial_days))

        if user is None:
            user = user_repo.create_or_update(
                telegram_user_id=telegram_user_id,
                username=username,
                full_name=full_name,
                role=default_role,
                tariff_plan=default_tariff_plan,
                tariff_end_at=default_tariff_end_at,
                is_active=True,
            )
            logger.info(
                "Created new user telegram_user_id=%s role=%s tariff_plan=%s",
                telegram_user_id,
                user.role,
                user.tariff_plan,
            )
            session.flush()
            return user

        if username is not None:
            user.username = username
        if full_name is not None:
            user.full_name = full_name

        if is_admin:
            user.role = "admin"
            user.tariff_plan = "pro"
            user.tariff_end_at = None
            user.is_active = True

        user.updated_at = datetime.now(timezone.utc)
        session.flush()
        return user

    def _item_to_dict(self, item: TrackedItem) -> dict:
        return {
            "id": item.id,
            "user_id": item.user_id,
            "title": item.title,
            "map_link": item.map_link,
            "is_active": item.is_active,
            "last_check_at": _iso(item.last_check_at),
            "last_success_at": _iso(item.last_success_at),
            "last_status": item.last_status,
            "last_zone_count": item.last_zone_count,
            "created_at": _iso(item.created_at),
            "updated_at": _iso(item.updated_at),
        }

    @staticmethod
    def _event_to_dict(event: ChangeEvent, tracked_item_title: str) -> dict:
        return {
            "id": event.id,
            "tracked_item_id": event.tracked_item_id,
            "tracked_item_title": tracked_item_title,
            "previous_snapshot_id": event.previous_snapshot_id,
            "current_snapshot_id": event.current_snapshot_id,
            "added_count": event.added_count,
            "removed_count": event.removed_count,
            "event_type": event.event_type.value,
            "created_at": _iso(event.created_at),
            "notification_sent_at": _iso(event.notification_sent_at),
        }

    @staticmethod
    def _snapshot_to_dict(snapshot: ZoneSnapshot) -> dict:
        return {
            "id": snapshot.id,
            "tracked_item_id": snapshot.tracked_item_id,
            "checked_at": _iso(snapshot.checked_at),
            "status": snapshot.status.value,
            "screenshot_path": snapshot.screenshot_path,
            "processed_image_path": snapshot.processed_image_path,
            "diff_image_path": snapshot.diff_image_path,
            "zone_count": snapshot.zone_count,
            "error_message": snapshot.error_message,
        }

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
    def _zone_to_overlay_dict(
        zone: ZoneGeometry,
        status: str,
        label: str,
        appeared_at: datetime | None = None,
        updated_at: datetime | None = None,
        last_seen_at: datetime | None = None,
    ) -> dict:
        return {
            "status": status,
            "label": label,
            "centroid_x": zone.centroid_x,
            "centroid_y": zone.centroid_y,
            "bbox_x": zone.bbox_x,
            "bbox_y": zone.bbox_y,
            "bbox_w": zone.bbox_w,
            "bbox_h": zone.bbox_h,
            "area": zone.area,
            "perimeter": zone.perimeter,
            "polygon": zone.polygon,
            "contour": zone.contour,
            "shape_hash": zone.shape_hash,
            "appeared_at": _iso(appeared_at),
            "updated_at": _iso(updated_at),
            "last_seen_at": _iso(last_seen_at),
        }

    @staticmethod
    def _shape_hash_lifecycle(session, tracked_item_id: int, shape_hashes: set[str]) -> dict[str, tuple[datetime, datetime]]:
        if not shape_hashes:
            return {}

        stmt = (
            select(
                DetectedZone.shape_hash,
                func.min(ZoneSnapshot.checked_at),
                func.max(ZoneSnapshot.checked_at),
            )
            .join(ZoneSnapshot, DetectedZone.snapshot_id == ZoneSnapshot.id)
            .where(
                ZoneSnapshot.tracked_item_id == tracked_item_id,
                ZoneSnapshot.status == SnapshotStatus.SUCCESS,
                DetectedZone.shape_hash.in_(sorted(shape_hashes)),
            )
            .group_by(DetectedZone.shape_hash)
        )

        rows = session.execute(stmt).all()
        lifecycle: dict[str, tuple[datetime, datetime]] = {}
        for shape_hash, first_seen, last_seen in rows:
            if shape_hash and first_seen is not None and last_seen is not None:
                lifecycle[str(shape_hash)] = (_as_utc(first_seen), _as_utc(last_seen))
        return lifecycle

    def get_or_create_user_summary(
        self,
        telegram_user_id: int,
        username: str | None = None,
        full_name: str | None = None,
    ) -> dict:
        with SessionLocal() as session:
            user = self._ensure_user(
                session,
                telegram_user_id=telegram_user_id,
                username=username,
                full_name=full_name,
            )
            tracked_repo = TrackedItemRepository(session)

            limit = self._tracked_item_limit(user)
            total = tracked_repo.count_for_user(user.id)
            active = tracked_repo.count_for_user(user.id, only_active=True)

            session.commit()
            return {
                "id": user.id,
                "telegram_user_id": user.telegram_user_id,
                "username": user.username,
                "full_name": user.full_name,
                "role": user.role,
                "tariff_plan": user.tariff_plan,
                "tariff_end_at": _iso(user.tariff_end_at),
                "is_active": user.is_active,
                "tracked_items_total": total,
                "tracked_items_active": active,
                "tracked_items_limit": limit,
            }

    def list_tracked_items(self, telegram_user_id: int) -> list[dict]:
        with SessionLocal() as session:
            user = self._ensure_user(session, telegram_user_id)
            tracked_repo = TrackedItemRepository(session)
            items = tracked_repo.list_for_user(user.id)
            session.commit()
            return [self._item_to_dict(item) for item in items]

    def create_tracked_item(
        self,
        telegram_user_id: int,
        map_link: str,
        title: str | None = None,
        username: str | None = None,
        full_name: str | None = None,
        is_active: bool = False,
    ) -> dict:
        self._validate_map_link(map_link)
        title = (title or "").strip() or self._default_title_from_link(map_link)

        with SessionLocal() as session:
            user = self._ensure_user(
                session,
                telegram_user_id=telegram_user_id,
                username=username,
                full_name=full_name,
            )
            self._assert_tariff_active(user)

            tracked_repo = TrackedItemRepository(session)
            current_total = tracked_repo.count_for_user(user.id)
            limit = self._tracked_item_limit(user)
            if current_total >= limit:
                raise TariffLimitError(
                    f"Tracked items limit reached ({current_total}/{limit}) for plan {user.tariff_plan}"
                )

            item = tracked_repo.create(user_id=user.id, title=title, map_link=map_link, is_active=is_active)
            logger.info(
                "Tracked item created user_id=%s tracked_item_id=%s title=%s",
                user.id,
                item.id,
                item.title,
            )
            session.commit()
            return self._item_to_dict(item)

    def _get_item_for_user(self, session, telegram_user_id: int, tracked_item_id: int) -> tuple[User, TrackedItem]:
        self._assert_user_allowed(telegram_user_id)
        user_repo = UserRepository(session)
        tracked_repo = TrackedItemRepository(session)
        user = user_repo.get_by_telegram_id(telegram_user_id)
        if user is None:
            raise NotFoundError("User not found")

        item = tracked_repo.get_for_user(tracked_item_id=tracked_item_id, user_id=user.id)
        if item is None:
            raise NotFoundError("Tracked item not found")
        return user, item

    def get_tracked_item(self, telegram_user_id: int, tracked_item_id: int) -> dict:
        with SessionLocal() as session:
            _, item = self._get_item_for_user(session, telegram_user_id, tracked_item_id)
            session.commit()
            return self._item_to_dict(item)

    def update_tracked_item(
        self,
        telegram_user_id: int,
        tracked_item_id: int,
        *,
        title: str | None = None,
        map_link: str | None = None,
        is_active: bool | None = None,
    ) -> dict:
        if map_link is not None:
            self._validate_map_link(map_link)

        with SessionLocal() as session:
            user, item = self._get_item_for_user(session, telegram_user_id, tracked_item_id)
            self._assert_tariff_active(user)

            if title is not None and not title.strip():
                raise ValidationError("Title cannot be empty")

            tracked_repo = TrackedItemRepository(session)
            tracked_repo.update(
                item,
                title=title.strip() if title is not None else None,
                map_link=map_link,
                is_active=is_active,
            )
            logger.info("Tracked item updated user_id=%s tracked_item_id=%s", user.id, item.id)
            session.commit()
            return self._item_to_dict(item)

    def delete_tracked_item(self, telegram_user_id: int, tracked_item_id: int) -> None:
        with SessionLocal() as session:
            user, item = self._get_item_for_user(session, telegram_user_id, tracked_item_id)
            tracked_repo = TrackedItemRepository(session)
            tracked_repo.delete(item)
            logger.info("Tracked item deleted user_id=%s tracked_item_id=%s", user.id, tracked_item_id)
            session.commit()

    def list_item_snapshots(self, telegram_user_id: int, tracked_item_id: int, limit: int = 10) -> list[dict]:
        with SessionLocal() as session:
            _, item = self._get_item_for_user(session, telegram_user_id, tracked_item_id)
            snapshot_repo = SnapshotRepository(session)
            snapshots = snapshot_repo.list_for_tracked_item(item.id, limit=limit)
            session.commit()
            return [self._snapshot_to_dict(snapshot) for snapshot in snapshots]

    def list_recent_snapshots_for_user(self, telegram_user_id: int, limit: int = 10) -> list[dict]:
        self._assert_user_allowed(telegram_user_id)
        with SessionLocal() as session:
            user_repo = UserRepository(session)
            tracked_repo = TrackedItemRepository(session)
            snapshot_repo = SnapshotRepository(session)

            user = user_repo.get_by_telegram_id(telegram_user_id)
            if user is None:
                return []

            rows: list[dict] = []
            for item in tracked_repo.list_for_user(user.id):
                snapshots = snapshot_repo.list_for_tracked_item(item.id, limit=limit)
                for snapshot in snapshots:
                    rows.append(
                        {
                            **self._snapshot_to_dict(snapshot),
                            "tracked_item_title": item.title,
                        }
                    )

            rows.sort(key=lambda row: row["checked_at"] or "", reverse=True)
            return rows[:limit]

    def list_item_events(self, telegram_user_id: int, tracked_item_id: int, limit: int = 10) -> list[dict]:
        with SessionLocal() as session:
            _, item = self._get_item_for_user(session, telegram_user_id, tracked_item_id)
            event_repo = ChangeEventRepository(session)
            events = event_repo.list_for_tracked_item(item.id, limit=limit)
            session.commit()
            return [self._event_to_dict(event, item.title) for event in events]

    def get_snapshot_zone_diff(
        self,
        telegram_user_id: int,
        tracked_item_id: int,
        snapshot_id: int,
        previous_snapshot_id: int | None = None,
    ) -> dict:
        with SessionLocal() as session:
            _, item = self._get_item_for_user(session, telegram_user_id, tracked_item_id)
            snapshot_repo = SnapshotRepository(session)

            current_snapshot = snapshot_repo.get(snapshot_id)
            if current_snapshot is None or current_snapshot.tracked_item_id != item.id:
                raise NotFoundError("Snapshot not found")

            current_db_zones = snapshot_repo.get_detected_zones(current_snapshot.id)
            current_zones = [self._db_zone_to_geometry(zone) for zone in current_db_zones]

            previous_snapshot: ZoneSnapshot | None = None
            if previous_snapshot_id is not None:
                previous_snapshot = snapshot_repo.get(previous_snapshot_id)
                if previous_snapshot is None or previous_snapshot.tracked_item_id != item.id:
                    raise NotFoundError("Previous snapshot not found")
            else:
                previous_snapshot = snapshot_repo.latest_success_snapshot(
                    tracked_item_id=item.id,
                    exclude_snapshot_id=current_snapshot.id,
                )

            previous_zones: list[ZoneGeometry] = []
            if previous_snapshot is not None:
                previous_db_zones = snapshot_repo.get_detected_zones(previous_snapshot.id)
                previous_zones = [self._db_zone_to_geometry(zone) for zone in previous_db_zones]

            match_result = self.monitoring_service.matcher.match(previous_zones, current_zones)
            added_set = set(match_result.added_current_indices)
            removed_set = set(match_result.removed_previous_indices)
            stable_indexes = [idx for idx in range(len(current_zones)) if idx not in added_set]

            shape_hashes = {
                zone.shape_hash
                for zone in [*current_zones, *previous_zones]
                if zone.shape_hash
            }
            lifecycle_by_hash = self._shape_hash_lifecycle(session, item.id, shape_hashes)

            current_checked_at = _as_utc(current_snapshot.checked_at)
            previous_checked_at = _as_utc(previous_snapshot.checked_at) if previous_snapshot else None

            zones_payload: list[dict] = []
            added_counter = 1
            stable_counter = 1
            for idx, zone in enumerate(current_zones):
                first_seen, last_seen = lifecycle_by_hash.get(zone.shape_hash or "", (None, None))
                if idx in added_set:
                    zones_payload.append(
                        self._zone_to_overlay_dict(
                            zone,
                            status="added",
                            label=f"A{added_counter}",
                            appeared_at=first_seen or current_checked_at,
                            updated_at=current_checked_at,
                            last_seen_at=current_checked_at,
                        )
                    )
                    added_counter += 1
                else:
                    zones_payload.append(
                        self._zone_to_overlay_dict(
                            zone,
                            status="stable",
                            label=f"S{stable_counter}",
                            appeared_at=first_seen or previous_checked_at or current_checked_at,
                            updated_at=current_checked_at,
                            last_seen_at=last_seen or current_checked_at,
                        )
                    )
                    stable_counter += 1

            removed_counter = 1
            for idx in sorted(removed_set):
                zone = previous_zones[idx]
                first_seen, last_seen = lifecycle_by_hash.get(zone.shape_hash or "", (None, None))
                zones_payload.append(
                    self._zone_to_overlay_dict(
                        zone,
                        status="removed",
                        label=f"R{removed_counter}",
                        appeared_at=first_seen or previous_checked_at,
                        updated_at=current_checked_at,
                        last_seen_at=last_seen or previous_checked_at,
                    )
                )
                removed_counter += 1

            session.commit()
            return {
                "tracked_item_id": item.id,
                "snapshot_id": current_snapshot.id,
                "snapshot_checked_at": _iso(current_snapshot.checked_at),
                "previous_snapshot_id": previous_snapshot.id if previous_snapshot else None,
                "counts": {
                    "added": len(added_set),
                    "removed": len(removed_set),
                    "stable": len(stable_indexes),
                    "total_current": len(current_zones),
                },
                "zones": zones_payload,
            }

    def list_recent_events_for_user(self, telegram_user_id: int, limit: int = 10) -> list[dict]:
        self._assert_user_allowed(telegram_user_id)
        with SessionLocal() as session:
            user_repo = UserRepository(session)
            user = user_repo.get_by_telegram_id(telegram_user_id)
            if user is None:
                return []

            stmt = (
                select(ChangeEvent, TrackedItem.title)
                .join(TrackedItem, ChangeEvent.tracked_item_id == TrackedItem.id)
                .where(TrackedItem.user_id == user.id)
                .order_by(ChangeEvent.created_at.desc(), ChangeEvent.id.desc())
                .limit(limit)
            )
            rows = list(session.execute(stmt).all())
            session.commit()
            return [self._event_to_dict(event, title) for event, title in rows]

    def run_manual_check(
        self,
        telegram_user_id: int,
        tracked_item_id: int,
        progress_callback: Callable[[int, str], None] | None = None,
    ) -> dict:
        with SessionLocal() as session:
            user, item = self._get_item_for_user(session, telegram_user_id, tracked_item_id)
            self._assert_tariff_active(user)
            session.commit()

        logger.info("Manual check requested telegram_user_id=%s tracked_item_id=%s", telegram_user_id, tracked_item_id)
        result = self.monitoring_service.run_for_tracked_item(
            tracked_item_id,
            progress_callback=progress_callback,
        )
        return result.as_dict()

    def activate_item(self, telegram_user_id: int, tracked_item_id: int, is_active: bool) -> dict:
        return self.update_tracked_item(
            telegram_user_id=telegram_user_id,
            tracked_item_id=tracked_item_id,
            is_active=is_active,
        )

    def get_item_full_details(self, telegram_user_id: int, tracked_item_id: int) -> dict:
        item = self.get_tracked_item(telegram_user_id, tracked_item_id)
        snapshots = self.list_item_snapshots(telegram_user_id, tracked_item_id, limit=5)
        events = self.list_item_events(telegram_user_id, tracked_item_id, limit=5)
        return {
            "item": item,
            "snapshots": snapshots,
            "events": events,
        }

    def set_mock_tariff(self, telegram_user_id: int, tariff_plan: str, days: int | None = None) -> dict:
        allowed = {"trial", "free", "base", "pro"}
        plan = tariff_plan.lower()
        if plan not in allowed:
            raise ValidationError(f"Unsupported tariff plan: {tariff_plan}")

        with SessionLocal() as session:
            user = self._ensure_user(session, telegram_user_id)
            tariff_end_at = None
            if days is not None:
                tariff_end_at = datetime.now(timezone.utc) + timedelta(days=days)
            elif plan == "trial":
                tariff_end_at = datetime.now(timezone.utc) + timedelta(days=self.settings.trial_days)

            user.tariff_plan = plan
            user.tariff_end_at = tariff_end_at
            user.updated_at = datetime.now(timezone.utc)
            session.commit()

        return self.get_or_create_user_summary(telegram_user_id)

    def assert_user_can_view_item(self, telegram_user_id: int, tracked_item_id: int) -> None:
        self._assert_user_allowed(telegram_user_id)
        with SessionLocal() as session:
            user_repo = UserRepository(session)
            user = user_repo.get_by_telegram_id(telegram_user_id)
            if user is None:
                raise AccessDeniedError("User not found")

            tracked_repo = TrackedItemRepository(session)
            item = tracked_repo.get_for_user(tracked_item_id, user.id)
            if item is None:
                raise AccessDeniedError("No access to tracked item")
            session.commit()






