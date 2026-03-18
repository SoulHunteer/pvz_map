from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.core.exceptions import TariffLimitError
from app.core.settings import Settings
from app.db.repositories import TrackedItemRepository, UserRepository
from app.db.session import SessionLocal


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class SubscriptionService:
    def __init__(self, settings: Settings):
        self.settings = settings

    def _tracked_item_limit(self, tariff_plan: str) -> int:
        plan = (tariff_plan or "trial").lower()
        if plan in {"trial", "free"}:
            return self.settings.max_items_trial_free
        if plan == "base":
            return self.settings.max_items_base
        if plan == "pro":
            return self.settings.max_items_pro
        return self.settings.max_items_trial_free

    def ensure_default_trial_user(self, telegram_user_id: int, username: str | None = None, full_name: str | None = None) -> int:
        with SessionLocal() as session:
            user_repo = UserRepository(session)
            user = user_repo.get_by_telegram_id(telegram_user_id)
            if user is None:
                user = user_repo.create_or_update(
                    telegram_user_id=telegram_user_id,
                    username=username,
                    full_name=full_name,
                    tariff_plan="trial",
                    tariff_end_at=datetime.now(timezone.utc) + timedelta(days=self.settings.trial_days),
                    is_active=True,
                )
                session.commit()
                return user.id

            if not user.tariff_end_at and (user.tariff_plan or "trial").lower() == "trial":
                user.tariff_end_at = datetime.now(timezone.utc) + timedelta(days=self.settings.trial_days)
            session.commit()
            return user.id

    def assert_can_add_tracked_item(self, user_id: int) -> None:
        with SessionLocal() as session:
            user_repo = UserRepository(session)
            tracked_repo = TrackedItemRepository(session)

            user = user_repo.get(user_id)
            if user is None:
                raise TariffLimitError("User not found")

            if not user.is_active:
                raise TariffLimitError("User is inactive")

            tariff_end_at = _as_utc(user.tariff_end_at)
            if tariff_end_at and tariff_end_at < datetime.now(timezone.utc):
                raise TariffLimitError("Tariff period expired")

            total_count = len(tracked_repo.list_for_user(user_id=user.id, only_active=False))
            limit = self._tracked_item_limit(user.tariff_plan)
            if total_count >= limit:
                raise TariffLimitError(
                    f"Tracked item limit reached ({total_count}/{limit}) for plan {user.tariff_plan}"
                )

    def create_tracked_item(
        self,
        telegram_user_id: int,
        map_link: str,
        title: str,
        username: str | None = None,
        full_name: str | None = None,
        is_active: bool = True,
    ) -> int:
        with SessionLocal() as session:
            user_repo = UserRepository(session)
            tracked_repo = TrackedItemRepository(session)

            user = user_repo.get_by_telegram_id(telegram_user_id)
            if user is None:
                user_id = self.ensure_default_trial_user(telegram_user_id, username=username, full_name=full_name)
                user = user_repo.get(user_id)

            if user is None:
                raise TariffLimitError("Cannot create tracked item for unknown user")

            # Reuse tariff validation rules
            self.assert_can_add_tracked_item(user.id)

            item = tracked_repo.create(
                user_id=user.id,
                title=title,
                map_link=map_link,
                is_active=is_active,
            )
            session.commit()
            return item.id

    def get_tariff_summary(self, user_id: int) -> dict:
        with SessionLocal() as session:
            user_repo = UserRepository(session)
            tracked_repo = TrackedItemRepository(session)
            user = user_repo.get(user_id)
            if user is None:
                raise TariffLimitError("User not found")

            limit = self._tracked_item_limit(user.tariff_plan)
            total = tracked_repo.count_for_user(user.id)

            return {
                "tariff_plan": user.tariff_plan,
                "tariff_end_at": _as_utc(user.tariff_end_at).isoformat() if user.tariff_end_at else None,
                "limit": limit,
                "used": total,
                "remaining": max(0, limit - total),
                "is_active": user.is_active,
            }
