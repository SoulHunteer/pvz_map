from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select

from app.db.base import Base
from app.db.models import User
from app.db.repositories.tracked_items import TrackedItemRepository
from app.db.repositories.users import UserRepository
from app.db.session import SessionLocal, get_engine

logger = logging.getLogger(__name__)


def _parse_legacy_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.strptime(value, "%Y-%m-%d")
        return dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
        (table_name,),
    )
    return cursor.fetchone() is not None


def migrate_legacy_sqlite(legacy_db_path: Path) -> None:
    if not legacy_db_path.exists():
        return

    with SessionLocal() as session:
        existing_users = session.scalar(select(func.count(User.id)))
        if existing_users and existing_users > 0:
            return

    logger.info("Legacy database detected. Running one-time migration from %s", legacy_db_path)

    legacy_conn = sqlite3.connect(str(legacy_db_path))
    legacy_conn.row_factory = sqlite3.Row

    try:
        if not _table_exists(legacy_conn, "users"):
            logger.info("Legacy users table not found, skip migration")
            return

        rows = list(legacy_conn.execute("SELECT * FROM users"))
        if not rows:
            logger.info("Legacy database has no users")
            return

        with SessionLocal() as session:
            user_repo = UserRepository(session)
            tracked_repo = TrackedItemRepository(session)

            for row in rows:
                telegram_user_id = int(row["user_id"])
                map_link = row["map_link"]
                role = row["role"] or "user"
                is_active = bool(row["is_confirmed"])

                user = user_repo.create_or_update(
                    telegram_user_id=telegram_user_id,
                    username=None,
                    full_name=None,
                    role=role,
                    tariff_plan="trial",
                    tariff_end_at=_parse_legacy_date(row["tariff_end_date"]),
                    is_active=is_active,
                )

                if map_link:
                    tracked_repo.create(
                        user_id=user.id,
                        title="Legacy map",
                        map_link=map_link,
                        is_active=is_active,
                    )

            session.commit()
            logger.info("Legacy migration complete: %s users", len(rows))
    finally:
        legacy_conn.close()


def init_schema(migrate_legacy: bool = True, legacy_db_path: str = "users.db") -> None:
    Base.metadata.create_all(bind=get_engine())
    if migrate_legacy:
        migrate_legacy_sqlite(Path(legacy_db_path))
