from __future__ import annotations

from app.db.models import ChangeEvent, TrackedItem, User, ZoneSnapshot
from app.services.types import NotificationPayload


class NotificationService:
    """Builds payloads for a future Telegram notifier."""

    @staticmethod
    def build_payload(user: User, item: TrackedItem, snapshot: ZoneSnapshot, event: ChangeEvent) -> NotificationPayload:
        return NotificationPayload(
            event_id=event.id,
            telegram_user_id=user.telegram_user_id,
            tracked_item_id=item.id,
            tracked_item_title=item.title,
            event_type=event.event_type.value,
            added_count=event.added_count,
            removed_count=event.removed_count,
            snapshot_id=snapshot.id,
            diff_image_path=snapshot.diff_image_path,
        )
