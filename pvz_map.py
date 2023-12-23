import pip
pip.main(['install', 'pytelegrambotapi'])
pip.main(['install', 'selenium'])
pip.main(['install', 'opencv-python'])
pip.main(['install', 'numpy'])
pip.main(['install', 'csv'])

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
import time
import cv2
import numpy as np
import csv
import sys
import telebot


TELEGRAM_BOT_TOKEN = sys.argv[1]
TELEGRAM_CHAT_ID = sys.argv[2]

bot_token = TELEGRAM_BOT_TOKEN
bot = telebot.TeleBot(token=bot_token)


def init_driver():
    chrome_options = webdriver.ChromeOptions()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--disable-gpu')
    driver = webdriver.Chrome(options=chrome_options)
    return driver


def open_map_and_hide_menus(driver):
    driver.get('https://pvz-stat-map.wildberries.ru/#11.26/55.753/37.6211')
    driver.maximize_window()
    time.sleep(5)

    menu_button = driver.find_element(By.CLASS_NAME, 'pwz-control-panel__toggle-button')
    ActionChains(driver).move_to_element(menu_button).click().perform()

    legend_menu = driver.find_element(By.CLASS_NAME, 'legend-control')
    ActionChains(driver).move_to_element(legend_menu).click().perform()

    time.sleep(1)


def click_buttons(driver, buttons_to_click):
    elements = driver.find_elements(By.CLASS_NAME, 'ant-flex')

    for element in elements:
        text = element.text

        if text in buttons_to_click:
            button = element.find_element(By.CLASS_NAME, 'ant-btn-icon-only')
            ActionChains(driver).click(button).perform()

    time.sleep(1)


def close_legend_menu(driver):
    close_legend_button = driver.find_element(By.CLASS_NAME, 'legend-button')
    ActionChains(driver).move_to_element(close_legend_button).click().perform()


def take_screenshot(driver):
    window_size = driver.execute_script("return [window.innerWidth, window.innerHeight];")
    screenshot = driver.get_screenshot_as_png()
    screenshot_np = np.frombuffer(screenshot, np.uint8)
    image = cv2.imdecode(screenshot_np, cv2.IMREAD_COLOR)
    return image, window_size


def process_image(image):
    target_color = np.array([108, 38, 123], dtype=np.uint8)
    lower_target = np.array([target_color[0] - 25, target_color[1] - 25, target_color[2] - 25], dtype=np.uint8)
    upper_target = np.array([target_color[0] + 25, target_color[1] + 25, target_color[2] + 25], dtype=np.uint8)
    purple_mask = cv2.inRange(image, lower_target, upper_target)
    contours, _ = cv2.findContours(purple_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    purple_zones = []
    for contour in contours:
        (x, y), radius = cv2.minEnclosingCircle(contour)
        center = (int(x), int(y))
        radius = int(radius)
        purple_zones.append({'center': center, 'radius': radius})
    return purple_zones


def save_image_with_zones(image, purple_zones):
    cv2.imwrite('map_with_zones.png', image)
    for zone in purple_zones:
        cv2.circle(image, zone['center'], zone['radius'], (0, 255, 0), 2)
    cv2.imwrite('map_image.png', image)


def save_coordinates_to_csv(purple_zones_geographic, saved_coordinates):
    with open('coordinates.csv', 'a', newline='') as csvfile:
        fieldnames = ['latitude', 'longitude']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        for zone in purple_zones_geographic:
            if zone not in saved_coordinates:
                writer.writerow({'latitude': zone['latitude'], 'longitude': zone['longitude']})
                saved_coordinates.append(zone)

                # Приводим координаты к строке для уведомления
                coordinate_str = f"{zone['latitude']}, {zone['longitude']}"
                notify_telegram(f"New coordinate: {coordinate_str}")


def send_telegram_message(message):
    chat_id = int(TELEGRAM_CHAT_ID)
    bot.send_message(chat_id, message)


def notify_telegram(message):
    send_telegram_message(message)


def convert_pixel_to_geographic_coordinates(pixel_x, pixel_y, window_size, top_left_lat, top_left_lon, bottom_right_lat,
                                            bottom_right_lon):
    lon = top_left_lon + (pixel_x / window_size[0]) * (bottom_right_lon - top_left_lon)
    lat = top_left_lat - (pixel_y / window_size[1]) * (top_left_lat - bottom_right_lat)
    return {'latitude': lat, 'longitude': lon}


def process_map(driver):
    open_map_and_hide_menus(driver)

    buttons_to_click = ['приоритетные', 'недоступные', 'недоступные здания', "работает штатно", 'перегружен',
                        'перегружен, но рядом откроется новый', 'скоро откроется', 'продаётся на аукционе', 'неактивный']
    click_buttons(driver, buttons_to_click)

    close_legend_menu(driver)

    image, window_size = take_screenshot(driver)
    purple_zones = process_image(image)

    save_image_with_zones(image, purple_zones)

    top_left_lat, top_left_lon = 55.8, 37.5175
    bottom_right_lat, bottom_right_lon = 55.7, 37.719

    saved_coordinates = []
    try:
        with open('coordinates.csv', 'r') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                saved_coordinates.append({'latitude': float(row['latitude']), 'longitude': float(row['longitude'])})
    except FileNotFoundError:
        pass

    purple_zones_geographic = [convert_pixel_to_geographic_coordinates(zone['center'][0], zone['center'][1],
                                                                       window_size, top_left_lat, top_left_lon,
                                                                       bottom_right_lat, bottom_right_lon) for zone in
                               purple_zones]

    save_coordinates_to_csv(purple_zones_geographic, saved_coordinates)


if __name__ == "__main__":
    driver = init_driver()
    process_map(driver)
    driver.quit()
