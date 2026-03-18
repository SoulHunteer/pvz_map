from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import TrackedItem


class TrackedItemRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(
        self,
        user_id: int,
        title: str,
        map_link: str,
        is_active: bool = True,
    ) -> TrackedItem:
        item = TrackedItem(user_id=user_id, title=title, map_link=map_link, is_active=is_active)
        self.session.add(item)
        self.session.flush()
        return item

    def list_active(self) -> list[TrackedItem]:
        stmt = select(TrackedItem).where(TrackedItem.is_active.is_(True))
        return list(self.session.scalars(stmt).all())

    def list_for_user(self, user_id: int, only_active: bool = False) -> list[TrackedItem]:
        stmt = select(TrackedItem).where(TrackedItem.user_id == user_id).order_by(TrackedItem.created_at.desc(), TrackedItem.id.desc())
        if only_active:
            stmt = stmt.where(TrackedItem.is_active.is_(True))
        return list(self.session.scalars(stmt).all())

    def get(self, tracked_item_id: int) -> TrackedItem | None:
        return self.session.get(TrackedItem, tracked_item_id)

    def get_for_user(self, tracked_item_id: int, user_id: int) -> TrackedItem | None:
        stmt = select(TrackedItem).where(TrackedItem.id == tracked_item_id).where(TrackedItem.user_id == user_id)
        return self.session.scalar(stmt)

    def count_for_user(self, user_id: int, only_active: bool = False) -> int:
        items = self.list_for_user(user_id=user_id, only_active=only_active)
        return len(items)

    def update(
        self,
        item: TrackedItem,
        *,
        title: str | None = None,
        map_link: str | None = None,
        is_active: bool | None = None,
    ) -> TrackedItem:
        if title is not None:
            item.title = title
        if map_link is not None:
            item.map_link = map_link
        if is_active is not None:
            item.is_active = is_active
        item.updated_at = datetime.now(timezone.utc)
        self.session.flush()
        return item

    def delete(self, item: TrackedItem) -> None:
        self.session.delete(item)
        self.session.flush()

    def update_status(
        self,
        tracked_item_id: int,
        status: str,
        zone_count: int,
        checked_at: datetime,
        success: bool,
    ) -> None:
        item = self.get(tracked_item_id)
        if item is None:
            return
        item.last_status = status
        item.last_zone_count = zone_count
        item.last_check_at = checked_at
        if success:
            item.last_success_at = checked_at
        item.updated_at = datetime.now(timezone.utc)
        self.session.flush()
