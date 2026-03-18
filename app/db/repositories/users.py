from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import User


class UserRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_by_telegram_id(self, telegram_user_id: int) -> User | None:
        stmt = select(User).where(User.telegram_user_id == telegram_user_id)
        return self.session.scalar(stmt)

    def get(self, user_id: int) -> User | None:
        return self.session.get(User, user_id)

    def create_or_update(
        self,
        telegram_user_id: int,
        username: str | None = None,
        full_name: str | None = None,
        role: str = "user",
        tariff_plan: str = "trial",
        tariff_end_at: datetime | None = None,
        is_active: bool = True,
    ) -> User:
        user = self.get_by_telegram_id(telegram_user_id)
        if user is None:
            user = User(
                telegram_user_id=telegram_user_id,
                username=username,
                full_name=full_name,
                role=role,
                tariff_plan=tariff_plan,
                tariff_end_at=tariff_end_at,
                is_active=is_active,
            )
            self.session.add(user)
        else:
            user.username = username
            user.full_name = full_name
            user.role = role
            user.tariff_plan = tariff_plan
            user.tariff_end_at = tariff_end_at
            user.is_active = is_active
            user.updated_at = datetime.now(timezone.utc)

        self.session.flush()
        return user

    def touch_profile(self, user: User, username: str | None, full_name: str | None) -> None:
        user.username = username
        user.full_name = full_name
        user.updated_at = datetime.now(timezone.utc)
        self.session.flush()

    def update_tariff(self, user: User, tariff_plan: str, tariff_end_at: datetime | None) -> None:
        user.tariff_plan = tariff_plan
        user.tariff_end_at = tariff_end_at
        user.updated_at = datetime.now(timezone.utc)
        self.session.flush()
