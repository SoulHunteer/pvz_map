from __future__ import annotations

import asyncio
import logging
import os

from app.bot import BotRunner
from app.core import get_settings, setup_logging
from app.db.init_db import init_schema
from app.scheduler import MonitoringScheduler
from app.services.monitoring import MonitoringService
from app.services.mvp import MvpService
from app.services.telegram_notifier import TelegramNotifier

logger = logging.getLogger(__name__)


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


async def run() -> None:
    settings = get_settings()
    setup_logging(settings)

    logger.info("Initializing backend schema")
    init_schema(migrate_legacy=True)

    monitoring_service = MonitoringService(settings)
    mvp_service = MvpService(settings, monitoring_service=monitoring_service)
    notifier = TelegramNotifier(settings)
    scheduler = MonitoringScheduler(settings, monitoring_service, notifier=notifier)

    run_once = _env_bool("RUN_ONCE", False)
    if run_once:
        logger.info("RUN_ONCE enabled. Executing single scheduler iteration")
        await scheduler.run_iteration()
        await notifier.close()
        return

    tasks: list[asyncio.Task] = []
    bot_runner: BotRunner | None = None

    if settings.enable_scheduler:
        logger.info("Scheduler enabled. Interval=%ss", settings.monitor_interval_seconds)
        tasks.append(asyncio.create_task(scheduler.start_forever(), name="scheduler"))

    if settings.enable_bot:
        if settings.telegram_bot_token:
            logger.info("Telegram bot enabled")
            bot_runner = BotRunner(settings, mvp_service)
            tasks.append(asyncio.create_task(bot_runner.start(), name="bot"))
        else:
            logger.warning("ENABLE_BOT=true but TELEGRAM_BOT_TOKEN is missing. Bot is not started.")

    if not tasks:
        logger.warning("Nothing to run: both scheduler and bot are disabled")
        await notifier.close()
        return

    try:
        await asyncio.gather(*tasks)
    finally:
        if bot_runner is not None:
            await bot_runner.close()
        await notifier.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
