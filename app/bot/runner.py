from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from queue import Empty, Queue

from aiogram import Bot, Dispatcher, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)

from app.core.exceptions import AccessDeniedError, NotFoundError, TariffLimitError, ValidationError
from app.core.settings import Settings
from app.services.mvp import MvpService

logger = logging.getLogger(__name__)

BTN_ADD = "➕ Добавить отслеживание"
BTN_ITEMS = "📂 Мои отслеживания"
BTN_EVENTS = "🕘 История событий"
BTN_CHECKS = "🧾 История проверок"
BTN_TARIFF = "💳 Тариф"
BTN_HELP = "❓ Помощь"
BTN_SKIP_TITLE = "⏭ Пропустить"


class AddTrackingStates(StatesGroup):
    waiting_for_link = State()
    waiting_for_title = State()


class BotRunner:
    def __init__(self, settings: Settings, mvp_service: MvpService):
        if not settings.telegram_bot_token:
            raise ValueError("TELEGRAM_BOT_TOKEN is not configured")

        self.settings = settings
        self.mvp_service = mvp_service
        self.bot = Bot(token=settings.telegram_bot_token)
        self.dp = Dispatcher()
        self._register_handlers()

    def _is_allowed_user(self, telegram_user_id: int) -> bool:
        allowed = self.settings.allowed_telegram_user_ids
        return not allowed or telegram_user_id in allowed

    async def _guard_message_user(self, message: Message) -> bool:
        telegram_user_id = message.from_user.id
        if self._is_allowed_user(telegram_user_id):
            return True

        logger.warning("Bot: access denied telegram_user_id=%s", telegram_user_id)
        await message.answer("⛔ Доступ к тестовому боту закрыт.")
        return False

    async def _guard_callback_user(self, callback: CallbackQuery) -> bool:
        telegram_user_id = callback.from_user.id
        if self._is_allowed_user(telegram_user_id):
            return True

        logger.warning("Bot: callback access denied telegram_user_id=%s", telegram_user_id)
        await callback.answer("Нет доступа", show_alert=True)
        return False

    @staticmethod
    def _main_menu_markup() -> ReplyKeyboardMarkup:
        return ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text=BTN_ADD), KeyboardButton(text=BTN_ITEMS)],
                [KeyboardButton(text=BTN_EVENTS), KeyboardButton(text=BTN_CHECKS)],
                [KeyboardButton(text=BTN_TARIFF), KeyboardButton(text=BTN_HELP)],
            ],
            resize_keyboard=True,
        )

    @staticmethod
    def _skip_title_markup() -> ReplyKeyboardMarkup:
        return ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text=BTN_SKIP_TITLE)]],
            resize_keyboard=True,
            one_time_keyboard=True,
        )

    @staticmethod
    def _item_actions_markup(item_id: int, is_active: bool) -> InlineKeyboardMarkup:
        toggle_to = "0" if is_active else "1"
        toggle_text = "⏸ Выключить" if is_active else "▶️ Включить"
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="🔎 Проверить сейчас", callback_data=f"item:checkask:{item_id}"),
                    InlineKeyboardButton(text=toggle_text, callback_data=f"item:toggle:{item_id}:{toggle_to}"),
                ],
                [
                    InlineKeyboardButton(text="📄 Детали", callback_data=f"item:details:{item_id}"),
                    InlineKeyboardButton(text="🗑 Удалить", callback_data=f"item:deleteask:{item_id}"),
                ],
            ]
        )

    @staticmethod
    def _delete_confirm_markup(item_id: int) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"item:delete:{item_id}"),
                    InlineKeyboardButton(text="↩️ Отмена", callback_data=f"item:details:{item_id}"),
                ]
            ]
        )

    @staticmethod
    def _activation_markup(item_id: int) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✅ Активировать мониторинг", callback_data=f"item:activate:{item_id}")],
                [InlineKeyboardButton(text="📂 Открыть мои отслеживания", callback_data="menu:items")],
            ]
        )

    @staticmethod
    def _check_confirm_markup(item_id: int, first_check: bool = False) -> InlineKeyboardMarkup:
        run_action = "firstcheckrun" if first_check else "checkrun"
        cancel_action = "firstcheckcancel" if first_check else "checkcancel"
        run_label = "🚀 Запустить первую проверку" if first_check else "🚀 Да, запустить"

        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text=run_label, callback_data=f"item:{run_action}:{item_id}"),
                    InlineKeyboardButton(text="❌ Отмена", callback_data=f"item:{cancel_action}:{item_id}"),
                ]
            ]
        )

    @staticmethod
    def _tariff_mock_markup() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="trial", callback_data="tariff:set:trial"),
                    InlineKeyboardButton(text="free", callback_data="tariff:set:free"),
                ],
                [
                    InlineKeyboardButton(text="base", callback_data="tariff:set:base"),
                    InlineKeyboardButton(text="pro", callback_data="tariff:set:pro"),
                ],
            ]
        )

    @staticmethod
    def _format_dt(value: str | None) -> str:
        if not value:
            return "-"
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return dt.strftime("%d.%m.%Y %H:%M")
        except ValueError:
            return value

    def _format_item_card(self, item: dict) -> str:
        active = "активен" if item["is_active"] else "выключен"
        return (
            f"📍 Отслеживание: {item['title']}\n"
            f"ID: {item['id']}\n"
            f"Статус: {item['last_status']} ({active})\n"
            f"Найдено зон: {item['last_zone_count']}\n"
            f"Последняя успешная проверка: {self._format_dt(item['last_success_at'])}"
        )

    @staticmethod
    def _format_check_result(result: dict) -> str:
        if result["status"] == "error":
            return (
                "⚠️ Проверка завершилась ошибкой\n"
                f"Snapshot ID: {result.get('snapshot_id') or '-'}\n"
                f"Ошибка: {result.get('error_message') or 'unknown'}"
            )

        lines = [
            "✅ Проверка завершена",
            f"Snapshot ID: {result.get('snapshot_id')}",
            f"Статус: {result.get('status')}",
            f"Найдено зон: {result.get('zone_count', 0)}",
        ]

        if result.get("event_id"):
            lines.append(f"Event ID: {result['event_id']}")
            lines.append(f"Изменения: +{result.get('added_count', 0)} / -{result.get('removed_count', 0)}")
        return "\n".join(lines)

    @staticmethod
    def _progress_text(percent: int, status: str, done: bool = False) -> str:
        bounded = max(0, min(100, int(percent)))
        filled = max(0, min(10, round(bounded / 10)))
        bar = "█" * filled + "░" * (10 - filled)
        icon = "✅" if done else "🔄"
        title = "Проверка завершена" if done else "Проверка в процессе"
        return f"{icon} {title}\n[{bar}] {bounded}%\n{status}"

    @staticmethod
    async def _safe_edit_text(message: Message, text: str) -> None:
        try:
            await message.edit_text(text)
        except TelegramBadRequest:
            # Message may already contain same text; ignore this UX-level issue.
            return

    async def _run_check_with_progress(self, target_message: Message, telegram_user_id: int, item_id: int) -> dict:
        progress_message = await target_message.answer(self._progress_text(0, "Ожидаю старт проверки"))

        progress_queue: Queue[tuple[int, str]] = Queue()

        def progress_callback(percent: int, status: str) -> None:
            progress_queue.put((percent, status))

        check_task = asyncio.create_task(
            asyncio.to_thread(
                self.mvp_service.run_manual_check,
                telegram_user_id,
                item_id,
                progress_callback,
            )
        )

        last_progress = (-1, "")

        while True:
            latest: tuple[int, str] | None = None
            while True:
                try:
                    latest = progress_queue.get_nowait()
                except Empty:
                    break

            if latest is not None and latest != last_progress:
                last_progress = latest
                await self._safe_edit_text(progress_message, self._progress_text(latest[0], latest[1]))

            if check_task.done():
                break

            await asyncio.sleep(0.35)

        try:
            result = await check_task
        except Exception as exc:
            await self._safe_edit_text(progress_message, self._progress_text(100, f"Ошибка: {exc}", done=True))
            raise

        if result.get("status") == "error":
            final_status = f"Ошибка: {result.get('error_message') or 'unknown'}"
        else:
            final_status = "Все этапы выполнены"

        await self._safe_edit_text(progress_message, self._progress_text(100, final_status, done=True))
        return result

    async def _ensure_user(self, message: Message) -> dict:
        user = message.from_user
        return await asyncio.to_thread(
            self.mvp_service.get_or_create_user_summary,
            user.id,
            user.username,
            user.full_name,
        )

    async def _send_item_details(self, target_message: Message, telegram_user_id: int, item_id: int) -> None:
        details = await asyncio.to_thread(self.mvp_service.get_item_full_details, telegram_user_id, item_id)
        item = details["item"]
        text = self._format_item_card(item)

        snapshots = details["snapshots"]
        if snapshots:
            text += "\n\nПоследние проверки:"
            for snapshot in snapshots[:3]:
                checked_at = self._format_dt(snapshot["checked_at"])
                text += f"\n- {checked_at} | {snapshot['status']} | зон: {snapshot['zone_count']}"

        events = details["events"]
        if events:
            text += "\n\nПоследние события:"
            for event in events[:3]:
                created_at = self._format_dt(event["created_at"])
                text += (
                    f"\n- {created_at} | {event['event_type']} "
                    f"(+{event['added_count']}/-{event['removed_count']})"
                )

        await target_message.answer(text, reply_markup=self._item_actions_markup(item["id"], item["is_active"]))

    async def _create_tracking_with_first_check_confirmation(
        self,
        message: Message,
        state: FSMContext,
        title: str | None,
    ) -> None:
        data = await state.get_data()
        map_link = data.get("map_link")
        if not map_link:
            await state.clear()
            await message.answer("❌ Не удалось прочитать ссылку. Начните заново.", reply_markup=self._main_menu_markup())
            return

        user = message.from_user
        try:
            item = await asyncio.to_thread(
                self.mvp_service.create_tracked_item,
                user.id,
                map_link,
                title,
                user.username,
                user.full_name,
                False,
            )
            logger.info("Bot: tracked item created telegram_user_id=%s tracked_item_id=%s", user.id, item["id"])
        except AccessDeniedError as exc:
            await message.answer(f"⛔ Доступ запрещен: {exc}", reply_markup=self._main_menu_markup())
            await state.clear()
            return
        except TariffLimitError as exc:
            await message.answer(f"🚫 Нельзя создать отслеживание: {exc}", reply_markup=self._main_menu_markup())
            await state.clear()
            return
        except ValidationError as exc:
            await message.answer(f"⚠️ Ошибка валидации: {exc}", reply_markup=self._main_menu_markup())
            await state.clear()
            return

        await state.clear()
        await message.answer(
            (
                f"✅ Отслеживание создано: {item['title']}\n"
                "Перед первой проверкой нужно подтверждение."
            ),
            reply_markup=self._check_confirm_markup(item["id"], first_check=True),
        )

    @staticmethod
    def _zone_validation_markup(item_id: int, first_check: bool) -> InlineKeyboardMarkup:
        mode = "first" if first_check else "manual"
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="\u2705 \u041f\u043e\u0434\u0442\u0432\u0435\u0440\u0434\u0438\u0442\u044c", callback_data=f"item:zonesok:{item_id}:{mode}"),
                    InlineKeyboardButton(text="\u274c \u041e\u0442\u043c\u0435\u043d\u0438\u0442\u044c", callback_data=f"item:zonescancel:{item_id}:{mode}"),
                ]
            ]
        )

    async def _load_snapshot_for_result(
        self,
        telegram_user_id: int,
        item_id: int,
        snapshot_id: int | None,
    ) -> dict | None:
        if snapshot_id is None:
            return None

        snapshots = await asyncio.to_thread(self.mvp_service.list_item_snapshots, telegram_user_id, item_id, 10)
        for snapshot in snapshots:
            if snapshot.get("id") == snapshot_id:
                return snapshot
        return None

    async def _send_zone_validation_prompt(
        self,
        target_message: Message,
        telegram_user_id: int,
        item_id: int,
        result: dict,
        *,
        first_check: bool,
    ) -> None:
        if result.get("status") == "error":
            return

        snapshot = await self._load_snapshot_for_result(telegram_user_id, item_id, result.get("snapshot_id"))
        processed_image_path = (snapshot or {}).get("processed_image_path") if snapshot else None

        caption = (
            "\U0001f9ea \u041f\u0440\u043e\u0432\u0435\u0440\u044c\u0442\u0435 \u0440\u0430\u0437\u043c\u0435\u0442\u043a\u0443 \u0437\u043e\u043d \u043d\u0430 \u0441\u043a\u0440\u0438\u043d\u0448\u043e\u0442\u0435.\n"
            "\u0415\u0441\u043b\u0438 \u043a\u0430\u043a\u0430\u044f-\u0442\u043e \u0437\u043e\u043d\u0430 \u043d\u0435 \u043e\u0431\u0432\u0435\u043b\u0430\u0441\u044c, \u0441\u043a\u043e\u0440\u0435\u0435 \u0432\u0441\u0435\u0433\u043e \u043e\u043d\u0430 \u0441\u043b\u0438\u0448\u043a\u043e\u043c \u043c\u0430\u043b\u0435\u043d\u044c\u043a\u0430\u044f \u0434\u043b\u044f \u0442\u0435\u043a\u0443\u0449\u0438\u0445 \u043f\u0430\u0440\u0430\u043c\u0435\u0442\u0440\u043e\u0432 \u0434\u0435\u0442\u0435\u043a\u0446\u0438\u0438.\n\n"
            "\u041f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0430\u0435\u0442\u0435 \u0440\u0435\u0437\u0443\u043b\u044c\u0442\u0430\u0442?"
        )

        markup = self._zone_validation_markup(item_id, first_check=first_check)

        if processed_image_path and Path(processed_image_path).exists():
            await target_message.answer_photo(FSInputFile(processed_image_path), caption=caption, reply_markup=markup)
            return

        await target_message.answer(
            "\u26a0\ufe0f \u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u043f\u0440\u0438\u043a\u0440\u0435\u043f\u0438\u0442\u044c \u0438\u0437\u043e\u0431\u0440\u0430\u0436\u0435\u043d\u0438\u0435 \u0441 \u0440\u0430\u0437\u043c\u0435\u0442\u043a\u043e\u0439, \u043d\u043e \u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0435\u043d\u0438\u0435 \u043e\u0431\u044f\u0437\u0430\u0442\u0435\u043b\u044c\u043d\u043e.\n\n" + caption,
            reply_markup=markup,
        )

    def _register_handlers(self) -> None:
        @self.dp.message(Command("start"))
        async def cmd_start(message: Message, state: FSMContext) -> None:
            if not await self._guard_message_user(message):
                return

            await state.clear()
            summary = await self._ensure_user(message)
            logger.info("Bot: /start telegram_user_id=%s", message.from_user.id)

            text = (
                "👋 Привет! Это сервис мониторинга фиолетовых зон ПВЗ.\n"
                "Добавляйте несколько отслеживаний, получайте уведомления об изменениях и запускайте ручные проверки.\n\n"
                f"Тариф: {summary['tariff_plan']}\n"
                f"Лимит отслеживаний: {summary['tracked_items_total']}/{summary['tracked_items_limit']}"
            )
            await message.answer(text, reply_markup=self._main_menu_markup())

        @self.dp.message(Command("status"))
        async def cmd_status(message: Message) -> None:
            if not await self._guard_message_user(message):
                return

            summary = await self._ensure_user(message)
            await message.answer(
                (
                    f"💳 Тариф: {summary['tariff_plan']}\n"
                    f"📌 Лимит: {summary['tracked_items_total']}/{summary['tracked_items_limit']}\n"
                    f"⏳ Срок действия: {self._format_dt(summary['tariff_end_at'])}"
                ),
                reply_markup=self._main_menu_markup(),
            )

        @self.dp.message(F.text == BTN_HELP)
        async def help_menu(message: Message) -> None:
            if not await self._guard_message_user(message):
                return

            logger.info("Bot: help opened telegram_user_id=%s", message.from_user.id)
            text = (
                "🧭 Сценарии:\n"
                "- Добавить отслеживание: ссылка -> название -> подтверждение первой проверки\n"
                "- Мои отслеживания: проверить сейчас, включить/выключить, удалить, детали\n"
                "- История событий: последние изменения зон\n"
                "- История проверок: последние snapshot-проверки\n"
                "- Тариф: текущий план и лимиты\n"
                "Команда: /start"
            )
            await message.answer(text, reply_markup=self._main_menu_markup())

        @self.dp.message(F.text == BTN_ADD)
        async def add_tracking_start(message: Message, state: FSMContext) -> None:
            if not await self._guard_message_user(message):
                return

            await self._ensure_user(message)
            logger.info("Bot: add tracking started telegram_user_id=%s", message.from_user.id)
            await state.set_state(AddTrackingStates.waiting_for_link)
            await message.answer("🔗 Отправьте ссылку на карту для нового отслеживания.")

        @self.dp.message(AddTrackingStates.waiting_for_link)
        async def add_tracking_receive_link(message: Message, state: FSMContext) -> None:
            if not await self._guard_message_user(message):
                return

            link = (message.text or "").strip()
            if not (link.startswith("http://") or link.startswith("https://")):
                await message.answer("⚠️ Ссылка должна начинаться с http:// или https://")
                return

            await state.update_data(map_link=link)
            await state.set_state(AddTrackingStates.waiting_for_title)
            await message.answer(
                "📝 Отправьте название отслеживания или нажмите 'Пропустить'.",
                reply_markup=self._skip_title_markup(),
            )

        @self.dp.message(AddTrackingStates.waiting_for_title)
        async def add_tracking_receive_title(message: Message, state: FSMContext) -> None:
            if not await self._guard_message_user(message):
                return

            title = None if message.text == BTN_SKIP_TITLE else (message.text or "").strip()
            await self._create_tracking_with_first_check_confirmation(message, state, title)
            await message.answer("Готово. Выберите следующее действие.", reply_markup=self._main_menu_markup())

        @self.dp.message(F.text == BTN_ITEMS)
        async def list_items(message: Message) -> None:
            if not await self._guard_message_user(message):
                return

            await self._ensure_user(message)
            items = await asyncio.to_thread(self.mvp_service.list_tracked_items, message.from_user.id)
            logger.info("Bot: list items telegram_user_id=%s count=%s", message.from_user.id, len(items))
            if not items:
                await message.answer("📭 Отслеживаний пока нет. Добавьте первое.", reply_markup=self._main_menu_markup())
                return

            await message.answer(f"📂 Отслеживаний: {len(items)}", reply_markup=self._main_menu_markup())
            for item in items:
                await message.answer(
                    self._format_item_card(item),
                    reply_markup=self._item_actions_markup(item["id"], item["is_active"]),
                )

        @self.dp.message(F.text == BTN_EVENTS)
        async def event_history(message: Message) -> None:
            if not await self._guard_message_user(message):
                return

            events = await asyncio.to_thread(self.mvp_service.list_recent_events_for_user, message.from_user.id, 10)
            logger.info("Bot: events history telegram_user_id=%s count=%s", message.from_user.id, len(events))
            if not events:
                await message.answer("🕘 Событий пока нет.", reply_markup=self._main_menu_markup())
                return

            lines = ["🕘 Последние события:"]
            for event in events:
                lines.append(
                    (
                        f"- {self._format_dt(event['created_at'])} | {event['tracked_item_title']} | "
                        f"{event['event_type']} (+{event['added_count']}/-{event['removed_count']})"
                    )
                )
            await message.answer("\n".join(lines), reply_markup=self._main_menu_markup())

        @self.dp.message(F.text == BTN_CHECKS)
        async def checks_history(message: Message) -> None:
            if not await self._guard_message_user(message):
                return

            snapshots = await asyncio.to_thread(self.mvp_service.list_recent_snapshots_for_user, message.from_user.id, 10)
            logger.info("Bot: checks history telegram_user_id=%s count=%s", message.from_user.id, len(snapshots))
            if not snapshots:
                await message.answer("🧾 Проверок пока нет.", reply_markup=self._main_menu_markup())
                return

            lines = ["🧾 Последние проверки:"]
            for snapshot in snapshots:
                line = (
                    f"- {self._format_dt(snapshot['checked_at'])} | {snapshot['tracked_item_title']} | "
                    f"{snapshot['status']} | зон: {snapshot['zone_count']}"
                )
                if snapshot.get("error_message"):
                    line += f" | ошибка: {snapshot['error_message']}"
                lines.append(line)

            await message.answer("\n".join(lines), reply_markup=self._main_menu_markup())

        @self.dp.message(F.text == BTN_TARIFF)
        async def tariff_info(message: Message) -> None:
            if not await self._guard_message_user(message):
                return

            summary = await self._ensure_user(message)
            logger.info("Bot: tariff info telegram_user_id=%s", message.from_user.id)

            text = (
                "💳 Информация по тарифу:\n"
                f"- План: {summary['tariff_plan']}\n"
                f"- Лимит: {summary['tracked_items_limit']}\n"
                f"- Использовано: {summary['tracked_items_total']}\n"
                f"- Срок действия: {self._format_dt(summary['tariff_end_at'])}\n\n"
                "MVP-режим: тариф можно переключить мок-кнопками ниже."
            )
            await message.answer(text, reply_markup=self._tariff_mock_markup())

        @self.dp.callback_query(F.data == "menu:items")
        async def callback_menu_items(callback: CallbackQuery) -> None:
            if not await self._guard_callback_user(callback):
                return

            await callback.answer()
            await callback.message.answer(BTN_ITEMS, reply_markup=self._main_menu_markup())

        @self.dp.callback_query(F.data.startswith("tariff:set:"))
        async def callback_set_tariff(callback: CallbackQuery) -> None:
            if not await self._guard_callback_user(callback):
                return

            plan = callback.data.split(":", 2)[2]
            days = 30 if plan in {"base", "pro"} else None
            summary = await asyncio.to_thread(self.mvp_service.set_mock_tariff, callback.from_user.id, plan, days)
            logger.info("Bot: tariff changed telegram_user_id=%s plan=%s", callback.from_user.id, plan)
            await callback.answer("Тариф обновлен")
            await callback.message.answer(
                (
                    f"✅ Тариф изменен: {summary['tariff_plan']}\n"
                    f"Лимит: {summary['tracked_items_total']}/{summary['tracked_items_limit']}\n"
                    f"Срок действия: {self._format_dt(summary['tariff_end_at'])}"
                ),
                reply_markup=self._main_menu_markup(),
            )

        @self.dp.callback_query(F.data.startswith("item:"))
        async def callback_item_actions(callback: CallbackQuery) -> None:
            if not await self._guard_callback_user(callback):
                return

            await callback.answer()
            payload = (callback.data or "").split(":")
            if len(payload) < 3:
                return

            action = payload[1]
            item_id = int(payload[2])
            telegram_user_id = callback.from_user.id

            try:
                if action == "checkask":
                    await callback.message.answer(
                        "❔ Подтвердите запуск ручной проверки.",
                        reply_markup=self._check_confirm_markup(item_id, first_check=False),
                    )
                    return

                if action == "checkcancel":
                    await callback.message.answer("Ручная проверка отменена.")
                    return

                if action == "checkrun":
                    logger.info("Bot: manual check telegram_user_id=%s tracked_item_id=%s", telegram_user_id, item_id)
                    result = await self._run_check_with_progress(callback.message, telegram_user_id, item_id)
                    await callback.message.answer(self._format_check_result(result))
                    await self._send_zone_validation_prompt(
                        callback.message,
                        telegram_user_id,
                        item_id,
                        result,
                        first_check=False,
                    )
                    return

                if action == "firstcheckrun":
                    logger.info("Bot: first check telegram_user_id=%s tracked_item_id=%s", telegram_user_id, item_id)
                    result = await self._run_check_with_progress(callback.message, telegram_user_id, item_id)
                    await callback.message.answer(self._format_check_result(result))
                    await self._send_zone_validation_prompt(
                        callback.message,
                        telegram_user_id,
                        item_id,
                        result,
                        first_check=True,
                    )
                    return

                if action == "firstcheckcancel":
                    await callback.message.answer(
                        "\u23f9 \u041f\u0435\u0440\u0432\u0430\u044f \u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0430 \u043e\u0442\u043c\u0435\u043d\u0435\u043d\u0430. \u041e\u0442\u0441\u043b\u0435\u0436\u0438\u0432\u0430\u043d\u0438\u0435 \u0441\u043e\u0437\u0434\u0430\u043d\u043e, \u043d\u043e \u043f\u043e\u043a\u0430 \u043d\u0435 \u0430\u043a\u0442\u0438\u0432\u0438\u0440\u043e\u0432\u0430\u043d\u043e.",
                        reply_markup=self._main_menu_markup(),
                    )
                    return

                if action == "zonesok":
                    mode = payload[3] if len(payload) > 3 else "manual"
                    if mode == "first":
                        await callback.message.answer(
                            "\u2705 \u0420\u0430\u0437\u043c\u0435\u0442\u043a\u0430 \u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0435\u043d\u0430. \u0422\u0435\u043f\u0435\u0440\u044c \u043c\u043e\u0436\u043d\u043e \u0430\u043a\u0442\u0438\u0432\u0438\u0440\u043e\u0432\u0430\u0442\u044c \u043c\u043e\u043d\u0438\u0442\u043e\u0440\u0438\u043d\u0433.",
                            reply_markup=self._activation_markup(item_id),
                        )
                    else:
                        item = await asyncio.to_thread(self.mvp_service.get_tracked_item, telegram_user_id, item_id)
                        await callback.message.answer(
                            "\u2705 \u0420\u0430\u0437\u043c\u0435\u0442\u043a\u0430 \u0440\u0443\u0447\u043d\u043e\u0439 \u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0438 \u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0435\u043d\u0430.",
                            reply_markup=self._item_actions_markup(item["id"], item["is_active"]),
                        )
                    return

                if action == "zonescancel":
                    mode = payload[3] if len(payload) > 3 else "manual"
                    if mode == "first":
                        await callback.message.answer(
                            "\u274c \u041f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0435\u043d\u0438\u0435 \u043e\u0442\u043a\u043b\u043e\u043d\u0435\u043d\u043e. \u041e\u0442\u0441\u043b\u0435\u0436\u0438\u0432\u0430\u043d\u0438\u0435 \u043e\u0441\u0442\u0430\u043d\u0435\u0442\u0441\u044f \u043d\u0435\u0430\u043a\u0442\u0438\u0432\u043d\u044b\u043c.",
                            reply_markup=self._main_menu_markup(),
                        )
                    else:
                        item = await asyncio.to_thread(self.mvp_service.get_tracked_item, telegram_user_id, item_id)
                        await callback.message.answer(
                            "\u274c \u0420\u0430\u0437\u043c\u0435\u0442\u043a\u0430 \u043e\u0442\u043a\u043b\u043e\u043d\u0435\u043d\u0430. \u0417\u0430\u043f\u0443\u0441\u0442\u0438\u0442\u0435 \u043f\u043e\u0432\u0442\u043e\u0440\u043d\u0443\u044e \u0440\u0443\u0447\u043d\u0443\u044e \u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0443.",
                            reply_markup=self._item_actions_markup(item["id"], item["is_active"]),
                        )
                    return

                if action == "toggle":
                    target_value = payload[3] if len(payload) > 3 else "1"
                    is_active = target_value == "1"
                    item = await asyncio.to_thread(self.mvp_service.activate_item, telegram_user_id, item_id, is_active)
                    logger.info(
                        "Bot: toggle item telegram_user_id=%s tracked_item_id=%s active=%s",
                        telegram_user_id,
                        item_id,
                        is_active,
                    )
                    await callback.message.answer(
                        f"Статус обновлен: {'активен' if item['is_active'] else 'выключен'}",
                        reply_markup=self._item_actions_markup(item["id"], item["is_active"]),
                    )
                    return

                if action == "deleteask":
                    await callback.message.answer(
                        "❔ Подтвердите удаление.",
                        reply_markup=self._delete_confirm_markup(item_id),
                    )
                    return

                if action == "delete":
                    await asyncio.to_thread(self.mvp_service.delete_tracked_item, telegram_user_id, item_id)
                    logger.info("Bot: delete item telegram_user_id=%s tracked_item_id=%s", telegram_user_id, item_id)
                    await callback.message.answer("🗑 Отслеживание удалено.", reply_markup=self._main_menu_markup())
                    return

                if action in {"details", "activate"}:
                    if action == "activate":
                        await asyncio.to_thread(self.mvp_service.activate_item, telegram_user_id, item_id, True)
                        logger.info("Bot: activate item telegram_user_id=%s tracked_item_id=%s", telegram_user_id, item_id)
                    await self._send_item_details(callback.message, telegram_user_id, item_id)
                    return

            except AccessDeniedError as exc:
                await callback.message.answer(f"⛔ Доступ запрещен: {exc}")
            except TariffLimitError as exc:
                await callback.message.answer(f"🚫 Ограничение тарифа: {exc}")
            except NotFoundError:
                await callback.message.answer("Отслеживание не найдено.")
            except ValidationError as exc:
                await callback.message.answer(f"⚠️ Ошибка валидации: {exc}")
            except Exception:
                logger.exception("Bot callback failed action=%s item_id=%s", action, item_id)
                await callback.message.answer("Внутренняя ошибка при выполнении действия.")

        @self.dp.message()
        async def fallback(message: Message) -> None:
            if not await self._guard_message_user(message):
                return

            await message.answer("Выберите действие из меню.", reply_markup=self._main_menu_markup())

    async def start(self) -> None:
        logger.info("Bot polling started")
        await self.dp.start_polling(self.bot)

    async def close(self) -> None:
        await self.bot.session.close()
