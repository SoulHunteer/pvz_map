from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from app.core.settings import get_settings

SessionLocal = sessionmaker(autoflush=False, autocommit=False, expire_on_commit=False)
_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(settings.database_url, future=True)
        SessionLocal.configure(bind=_engine)
    return _engine


def reconfigure_engine(database_url: str) -> Engine:
    global _engine
    if _engine is not None:
        _engine.dispose()
    _engine = create_engine(database_url, future=True)
    SessionLocal.configure(bind=_engine)
    return _engine


engine = get_engine()
