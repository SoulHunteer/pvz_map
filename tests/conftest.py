from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TEST_ROOT = Path(__file__).resolve().parent / ".runtime"
TEST_ROOT.mkdir(parents=True, exist_ok=True)

os.environ["ARTIFACT_ROOT"] = str((TEST_ROOT / "artifacts").resolve())
os.environ["SCREENSHOTS_DIR"] = str((TEST_ROOT / "artifacts" / "screenshots").resolve())
os.environ["PROCESSED_DIR"] = str((TEST_ROOT / "artifacts" / "processed").resolve())
os.environ["DIFFS_DIR"] = str((TEST_ROOT / "artifacts" / "diffs").resolve())
os.environ["LOGS_DIR"] = str((TEST_ROOT / "artifacts" / "logs").resolve())
os.environ["ALLOWED_TELEGRAM_USER_IDS"] = ""
os.environ["ADMIN_TELEGRAM_USER_IDS"] = ""

from app.core.settings import get_settings
from app.db import init_schema, reconfigure_engine
from app.db.base import Base
from app.db.session import get_engine


def _prepare_test_db() -> None:
    db_path = (TEST_ROOT / "test.db").resolve()
    reconfigure_engine(f"sqlite:///{db_path}")
    init_schema(migrate_legacy=False)


_prepare_test_db()


@pytest.fixture(autouse=True)
def clean_database() -> None:
    engine = get_engine()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture()
def settings():
    get_settings.cache_clear()
    return get_settings()
