import logging
import sqlite3
from datetime import datetime, timedelta
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from selenium import webdriver
from selenium.webdriver.common.by import By
import threading
import time
import cv2
import numpy as np
import os
from dotenv import load_dotenv

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
bot = telebot.TeleBot(token=TELEGRAM_TOKEN)

COLOR_LEGEND = (
    "🎨 Цветовая легенда:\n"
    "🟢 Зеленый - текущие зоны\n"
    "🔴 Красный - новые зоны\n"
    "⚫ Черный - удаленные зоны"
)

# Инициализация базы данных
def init_db():
    """
    Инициализирует базу данных SQLite
    Создает таблицы users и pixel_zones при первом запуске
    """
    logger.info("Инициализация базы данных...")
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    try:
        cursor.execute('''CREATE TABLE IF NOT EXISTS users (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            user_id INTEGER NOT NULL UNIQUE,
                            role TEXT NOT NULL DEFAULT 'user',
                            map_link TEXT,
                            tariff_end_date TEXT,
                            is_confirmed BOOLEAN NOT NULL DEFAULT FALSE,
                            notified BOOLEAN NOT NULL DEFAULT FALSE
                        )''')

        cursor.execute('''CREATE TABLE IF NOT EXISTS pixel_zones (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            x INTEGER NOT NULL,
                            y INTEGER NOT NULL,
                            radius INTEGER NOT NULL,
                            user_id INTEGER,
                            FOREIGN KEY (user_id) REFERENCES users(user_id),
                            UNIQUE(x, y, radius, user_id)
                        )''')

        conn.commit()
        logger.info("База данных успешно инициализирована")
    except Exception as e:
        logger.error(f"Ошибка инициализации БД: {str(e)}")
    finally:
        conn.close()


# Добавление/обновление пользователя
def save_user(user_id, **kwargs):
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
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT map_link FROM users WHERE user_id = ?", (user_id,))
        existing_user = cursor.fetchone()

        if existing_user and 'map_link' in kwargs and existing_user[0] != kwargs['map_link']:
            logger.info(f"Обновление карты для пользователя {user_id}")
            delete_all_zones_for_user(user_id)

        if not existing_user:
            logger.info(f"Новый пользователь {user_id}")
            default_end_date = datetime.now() + timedelta(days=3)
            cursor.execute(
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
            cursor.execute(update_query, params)

        conn.commit()
    except Exception as e:
        logger.error(f"Ошибка сохранения пользователя {user_id}: {str(e)}")
    finally:
        conn.close()


def check_subscription(user_id):
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute('''SELECT tariff_end_date, notified, is_confirmed 
                    FROM users 
                    WHERE user_id = ?''', (user_id,))
    result = cursor.fetchone()
    conn.close()

    if not result:
        return True

    end_date, notified, is_confirmed = result

    # Проверка подтверждения карты
    # if not is_confirmed:
    #     return False

    # Проверка даты подписки
    if end_date and datetime.strptime(end_date, '%Y-%m-%d') < datetime.now():
        # if not notified:
        bot.send_message(user_id, "🚫 Подписка истекла! Для продления свяжитесь с администратором.")
        save_user(user_id, notified=True)
        return False
    return True


# Сохранение зон в БД
def save_zones_to_db(user_id, zones):
    """
    Сохраняет обнаруженные зоны в базу данных

    Параметры:
    user_id (int): Идентификатор пользователя Telegram
    zones (list): Список словарей с координатами зон

    Возвращает:
    None
    """
    logger.info(f"Сохранение {len(zones)} зон для пользователя {user_id}")
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    try:
        for zone in zones:
            cursor.execute("INSERT OR IGNORE INTO pixel_zones (x, y, radius, user_id) VALUES (?, ?, ?, ?)",
                           (zone['x'], zone['y'], zone['radius'], user_id))
        conn.commit()
        logger.info(f"Успешно сохранено зон: {len(zones)}")
    except Exception as e:
        logger.error(f"Ошибка сохранения зон для {user_id}: {str(e)}")
    finally:
        conn.close()


# Удаление зон из БД
def delete_zones_from_db(user_id, zones):
    """
    Удаляет указанные зоны из базы данных

    Параметры:
    user_id (int): Идентификатор пользователя Telegram
    zones (set): Множество кортежей (x, y, radius) для удаления

    Возвращает:
    None
    """
    logger.info(f"Удаление {len(zones)} зон для пользователя {user_id}")
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    try:
        for (x, y, radius) in zones:
            cursor.execute(
                "DELETE FROM pixel_zones WHERE user_id = ? AND x = ? AND y = ? AND radius = ?",
                (user_id, x, y, radius)
            )
        conn.commit()
        logger.info(f"Успешно удалено зон: {len(zones)}")
    except Exception as e:
        logger.error(f"Ошибка удаления зон для {user_id}: {str(e)}")
    finally:
        conn.close()


def delete_all_zones_for_user(user_id):
    """
    Удаляет все зоны, связанные с указанным пользователем

    Параметры:
    user_id (int): Идентификатор пользователя Telegram

    Возвращает:
    None
    """
    logger.info(f"Удаление всех зон для пользователя {user_id}")
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM pixel_zones WHERE user_id = ?", (user_id,))
        conn.commit()
        logger.info(f"Удалено зон: {cursor.rowcount}")
    except Exception as e:
        logger.error(f"Ошибка удаления зон для {user_id}: {str(e)}")
    finally:
        conn.close()


# Получение зон из БД
def get_user_zones(user_id):
    """
    Получает сохраненные зоны пользователя из базы данных

    Параметры:
    user_id (int): Идентификатор пользователя Telegram

    Возвращает:
    list: Список словарей с координатами зон
    """
    logger.info(f"Получение зон для пользователя {user_id}")
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT x, y, radius FROM pixel_zones WHERE user_id = ?", (user_id,))
        result = cursor.fetchall()
        logger.info(f"Найдено зон: {len(result)}")
        return [{'x': row[0], 'y': row[1], 'radius': row[2]} for row in result]
    except Exception as e:
        logger.error(f"Ошибка получения зон для {user_id}: {str(e)}")
        return []
    finally:
        conn.close()


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
        has_close_match = False
        for old_zone in old_zones:
            if (abs(new_zone['x'] - old_zone['x']) <= 1 and
                    abs(new_zone['y'] - old_zone['y']) <= 1 and
                    abs(new_zone['radius'] - old_zone['radius']) <= 1):
                has_close_match = True
                break
        if not has_close_match:
            added.append(new_zone)

    # Ищем удалённые зоны
    for old_zone in old_zones:
        has_close_match = False
        for new_zone in new_zones:
            if (abs(old_zone['x'] - new_zone['x']) <= 1 and
                    abs(old_zone['y'] - new_zone['y']) <= 1 and
                    abs(old_zone['radius'] - new_zone['radius']) <= 1):
                has_close_match = True
                break
        if not has_close_match:
            removed.append(old_zone)

    added_set = set((z['x'], z['y'], z['radius']) for z in added)
    removed_set = set((z['x'], z['y'], z['radius']) for z in removed)

    logger.info(f"Обнаружено изменений: +{len(added)}, -{len(removed)}")
    return added_set, removed_set


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


# Обработка карты
def process_map(driver, map_link, user_id):
    """
    Обрабатывает карту по указанной ссылке

    Параметры:
    driver (WebDriver): Экземпляр Selenium WebDriver
    map_link (str): URL-адрес карты
    user_id: User id

    Возвращает:
    tuple: (screenshot_path, zones, original_path)
    """
    logger.info(f"Обработка карты: {map_link}")
    try:
        driver.get(map_link)
        time.sleep(5)
        driver.find_element(By.CLASS_NAME, 'ant-drawer-close').click()
        time.sleep(1)
        screenshot, _ = take_screenshot(driver)
        # Сохраняем оригинал и обработанное изображение с привязкой к user_id
        original_path = f'original_{user_id}.png'
        processed_path = f'processed_{user_id}.png'

        cv2.imwrite(original_path, screenshot)
        zones = process_image(screenshot)
        save_image_with_zones(screenshot, zones, processed_path)

        logger.info(f"Обнаружено зон: {len(zones)}")
        return processed_path, zones, original_path
    except Exception as e:
        logger.error(f"Ошибка обработки карты: {str(e)}")
        raise


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
        window_size = driver.execute_script("return [window.innerWidth, window.innerHeight];")
        screenshot = driver.get_screenshot_as_png()
        screenshot_np = np.frombuffer(screenshot, np.uint8)
        image = cv2.imdecode(screenshot_np, cv2.IMREAD_COLOR)
        return image, window_size
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


# Фоновая проверка зон
def background_check():
    """
    Фоновая задача для периодической проверки изменений зон
    Запускается каждые 30 секунд
    """
    logger.info("Запуск фоновой проверки")
    try:
        conn = sqlite3.connect('users.db')
        cursor = conn.cursor()
        cursor.execute('''SELECT user_id, map_link 
                        FROM users 
                        WHERE is_confirmed = TRUE and notified = FALSE''')
        users = cursor.fetchall()
        conn.close()

        for user_id, map_link in users:
            if not check_subscription(user_id):
                continue

            driver = init_driver()
            try:
                old_zones = get_user_zones(user_id)
                screenshot_path, new_zones, original_path = process_map(driver, map_link, user_id)
                added, removed = compare_zones(old_zones, new_zones)

                if added or removed:
                    save_zones_to_db(user_id, new_zones)
                    delete_zones_from_db(user_id, removed)

                    # Генерация изображения с изменениями
                    original_image = cv2.imread(original_path)

                    # Рисуем текущие зоны зеленым
                    for zone in new_zones:
                        cv2.circle(original_image, (zone['x'], zone['y']), zone['radius'], (0, 255, 0), 2)

                    # Добавляем новые зоны красным
                    for (x, y, radius) in added:
                        cv2.circle(original_image, (x, y), radius, (0, 0, 255), 2)

                    # Помечаем удаленные зоны черным
                    for (x, y, radius) in removed:
                        cv2.circle(original_image, (x, y), radius, (0, 0, 0), 2)

                    diff_path = 'diff_image.png'
                    cv2.imwrite(diff_path, original_image)

                    caption = "Обнаружены изменения в зонах!\n\n"
                    if added:
                        caption += f"Добавлено зон: {len(added)}\n"
                    if removed:
                        caption += f"Удалено зон: {len(removed)}\n"
                    caption += COLOR_LEGEND

                    with open(diff_path, 'rb') as diff_img:
                        bot.send_photo(user_id, diff_img, caption=caption)

            except Exception as e:
                print(f"Ошибка при проверке: {e}")
            finally:
                driver.quit()

    except Exception as e:
        logger.error(f"Ошибка фоновой проверки: {str(e)}")
    finally:
        logger.info("Завершение фоновой проверки")
        threading.Timer(30, background_check).start()


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
@bot.message_handler(commands=['start'])
def send_welcome(message):
    """
    Обработчик команды /start
    Отправляет приветственное сообщение и кнопку
    """
    logger.info(f"Сообщение от пользователя: {message.chat.id}")
    welcome_text = (
        "🌍 Система мониторинга зон\n\n"
        "📌 Отправьте ссылку на карту\n"
        "🆓 Пробный период: 3 дня\n"
        "🔔 Изменения проверяются каждые 2 минуты"
    )

    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("Отправить карту", callback_data="send_map"))

    bot.send_message(message.chat.id, welcome_text, reply_markup=markup)


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
def check_expired_subscriptions():
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute('''SELECT user_id 
                    FROM users 
                    WHERE is_confirmed = TRUE 
                    AND tariff_end_date < ?''',
                   (datetime.now().strftime('%Y-%m-%d'),))

    expired_users = cursor.fetchall()
    for (user_id,) in expired_users:
        bot.send_message(
            user_id,
            "🚫 Ваша пробная подписка истекла. Для продолжения работы обратитесь в поддержку."
        )
        save_user(user_id, is_confirmed=False)

    conn.close()
    threading.Timer(86400, check_expired_subscriptions).start()  # Проверка раз в сутки


@bot.message_handler(commands=['status'])
def handle_status(message):
    user_id = message.chat.id

    if not check_subscription(user_id):
        return

    try:
        # Начальное сообщение с прогресс-баром
        progress_msg = bot.send_message(user_id,
                                        "🔄 *Запуск процесса формирования отчета:*\n"
                                        "________________________________\n"
                                        "▰▱▱▱▱▱▱▱▱▱ 10%",
                                        parse_mode='Markdown')

        # Шаг 1: Получение данных
        edit_progress(progress_msg,
                      "📡 *Получаем последние координаты зон...*\n"
                      "________________________________\n"
                      "▰▰▰▱▱▱▱▱▱▱ 30%", 0)

        zones = get_user_zones(user_id)
        if not zones:
            edit_progress(progress_msg,
                          "❌ *Нет данных о зонах!*\n"
                          "Первая проверка будет выполнена в течение 2 минут",
                          100)
            return

        # Шаг 2: Загрузка карты
        edit_progress(progress_msg,
                      "🌍 *Загружаем последнюю версию карты...*\n"
                      "________________________________\n"
                      "▰▰▰▰▰▱▱▱▱▱ 50%", 0)

        map_path = f'processed_{user_id}.png'
        if not os.path.exists(map_path):
            edit_progress(progress_msg,
                          "❌ *Карта не найдена!*\n"
                          "Ожидайте следующей проверки",
                          100)
            return

        # Шаг 3: Визуализация
        edit_progress(progress_msg,
                      "🎨 *Визуализируем изменения...*\n"
                      "________________________________\n"
                      "▰▰▰▰▰▰▰▱▱▱ 70%", 0)

        img = cv2.imread(map_path)
        timestamp = datetime.now().strftime("%d.%m.%Y %H:%M:%S")

        # Добавляем текст на изображение
        cv2.putText(img, f"Status: {timestamp}", (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

        # Сохраняем временный файл
        temp_path = f'status_temp_{user_id}.png'
        cv2.imwrite(temp_path, img)

        # Шаг 4: Формирование отчета
        edit_progress(progress_msg,
                      "📊 *Анализируем данные...*\n"
                      "________________________________\n"
                      "▰▰▰▰▰▰▰▰▰▱ 90%", 1)

        status_text = (
            f"📋 *Детальный отчет*\n"
            f"• Всего зон: {len(zones)}\n"
            f"• Последнее обновление: {timestamp}\n"
            f"• Следующая проверка через: 2 минуты\n\n"
            f"{COLOR_LEGEND}"
        )

        # Отправка финального сообщения
        with open(temp_path, 'rb') as photo:
            bot.send_photo(user_id, photo,
                           caption=status_text,
                           parse_mode='Markdown')

        # Финализация прогресса
        edit_progress(progress_msg,
                      "✅ *Отчет успешно сформирован!*\n"
                      "________________________________\n"
                      "▰▰▰▰▰▰▰▰▰▰ 100%", 0)

        # Удаление временного файла
        os.remove(temp_path)

    except Exception as e:
        error_msg = (
            "⚠️ *Ошибка формирования отчета!*\n"
            f"Причина: {str(e)}\n"
            "Попробуйте снова через 2 минуты"
        )
        if 'progress_msg' in locals():
            edit_progress(progress_msg, error_msg, 100)
        else:
            bot.send_message(user_id, error_msg, parse_mode='Markdown')
        logger.error(f"Status error: {str(e)}")


def edit_progress(message, text, delay=0):
    """Обновление сообщения с прогрессом"""
    time.sleep(delay)
    try:
        bot.edit_message_text(
            text,
            chat_id=message.chat.id,
            message_id=message.message_id,
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.warning(f"Progress update error: {str(e)}")


@bot.message_handler(func=lambda message: message.text.startswith("http"))
def handle_map_link(message):
    """
    Обработчик для входящих ссылок на карты
    """
    logger.info(f"Обработка карты от пользователя {message.chat.id}")
    user_id = message.chat.id
    map_link = message.text

    if not check_subscription(user_id):
        return

    # Для новых пользователей создаем запись с подпиской
    save_user(user_id, map_link=map_link, notified=False)

    bot.send_message(user_id, "🔄 Обрабатываю карту...")

    driver = init_driver()
    try:
        screenshot_path, zones, original_path = process_map(driver, map_link, user_id)
        save_zones_to_db(user_id, zones)

        markup = InlineKeyboardMarkup()
        markup.add(
            InlineKeyboardButton("Активировать мониторинг", callback_data="confirm"),
            InlineKeyboardButton("Отмена", callback_data="cancel")
        )

        with open(screenshot_path, 'rb') as screenshot:
            bot.send_photo(
                user_id,
                screenshot,
                caption="📍 Карта готова! Подтвердите активацию мониторинга",
                reply_markup=markup
            )

    except Exception as e:
        bot.send_message(user_id, f"⚠️ Ошибка: {str(e)}")
    finally:
        driver.quit()


@bot.callback_query_handler(func=lambda call: call.data == 'confirm')
def handle_confirmation(call):
    user_id = call.message.chat.id
    # Обновляем подписку при подтверждении
    new_end_date = datetime.now() + timedelta(days=3)
    save_user(user_id,
              is_confirmed=True,
              tariff_end_date=new_end_date.strftime('%Y-%m-%d'),
              notified=False)

    bot.edit_message_reply_markup(
        chat_id=user_id,
        message_id=call.message.message_id,
        reply_markup=None
    )

    bot.send_message(
        user_id,
        f"✅ Мониторинг активирован до {new_end_date.strftime('%d.%m.%Y')}\n"
        "🔍 Изменения проверяются каждые 2 минуты"
    )


if __name__ == "__main__":
    """
    Основная точка входа в приложение
    """
    logger.info("Запуск бота...")
    try:
        init_db()
        # check_expired_subscriptions()
        background_check()
        bot.infinity_polling()
    except Exception as e:
        logger.critical(f"Критическая ошибка: {str(e)}")
    finally:
        logger.info("Завершение работы бота")
