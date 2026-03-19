from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    app_env: str
    log_level: str
    database_url: str

    artifact_root: Path
    screenshots_dir: Path
    processed_dir: Path
    diffs_dir: Path
    logs_dir: Path

    monitor_interval_seconds: int
    enable_scheduler: bool
    enable_bot: bool

    selenium_page_load_timeout_seconds: int
    selenium_wait_timeout_seconds: int
    chrome_headless: bool
    chrome_binary_path: str | None
    chromedriver_path: str | None

    telegram_bot_token: str | None

    api_host: str
    api_port: int
    api_cors_origins: tuple[str, ...]
    dev_auth_enabled: bool
    allowed_telegram_user_ids: tuple[int, ...]
    admin_telegram_user_ids: tuple[int, ...]
    admin_bypass_tariff_limits: bool

    cv_target_bgr: tuple[int, int, int]
    cv_tolerance: int
    cv_morph_kernel_size: int
    cv_min_area: float
    cv_min_perimeter: float
    cv_min_compactness: float
    cv_max_compactness: float

    cv_mask_mode: str
    cv_hue_min: int
    cv_hue_max: int
    cv_sat_min: int
    cv_sat_max: int
    cv_val_min: int
    cv_val_max: int

    zone_match_max_centroid_distance: float
    zone_match_min_iou: float
    zone_match_max_area_delta_ratio: float

    max_items_trial_free: int
    max_items_base: int
    max_items_pro: int

    # Backward compatible names from phase 1
    max_active_items_free: int
    max_active_items_pro: int

    trial_days: int


def _get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _get_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    return int(value)


def _get_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    return float(value)


def _get_path(name: str, default: str) -> Path:
    value = os.getenv(name, default)
    path = Path(value)
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    return path


def _get_str_tuple(name: str, default: tuple[str, ...] = ()) -> tuple[str, ...]:
    value = os.getenv(name)
    if value is None:
        return default

    chunks = [item.strip() for item in value.split(",")]
    items = [item for item in chunks if item]
    if not items:
        return default

    return tuple(dict.fromkeys(items))


def _get_int_tuple(name: str, default: tuple[int, ...] = ()) -> tuple[int, ...]:
    value = os.getenv(name)
    if value is None:
        return default

    chunks = [item.strip() for item in value.split(",")]
    numbers = [int(item) for item in chunks if item]
    if not numbers:
        return default

    # Preserve order but drop duplicates.
    return tuple(dict.fromkeys(numbers))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    load_dotenv()

    artifact_root = _get_path("ARTIFACT_ROOT", "data")
    screenshots_dir = _get_path("SCREENSHOTS_DIR", str(artifact_root / "screenshots"))
    processed_dir = _get_path("PROCESSED_DIR", str(artifact_root / "processed"))
    diffs_dir = _get_path("DIFFS_DIR", str(artifact_root / "diffs"))
    logs_dir = _get_path("LOGS_DIR", str(artifact_root / "logs"))

    max_items_trial_free = _get_int("MAX_ITEMS_TRIAL_FREE", _get_int("MAX_ACTIVE_ITEMS_FREE", 1))
    max_items_pro = _get_int("MAX_ITEMS_PRO", _get_int("MAX_ACTIVE_ITEMS_PRO", 20))

    settings = Settings(
        app_env=os.getenv("APP_ENV", "development"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        database_url=os.getenv("DATABASE_URL", "sqlite:///data/app.db"),
        artifact_root=artifact_root,
        screenshots_dir=screenshots_dir,
        processed_dir=processed_dir,
        diffs_dir=diffs_dir,
        logs_dir=logs_dir,
        monitor_interval_seconds=_get_int("MONITOR_INTERVAL_SECONDS", 120),
        enable_scheduler=_get_bool("ENABLE_SCHEDULER", True),
        enable_bot=_get_bool("ENABLE_BOT", True),
        selenium_page_load_timeout_seconds=_get_int("SELENIUM_PAGE_LOAD_TIMEOUT_SECONDS", 25),
        selenium_wait_timeout_seconds=_get_int("SELENIUM_WAIT_TIMEOUT_SECONDS", 20),
        chrome_headless=_get_bool("CHROME_HEADLESS", True),
        chrome_binary_path=os.getenv("CHROME_BINARY_PATH"),
        chromedriver_path=os.getenv("CHROMEDRIVER_PATH"),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN"),
        api_host=os.getenv("API_HOST", "0.0.0.0"),
        api_port=_get_int("API_PORT", 8000),
        api_cors_origins=_get_str_tuple("API_CORS_ORIGINS", ("http://localhost:5173", "http://localhost:3000")),
        dev_auth_enabled=_get_bool("DEV_AUTH_ENABLED", True),
        allowed_telegram_user_ids=_get_int_tuple("ALLOWED_TELEGRAM_USER_IDS", ()),
        admin_telegram_user_ids=_get_int_tuple("ADMIN_TELEGRAM_USER_IDS", ()),
        admin_bypass_tariff_limits=_get_bool("ADMIN_BYPASS_TARIFF_LIMITS", True),
        cv_target_bgr=(
            _get_int("CV_TARGET_BGR_B", 207),
            _get_int("CV_TARGET_BGR_G", 109),
            _get_int("CV_TARGET_BGR_R", 202),
        ),
        cv_tolerance=_get_int("CV_TOLERANCE", 28),
        cv_morph_kernel_size=_get_int("CV_MORPH_KERNEL_SIZE", 3),
        cv_min_area=_get_float("CV_MIN_AREA", 40.0),
        cv_min_perimeter=_get_float("CV_MIN_PERIMETER", 20.0),
        cv_min_compactness=_get_float("CV_MIN_COMPACTNESS", 0.03),
        cv_max_compactness=_get_float("CV_MAX_COMPACTNESS", 0.86),
        cv_mask_mode=os.getenv("CV_MASK_MODE", "bgr").lower(),
        cv_hue_min=_get_int("CV_HUE_MIN", 118),
        cv_hue_max=_get_int("CV_HUE_MAX", 179),
        cv_sat_min=_get_int("CV_SAT_MIN", 8),
        cv_sat_max=_get_int("CV_SAT_MAX", 240),
        cv_val_min=_get_int("CV_VAL_MIN", 85),
        cv_val_max=_get_int("CV_VAL_MAX", 255),
        zone_match_max_centroid_distance=_get_float("ZONE_MATCH_MAX_CENTROID_DISTANCE", 32.0),
        zone_match_min_iou=_get_float("ZONE_MATCH_MIN_IOU", 0.08),
        zone_match_max_area_delta_ratio=_get_float("ZONE_MATCH_MAX_AREA_DELTA_RATIO", 0.55),
        max_items_trial_free=max_items_trial_free,
        max_items_base=_get_int("MAX_ITEMS_BASE", 5),
        max_items_pro=max_items_pro,
        max_active_items_free=max_items_trial_free,
        max_active_items_pro=max_items_pro,
        trial_days=_get_int("TRIAL_DAYS", 3),
    )

    ensure_directories(settings)
    return settings


def ensure_directories(settings: Settings) -> None:
    settings.artifact_root.mkdir(parents=True, exist_ok=True)
    settings.screenshots_dir.mkdir(parents=True, exist_ok=True)
    settings.processed_dir.mkdir(parents=True, exist_ok=True)
    settings.diffs_dir.mkdir(parents=True, exist_ok=True)
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
