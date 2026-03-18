from __future__ import annotations

import asyncio
import logging

from app.core.settings import Settings
from app.services.monitoring import MonitoringService
from app.services.telegram_notifier import TelegramNotifier

logger = logging.getLogger(__name__)


class MonitoringScheduler:
    def __init__(
        self,
        settings: Settings,
        monitoring_service: MonitoringService,
        notifier: TelegramNotifier | None = None,
    ):
        self.settings = settings
        self.monitoring_service = monitoring_service
        self.notifier = notifier

    async def run_iteration(self) -> list[dict]:
        tracked_item_ids = self.monitoring_service.list_active_tracked_item_ids()
        results = []

        for tracked_item_id in tracked_item_ids:
            result = await asyncio.to_thread(self.monitoring_service.run_for_tracked_item, tracked_item_id)
            results.append(result.as_dict())

            if result.notification_payload:
                payload = result.notification_payload
                logger.info(
                    "Notification candidate event_id=%s user=%s item=%s type=%s",
                    payload.event_id,
                    payload.telegram_user_id,
                    payload.tracked_item_id,
                    payload.event_type,
                )

                delivered = False
                if self.notifier is not None:
                    delivered = await self.notifier.send(payload)

                if delivered and payload.event_id is not None:
                    await asyncio.to_thread(self.monitoring_service.mark_notification_sent, payload.event_id)

        return results

    async def start_forever(self) -> None:
        while True:
            try:
                await self.run_iteration()
            except Exception:
                logger.exception("Scheduler iteration failed")
            await asyncio.sleep(self.settings.monitor_interval_seconds)
