from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ChangeEvent, ChangeEventType


class ChangeEventRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(
        self,
        tracked_item_id: int,
        current_snapshot_id: int,
        event_type: ChangeEventType,
        added_count: int,
        removed_count: int,
        previous_snapshot_id: int | None = None,
    ) -> ChangeEvent:
        event = ChangeEvent(
            tracked_item_id=tracked_item_id,
            previous_snapshot_id=previous_snapshot_id,
            current_snapshot_id=current_snapshot_id,
            added_count=added_count,
            removed_count=removed_count,
            event_type=event_type,
        )
        self.session.add(event)
        self.session.flush()
        return event

    def get(self, event_id: int) -> ChangeEvent | None:
        return self.session.get(ChangeEvent, event_id)

    def list_for_tracked_item(self, tracked_item_id: int, limit: int = 10) -> list[ChangeEvent]:
        stmt = (
            select(ChangeEvent)
            .where(ChangeEvent.tracked_item_id == tracked_item_id)
            .order_by(ChangeEvent.created_at.desc(), ChangeEvent.id.desc())
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all())

    def mark_notification_sent(self, event: ChangeEvent) -> None:
        event.notification_sent_at = datetime.now(timezone.utc)
        self.session.flush()
