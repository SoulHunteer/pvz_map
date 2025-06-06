import logging
import sqlite3
from datetime import datetime, timedelta
import asyncio
import aiosqlite
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import cv2
import numpy as np
import os
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor
import time

load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()

# Пул потоков для CPU-bound задач
executor = ThreadPoolExecutor(max_workers=4)
selenium_executor = ThreadPoolExecutor(max_workers=2)

COLOR_LEGEND = (
    "🎨 Цветовая легенда:\n"
    "🟢 Зеленый - текущие зоны\n"
    "🔴 Красный - новые зоны\n"
    "⚫ Черный - удаленные зоны"
)


# Инициализация базы данных
async def init_db():
    """
    Инициализирует базу данных SQLite
    Создает таблицы users и pixel_zones при первом запуске
    """
    logger.info("Инициализация базы данных...")
    async with aiosqlite.connect('users.db') as conn:
        try:
            await conn.execute('''CREATE TABLE IF NOT EXISTS users (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                user_id INTEGER NOT NULL UNIQUE,
                                role TEXT NOT NULL DEFAULT 'user',
                                map_link TEXT,
                                tariff_end_date TEXT,
                                is_confirmed BOOLEAN NOT NULL DEFAULT FALSE,
                                notified BOOLEAN NOT NULL DEFAULT FALSE
                            )''')

            await conn.execute('''CREATE TABLE IF NOT EXISTS pixel_zones (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                x INTEGER NOT NULL,
                                y INTEGER NOT NULL,
                                radius INTEGER NOT NULL,
                                user_id INTEGER,
                                FOREIGN KEY (user_id) REFERENCES users(user_id),
                                UNIQUE(x, y, radius, user_id)
                            )''')

            await conn.commit()
            logger.info("База данных успешно инициализирована")
        except Exception as e:
            logger.error(f"Ошибка инициализации БД: {str(e)}")


# Добавление/обновление пользователя
async def save_user(user_id, **kwargs):
    """
    Сохраняет или обновляет данные пользователя в БД

    Параметры:
    user_id (int): Идентификатор пользователя Telegram
    kwargs: Дополнительные параметры для обновления:
        - map_link (str): Ссылка на карту
        - tariff_end_date (str): Дата окончания подписки
        - is_confirmed (bool): Подтверждение активации
        - notified (bool): Флаг отправки уведомления
    """
    logger.info(f"Сохранение пользователя {user_id}: {kwargs}")
    async with aiosqlite.connect('users.db') as conn:
        cursor = await conn.cursor()
        try:
            await cursor.execute("SELECT map_link FROM users WHERE user_id = ?", (user_id,))
            existing_user = await cursor.fetchone()

            if existing_user and 'map_link' in kwargs and existing_user[0] != kwargs['map_link']:
                logger.info(f"Обновление карты для пользователя {user_id}")
                await delete_all_zones_for_user(user_id)

            if not existing_user:
                default_end_date = datetime.now() + timedelta(days=3)
                await cursor.execute(
                    "INSERT INTO users (user_id, map_link, tariff_end_date) VALUES (?, ?, ?)",
                    (user_id, kwargs.get('map_link', ""), default_end_date.strftime('%Y-%m-%d'))
                )

            updates = []
            params = []
            for key, value in kwargs.items():
                if value is not None:
                    updates.append(f"{key} = ?")
                    params.append(value)

            if updates:
                update_query = f"UPDATE users SET {', '.join(updates)} WHERE user_id = ?"
                params.append(user_id)
                await cursor.execute(update_query, params)

            await conn.commit()
        except Exception as e:
            logger.error(f"Ошибка сохранения пользователя {user_id}: {str(e)}")


async def check_subscription(user_id):
    async with aiosqlite.connect('users.db') as conn:
        cursor = await conn.cursor()
        await cursor.execute('''SELECT tariff_end_date, notified, is_confirmed 
                              FROM users 
                              WHERE user_id = ?''', (user_id,))
        result = await cursor.fetchone()

    if not result:
        return True

    end_date, notified, is_confirmed = result
    if end_date and datetime.strptime(end_date, '%Y-%m-%d') < datetime.now():
        await bot.send_message(user_id, "🚫 Подписка истекла! Для продления свяжитесь с администратором.")
        await save_user(user_id, notified=True)
        return False
    return True


# Сохранение зон в БД
async def save_zones_to_db(user_id, zones):
    """
    Сохраняет обнаруженные зоны в базу данных

    Параметры:
    user_id (int): Идентификатор пользователя Telegram
    zones (list): Список словарей с координатами зон

    Возвращает:
    None
    """
    logger.info(f"Сохранение {len(zones)} зон для пользователя {user_id}")
    async with aiosqlite.connect('users.db') as conn:
        try:
            for zone in zones:
                await conn.execute(
                    "INSERT OR IGNORE INTO pixel_zones (x, y, radius, user_id) VALUES (?, ?, ?, ?)",
                    (zone['x'], zone['y'], zone['radius'], user_id)
                )
            await conn.commit()
            logger.info(f"Успешно сохранено зон: {len(zones)}")
        except Exception as e:
            logger.error(f"Ошибка сохранения зон для {user_id}: {str(e)}")


# Удаление зон из БД
async def delete_zones_from_db(user_id, zones):
    """
    Удаляет указанные зоны из базы данных

    Параметры:
    user_id (int): Идентификатор пользователя Telegram
    zones (set): Множество кортежей (x, y, radius) для удаления

    Возвращает:
    None
    """
    logger.info(f"Удаление {len(zones)} зон для пользователя {user_id}")
    async with aiosqlite.connect('users.db') as conn:
        try:
            for (x, y, radius) in zones:
                await conn.execute(
                    "DELETE FROM pixel_zones WHERE user_id = ? AND x = ? AND y = ? AND radius = ?",
                    (user_id, x, y, radius)
                )
            await conn.commit()
            logger.info(f"Успешно удалено зон: {len(zones)}")
        except Exception as e:
            logger.error(f"Ошибка удаления зон для {user_id}: {str(e)}")


async def delete_all_zones_for_user(user_id):
    """
    Удаляет все зоны, связанные с указанным пользователем

    Параметры:
    user_id (int): Идентификатор пользователя Telegram

    Возвращает:
    None
    """
    logger.info(f"Удаление всех зон для пользователя {user_id}")
    async with aiosqlite.connect('users.db') as conn:
        try:
            await conn.execute("DELETE FROM pixel_zones WHERE user_id = ?", (user_id,))
            await conn.commit()
        except Exception as e:
            logger.error(f"Ошибка удаления зон для {user_id}: {str(e)}")


# Получение зон из БД
async def get_user_zones(user_id):
    """
    Получает сохраненные зоны пользователя из базы данных

    Параметры:
    user_id (int): Идентификатор пользователя Telegram

    Возвращает:
    list: Список словарей с координатами зон
    """
    logger.info(f"Получение зон для пользователя {user_id}")
    async with aiosqlite.connect('users.db') as conn:
        cursor = await conn.cursor()
        try:
            await cursor.execute("SELECT x, y, radius FROM pixel_zones WHERE user_id = ?", (user_id,))
            result = await cursor.fetchall()
            return [{'x': row[0], 'y': row[1], 'radius': row[2]} for row in result]
        except Exception as e:
            logger.error(f"Ошибка получения зон для {user_id}: {str(e)}")
            return []


def is_zone_similar(z1, z2):
    """Проверка схожести зон с погрешностью 1px"""
    return (abs(z1['x'] - z2['x']) <= 1 and
            abs(z1['y'] - z2['y']) <= 1 and
            abs(z1['radius'] - z2['radius']) <= 1)


# Сравнение зон с погрешностью в 1 пиксель
def compare_zones(old_zones, new_zones):
    """
    Сравнивает два набора зон с учетом погрешности в 1 пиксель

    Параметры:
    old_zones (list): Предыдущий набор зон
    new_zones (list): Новый набор зон

    Возвращает:
    tuple: (added_set, removed_set) - множества добавленных и удаленных зон
    """
    logger.info("Сравнение зон")
    added = []
    removed = []

    # Ищем новые зоны
    for new_zone in new_zones:
        if not any(is_zone_similar(new_zone, old_zone) for old_zone in old_zones):
            added.append(new_zone)

    # Ищем удаленные зоны
    for old_zone in old_zones:
        if not any(is_zone_similar(old_zone, new_zone) for new_zone in new_zones):
            removed.append(old_zone)

    return added, removed


# Инициализация драйвера
def init_driver():
    """
    Инициализирует headless Chrome драйвер для Selenium

    Возвращает:
    WebDriver: Экземпляр Chrome WebDriver
    """
    logger.info("Инициализация Chrome драйвера")
    try:
        chrome_options = webdriver.ChromeOptions()
        chrome_options.add_argument('--headless')
        chrome_options.add_argument('--disable-gpu')
        driver = webdriver.Chrome(options=chrome_options)
        logger.info("Драйвер успешно инициализирован")
        return driver
    except Exception as e:
        logger.critical(f"Ошибка инициализации драйвера: {str(e)}")
        raise


def close_notifications(driver):
    """Закрытие всплывающих уведомлений"""
    try:
        notifications = WebDriverWait(driver, 15).until(
            EC.presence_of_all_elements_located(
                (By.CSS_SELECTOR, '.ant-notification-notice-close')
            )
        )
        for close_button in notifications:
            try:
                driver.execute_script("arguments[0].click();", close_button)
                time.sleep(0.5)
            except Exception as e:
                logger.warning(f"Не удалось закрыть уведомление: {str(e)}")
    except Exception as e:
        logger.info("Всплывающие уведомления не найдены")


# Обработка карты
def process_map_sync(map_link, user_id):
    """
    Обрабатывает карту по указанной ссылке

    Параметры:
    map_link (str): URL-адрес карты
    user_id: User id

    Возвращает:
    tuple: (screenshot_path, zones, original_path)
    """
    logger.info(f"Обработка карты: {map_link}")
    driver = init_driver()
    try:
        driver.get(map_link)

        # Ожидание полной загрузки страницы
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.TAG_NAME, 'body'))
        )

        # Закрытие попапа
        try:
            close_button = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.CLASS_NAME, 'ant-drawer-close'))
            )
            close_button.click()
            time.sleep(5)
            # close_notifications(driver)
        except Exception as e:
            logger.warning(f"Не удалось закрыть попап: {str(e)}")

        # Создание скриншота
        screenshot = take_screenshot(driver)

        # Проверка валидности изображения
        if not isinstance(screenshot, np.ndarray):
            raise ValueError("Invalid screenshot format")

        # Сохранение файлов
        original_path = f'original_{user_id}.png'
        processed_path = f'processed_{user_id}.png'

        cv2.imwrite(original_path, screenshot)

        # Обработка зон
        zones = process_image(screenshot)
        save_image_with_zones(screenshot.copy(), zones, processed_path)

        return processed_path, zones, original_path

    except Exception as e:
        logger.error(f"Ошибка обработки карты: {str(e)}")
        raise
    finally:
        driver.quit()


# Скриншот страницы
def take_screenshot(driver):
    """
    Делает скриншот текущей страницы

    Параметры:
    driver (WebDriver): Экземпляр Selenium WebDriver

    Возвращает:
    tuple: (image, window_size)
    """
    logger.info("Создание скриншота страницы")
    try:
        driver.set_window_size(1280, 720)
        time.sleep(1)  # Даем время для применения размера

        # Получаем скриншот как PNG
        screenshot_data = driver.get_screenshot_as_png()

        # Конвертируем в numpy array
        nparr = np.frombuffer(screenshot_data, np.uint8)

        # Декодируем изображение
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if img is None:
            raise ValueError("Failed to decode screenshot image")

        return img
    except Exception as e:
        logger.error(f"Ошибка создания скриншота: {str(e)}")
        raise


# Обработка изображения
def process_image(image):
    """
    Обрабатывает изображение для обнаружения зон

    Параметры:
    image (numpy.ndarray): Входное изображение в формате OpenCV

    Возвращает:
    list: Список обнаруженных зон
    """
    logger.info("Обработка изображения")
    try:
        target_color = np.array([170, 110, 190], dtype=np.uint8)
        lower_target = np.array([target_color[0] - 25, target_color[1] - 25, target_color[2] - 25], dtype=np.uint8)
        upper_target = np.array([target_color[0] + 25, target_color[1] + 25, target_color[2] + 25], dtype=np.uint8)
        purple_mask = cv2.inRange(image, lower_target, upper_target)
        contours, _ = cv2.findContours(purple_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        zones = []
        for contour in contours:
            (x, y), radius = cv2.minEnclosingCircle(contour)
            center = (int(x), int(y))
            radius = int(radius)
            if radius < 20:
                continue
            zones.append({'x': center[0], 'y': center[1], 'radius': radius})
        return zones
    except Exception as e:
        logger.error(f"Ошибка обработки изображения: {str(e)}")
        raise


# Сохранение изображения с зонами
def save_image_with_zones(image, zones, path):
    """
    Сохраняет изображение с отмеченными зонами

    Параметры:
    image (numpy.ndarray): Исходное изображение
    zones (list): Список зон для отрисовки

    Возвращает:
    None
    """
    logger.info("Сохранение изображения с зонами")
    try:
        for zone in zones:
            cv2.circle(image, (zone['x'], zone['y']), zone['radius'], (0, 255, 0), 2)
        cv2.imwrite(path, image)
    except Exception as e:
        logger.error(f"Ошибка сохранения изображения: {str(e)}")
        raise


# Асинхронные обертки для синхронных функций
async def run_in_threadpool(executor, func, *args):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, func, *args)


async def process_map_async(map_link, user_id):
    return await run_in_threadpool(selenium_executor, process_map_sync, map_link, user_id)


# Фоновая проверка зон
async def background_check():
    """
    Фоновая задача для периодической проверки изменений зон
    Запускается каждые 30 секунд
    """
    logger.info("Запуск фоновой проверки")
    while True:
        try:
            async with aiosqlite.connect('users.db') as conn:
                cursor = await conn.cursor()
                await cursor.execute('''SELECT user_id, map_link 
                                          FROM users 
                                          WHERE is_confirmed = TRUE 
                                          AND notified = FALSE''')
                users = await cursor.fetchall()

                for user_id, map_link in users:
                    try:
                        old_zones = await get_user_zones(user_id)
                        processed_path, new_zones, original_path = await process_map_async(map_link, user_id)

                        # Проверка на аномальное уменьшение зон
                        if (len(old_zones) != 0 and len(new_zones) == 0) or len(new_zones) < len(old_zones) * 0.9:
                            logger.warning(f"Обнаружено резкое уменьшение зон у {user_id}")
                            # await bot.send_message(
                            #     user_id,
                            #     "⚠️ Обнаружено аномальное изменение зон. Проверка пропущена."
                            # )
                            continue

                        added, removed = compare_zones(old_zones, new_zones)

                        if added or removed:
                            diff_path = await run_in_threadpool(
                                executor,
                                generate_diff_image,
                                user_id,
                                new_zones,
                                added,
                                removed
                            )

                            with open(diff_path, 'rb') as photo:
                                await bot.send_photo(
                                    user_id,
                                    types.BufferedInputFile(photo.read(), filename="changes.png"),
                                    caption=f"🔔 Обнаружены изменения!\n"
                                            f"➕ Новых зон: {len(added)}\n"
                                            f"➖ Удаленных зон: {len(removed)}"
                                )

                        await save_zones_to_db(user_id, new_zones)
                        await delete_zones_from_db(user_id, {(z['x'], z['y'], z['radius']) for z in removed})

                    except Exception as e:
                        logger.error(f"User {user_id} check error: {str(e)}")

        except Exception as e:
            logger.error(f"Background check error: {str(e)}")

        await asyncio.sleep(120)


def generate_diff_image(user_id, new_zones, added, removed):
    """Генерация изображения с визуализацией изменений"""
    original_path = f'original_{user_id}.png'
    diff_path = f'diff_{user_id}.png'

    if not os.path.exists(original_path):
        return None

    img = cv2.imread(original_path)

    # 1. Рисуем новые зоны
    for zone in new_zones:
        color = (0, 255, 0)  # Зеленый по умолчанию
        if any(is_zone_similar(zone, a) for a in added):
            color = (0, 0, 255)  # Красный для новых
        cv2.circle(img, (zone['x'], zone['y']), zone['radius'], color, 2)

    # 2. Рисуем удаленные зоны поверх
    for zone in removed:
        cv2.circle(img, (zone['x'], zone['y']), zone['radius'], (0, 0, 0), 2)
        # Добавляем перечеркивающую линию
        cv2.line(img,
                 (zone['x'] - zone['radius'], zone['y'] - zone['radius']),
                 (zone['x'] + zone['radius'], zone['y'] + zone['radius']),
                 (0, 0, 0), 2)

    cv2.imwrite(diff_path, img)
    return diff_path


# Проверка истёкших подписок
# def check_expired_subscriptions():
#     conn = sqlite3.connect('users.db')
#     cursor = conn.cursor()
#     cursor.execute('''SELECT user_id
#                     FROM users
#                     WHERE is_confirmed = TRUE
#                     AND tariff_end_date < ?''',
#                    (datetime.now().strftime('%Y-%m-%d'),))
#
#     expired_users = cursor.fetchall()
#     for (user_id,) in expired_users:
#         bot.send_message(
#             user_id,
#             "🚫 Ваша пробная подписка истекла. Для продолжения работы обратитесь в поддержку."
#         )
#         save_user(user_id, is_confirmed=False)
#
#     conn.close()
#     threading.Timer(60, check_expired_subscriptions).start()  # Проверка раз в сутки


# Обработка команды /start
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    welcome_text = (
        "🌍 Система мониторинга зон\n\n"
        "📌 Отправьте ссылку на карту\n"
        "🆓 Пробный период: 3 дня\n"
        "🔔 Изменения проверяются каждые 2 минуты"
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="Отправить карту", callback_data="send_map")

    await message.answer(
        welcome_text,
        reply_markup=builder.as_markup()
    )


def get_user_map_link(user_id):
    """
    Получает сохраненную ссылку на карту пользователя

    Параметры:
    user_id (int): Идентификатор пользователя Telegram

    Возвращает:
    str: URL-адрес карты или None
    """
    logger.info(f"Получение ссылки на карту для {user_id}")
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute("SELECT map_link FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None


# Новая функция проверки истёкших тарифов
async def check_expired_subscriptions():
    """Проверка истекших подписок"""
    while True:
        try:
            async with aiosqlite.connect('users.db') as conn:
                cursor = await conn.cursor()
                await cursor.execute('''SELECT user_id 
                                      FROM users 
                                      WHERE is_confirmed = TRUE 
                                      AND tariff_end_date < ?''',
                                     (datetime.now().strftime('%Y-%m-%d'),))

                expired_users = await cursor.fetchall()
                for (user_id,) in expired_users:
                    await bot.send_message(
                        user_id,
                        "🚫 Ваша пробная подписка истекла. Для продолжения работы обратитесь в поддержку."
                    )
                    await save_user(user_id, is_confirmed=False)

        except Exception as e:
            logger.error(f"Subscription check error: {str(e)}")

        await asyncio.sleep(86400)  # Проверка раз в сутки


@dp.message(Command("status"))
async def handle_status(message: types.Message):
    user_id = message.chat.id

    if not await check_subscription(user_id):
        return

    try:
        # Отправляем начальное сообщение с прогресс-баром
        progress_msg = await message.answer(
            "🔄 *Запуск процесса формирования отчета:*\n"
            "________________________________\n"
            "▰▱▱▱▱▱▱▱▱▱ 10%",
            parse_mode='Markdown'
        )

        # Получаем зоны асинхронно
        zones = await get_user_zones(user_id)
        if not zones:
            await progress_msg.edit_text(
                "❌ *Нет данных о зонах!*\n"
                "Возможно, ещё не прошла первая проверка или фиолетовые зоны отсутствуют по вашей ссылке\n"
                "Первая проверка выполняется в течении 2 минут",
                parse_mode='Markdown'
            )
            return

        # Обрабатываем изображение в отдельном потоке
        processed_image = await run_in_threadpool(
            executor,
            generate_status_image,
            user_id,
            zones
        )

        # Отправляем результат
        status_text = (
            f"📋 *Детальный отчет*\n"
            f"• Всего зон: {len(zones)}\n"
            f"• Последнее обновление: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n"
            f"• Следующая проверка через: 2 минуты\n\n"
            f"{COLOR_LEGEND}"
        )

        await message.answer_photo(
            types.BufferedInputFile(processed_image, filename="status.png"),
            caption=status_text,
            parse_mode='Markdown'
        )

        await progress_msg.delete()

    except Exception as e:
        logger.error(f"Status error: {str(e)}")
        await message.answer("⚠️ Произошла ошибка при формировании отчета")


def generate_status_image(user_id, zones):
    """Синхронная генерация изображения статуса"""
    map_path = f'processed_{user_id}.png'
    if not os.path.exists(map_path):
        return None

    img = cv2.imread(map_path)
    timestamp = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    cv2.putText(img, f"Status: {timestamp}", (20, 40),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

    temp_path = f'status_temp_{user_id}.png'
    cv2.imwrite(temp_path, img)

    with open(temp_path, 'rb') as f:
        image_data = f.read()

    os.remove(temp_path)
    return image_data


# def edit_progress(message, text, delay=0):
#     """Обновление сообщения с прогрессом"""
#     time.sleep(delay)
#     try:
#         bot.edit_message_text(
#             text,
#             chat_id=message.chat.id,
#             message_id=message.message_id,
#             parse_mode='Markdown'
#         )
#     except Exception as e:
#         logger.warning(f"Progress update error: {str(e)}")


@dp.message(lambda message: message.text.startswith("http"))
async def handle_map_link(message: types.Message):
    user_id = message.chat.id
    map_link = message.text

    if not await check_subscription(user_id):
        return

    await save_user(user_id, map_link=map_link, notified=False)
    await message.answer("🔄 Обрабатываю карту...")

    try:
        processed_path, zones, _ = await process_map_async(map_link, user_id)
        await save_zones_to_db(user_id, zones)

        builder = InlineKeyboardBuilder()
        builder.button(text="Активировать мониторинг", callback_data="confirm")
        builder.button(text="Отмена", callback_data="cancel")

        with open(processed_path, 'rb') as photo:
            await message.answer_photo(
                types.BufferedInputFile(photo.read(), filename="map.png"),
                caption="📍 Карта готова! Подтвердите активацию мониторинга",
                reply_markup=builder.as_markup()
            )

    except Exception as e:
        logger.error(f"Map processing error: {str(e)}")
        await message.answer(f"⚠️ Ошибка обработки карты: {str(e)}")


# Обработчики колбэков
@dp.callback_query(lambda c: c.data == 'confirm')
async def handle_confirmation(callback: types.CallbackQuery):
    user_id = callback.message.chat.id
    new_end_date = datetime.now() + timedelta(days=3)

    await save_user(user_id,
                    is_confirmed=True,
                    tariff_end_date=new_end_date.strftime('%Y-%m-%d'),
                    notified=False)

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        f"✅ Мониторинг активирован до {new_end_date.strftime('%d.%m.%Y')}\n"
        "🔍 Изменения проверяются каждые 2 минуты"
    )


@dp.callback_query(lambda c: c.data == 'cancel')
async def handle_cancel(callback: types.CallbackQuery):
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("❌ Активация мониторинга отменена")


async def main():
    await init_db()
    asyncio.create_task(background_check())
    asyncio.create_task(check_expired_subscriptions())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
