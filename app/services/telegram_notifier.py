from __future__ import annotations

import logging
from pathlib import Path

from aiogram import Bot
from aiogram.types import FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup

from app.core.settings import Settings
from app.services.types import NotificationPayload

logger = logging.getLogger(__name__)


class TelegramNotifier:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._bot: Bot | None = None

        if settings.telegram_bot_token:
            self._bot = Bot(settings.telegram_bot_token)

    @property
    def enabled(self) -> bool:
        return self._bot is not None

    @staticmethod
    def _details_markup(tracked_item_id: int) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Open details", callback_data=f"item:details:{tracked_item_id}")]
            ]
        )

    async def send(self, payload: NotificationPayload) -> bool:
        if self._bot is None:
            logger.info("Notifier disabled. Skip notification event_id=%s", payload.event_id)
            return False

        text = (
            f"Change detected for tracking: {payload.tracked_item_title}\n"
            f"Type: {payload.event_type}\n"
            f"Added: {payload.added_count}\n"
            f"Removed: {payload.removed_count}\n"
            f"Snapshot ID: {payload.snapshot_id}"
        )

        markup = self._details_markup(payload.tracked_item_id)

        try:
            if payload.diff_image_path:
                diff_path = Path(payload.diff_image_path)
                if diff_path.exists():
                    await self._bot.send_photo(
                        chat_id=payload.telegram_user_id,
                        photo=FSInputFile(str(diff_path)),
                        caption=text,
                        reply_markup=markup,
                    )
                    logger.info("Notification with diff sent event_id=%s", payload.event_id)
                    return True

            await self._bot.send_message(chat_id=payload.telegram_user_id, text=text, reply_markup=markup)
            logger.info("Text notification sent event_id=%s", payload.event_id)
            return True
        except Exception:
            logger.exception("Failed to send telegram notification event_id=%s", payload.event_id)
            return False

    async def close(self) -> None:
        if self._bot is None:
            return
        await self._bot.session.close()
