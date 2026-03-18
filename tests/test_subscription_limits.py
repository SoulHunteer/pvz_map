from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.core.exceptions import TariffLimitError
from app.db.repositories import TrackedItemRepository, UserRepository
from app.db.session import SessionLocal
from app.services.subscriptions import SubscriptionService


def test_tariff_limit_enforced(settings):
    service = SubscriptionService(settings)

    with SessionLocal() as session:
        user_repo = UserRepository(session)
        tracked_repo = TrackedItemRepository(session)

        user = user_repo.create_or_update(
            telegram_user_id=777,
            username="free-user",
            full_name="Free User",
            tariff_plan="free",
            tariff_end_at=datetime.now(timezone.utc) + timedelta(days=1),
            is_active=True,
        )

        for index in range(settings.max_active_items_free):
            tracked_repo.create(
                user_id=user.id,
                title=f"item-{index}",
                map_link=f"https://example.com/{index}",
                is_active=True,
            )

        session.commit()
        user_id = user.id

    with pytest.raises(TariffLimitError):
        service.assert_can_add_tracked_item(user_id)
