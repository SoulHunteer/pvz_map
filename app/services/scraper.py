from __future__ import annotations

import logging
import os
import platform
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import cv2
import numpy as np
from selenium import webdriver
from selenium.common.exceptions import SessionNotCreatedException, TimeoutException, WebDriverException
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from app.core.exceptions import BrowserTimeoutError, EmptyScreenshotError, InvalidMapLinkError, MapLoadError
from app.core.settings import Settings
from app.services.types import ScreenshotResult

logger = logging.getLogger(__name__)

FILTER_TOGGLE_XPATH = "//*[@id='legendControl']/button"
PICKUP_VISIBILITY_XPATHS = [
    "//*[@id='legendControl']/div/div/div/div[2]/div/div[1]/div/div[4]/button",
    "//*[@id='legendControl']/div/div/div/div[2]/div/div[2]/div/div[4]/button",
    "//*[@id='legendControl']/div/div/div/div[2]/div/div[3]/div/div[4]/button",
    "//*[@id='legendControl']/div/div/div/div[2]/div/div[4]/div/div[4]/button",
    "//*[@id='legendControl']/div/div/div/div[2]/div/div[5]/div/div[4]/button",
    "//*[@id='legendControl']/div/div/div/div[2]/div/div[6]/div/div[4]/button",
]
PICKUP_STATUS_NAMES = [
    "\u0420\u0430\u0431\u043e\u0442\u0430\u0435\u0442 \u0432 \u043e\u0431\u044b\u0447\u043d\u043e\u043c \u0440\u0435\u0436\u0438\u043c\u0435",
    "\u041f\u0435\u0440\u0435\u0433\u0440\u0443\u0436\u0435\u043d",
    "\u041f\u0435\u0440\u0435\u0433\u0440\u0443\u0436\u0435\u043d, \u043d\u043e \u0440\u044f\u0434\u043e\u043c \u043e\u0442\u043a\u0440\u043e\u0435\u0442\u0441\u044f \u043d\u043e\u0432\u044b\u0439",
    "\u0421\u043a\u043e\u0440\u043e \u043e\u0442\u043a\u0440\u043e\u0435\u0442\u0441\u044f",
    "\u041c\u043e\u0436\u043d\u043e \u043a\u0443\u043f\u0438\u0442\u044c \u043d\u0430 \u0430\u0443\u043a\u0446\u0438\u043e\u043d\u0435",
    "\u041d\u0435 \u0440\u0430\u0431\u043e\u0442\u0430\u0435\u0442",
]


class MapScraper:
    def __init__(self, settings: Settings):
        self.settings = settings

    def _validate_link(self, map_link: str) -> None:
        parsed = urlparse(map_link)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise InvalidMapLinkError(f"Invalid map link: {map_link}")

    def _init_driver(self) -> webdriver.Chrome:
        options = webdriver.ChromeOptions()
        if self.settings.chrome_headless:
            options.add_argument("--headless=new")


        if platform.system().lower().startswith("win"):
            options.add_argument("--use-angle=swiftshader")
            options.add_argument("--enable-webgl")
            options.add_argument("--ignore-gpu-blocklist")
        else:
            options.add_argument("--disable-gpu")

        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1280,720")
        options.add_argument("--remote-debugging-port=9222")

        if self.settings.chrome_binary_path:
            chrome_binary = Path(self.settings.chrome_binary_path)
            if chrome_binary.exists():
                options.binary_location = str(chrome_binary)
            else:
                logger.warning("Chrome binary path does not exist, fallback to system browser: %s", self.settings.chrome_binary_path)

        service = None
        if self.settings.chromedriver_path:
            driver_path = Path(self.settings.chromedriver_path)
            if driver_path.exists():
                service = Service(executable_path=str(driver_path))
            else:
                logger.warning("Chromedriver path does not exist, fallback to Selenium Manager: %s", self.settings.chromedriver_path)

        driver = None
        try:
            if service is not None:
                driver = webdriver.Chrome(options=options, service=service)
            else:
                driver = webdriver.Chrome(options=options)
        except SessionNotCreatedException as exc:
            mismatch = "only supports Chrome version" in str(exc)
            if service is not None and mismatch:
                logger.warning(
                    "Chromedriver at %s is incompatible with current Chrome, falling back to Selenium Manager",
                    self.settings.chromedriver_path,
                )
                try:
                    driver = webdriver.Chrome(options=options)
                except WebDriverException as retry_exc:
                    raise MapLoadError("Failed to initialize browser driver") from retry_exc
            else:
                raise MapLoadError("Failed to initialize browser driver") from exc
        except WebDriverException as exc:
            if service is not None:
                logger.warning(
                    "Failed to initialize with explicit chromedriver path, falling back to Selenium Manager: %s",
                    exc,
                )
                try:
                    driver = webdriver.Chrome(options=options)
                except WebDriverException as retry_exc:
                    raise MapLoadError("Failed to initialize browser driver") from retry_exc
            else:
                raise MapLoadError("Failed to initialize browser driver") from exc

        driver.set_page_load_timeout(self.settings.selenium_page_load_timeout_seconds)
        return driver

    @staticmethod
    def _safe_click(driver: webdriver.Chrome, element, reason: str) -> bool:
        try:
            driver.execute_script("arguments[0].click();", element)
            return True
        except Exception as exc:
            logger.debug("Click failed for %s: %s", reason, exc)
            return False

    @staticmethod
    def _is_cookie_banner_visible(driver: webdriver.Chrome) -> bool:
        script = """
            const cookieRe = /(cookies|cookie|\u0444\u0430\u0439\u043b\u044b cookie)/i;
            const rejectRe = /(\u043e\u0442\u043a\u0430\u0437\u0430\u0442\u044c\u0441\u044f|reject|decline|deny)/i;
            const allowRe = /(\u0440\u0430\u0437\u0440\u0435\u0448\u0438\u0442\u044c|accept|allow)/i;
            for (const el of document.querySelectorAll('body *')) {
              const text = (el.innerText || '').trim();
              if (!text) continue;
              const st = getComputedStyle(el);
              if (st.display === 'none' || st.visibility === 'hidden' || st.opacity === '0') continue;
              const rect = el.getBoundingClientRect();
              if (rect.width < 260 || rect.height < 70) continue;
              if (rect.top < window.innerHeight * 0.45) continue;
              if (cookieRe.test(text) || (rejectRe.test(text) && allowRe.test(text))) return true;
            }
            return false;
        """
        try:
            return bool(driver.execute_script(script))
        except Exception:
            return False

    @staticmethod
    def _js_click_text_buttons(driver: webdriver.Chrome, labels: list[str], bottom_only: bool = False) -> int:
        script = """
            const labels = arguments[0];
            const bottomOnly = Boolean(arguments[1]);
            const matches = (text) => labels.some((label) => text.includes(label));
            let clicked = 0;
            const seen = new Set();
            const nodes = Array.from(document.querySelectorAll('button, [role="button"], a, span, div'));
            for (const node of nodes) {
              const text = (node.innerText || node.textContent || '').trim();
              if (!text || !matches(text)) continue;

              let target = node;
              while (target && !['BUTTON', 'A'].includes(target.tagName) && target.getAttribute('role') !== 'button') {
                target = target.parentElement;
              }
              target = target || node;

              const rect = target.getBoundingClientRect();
              if (bottomOnly && rect.top < window.innerHeight * 0.45) continue;
              if (seen.has(target)) continue;

              seen.add(target);
              try {
                target.click();
                clicked += 1;
              } catch (e) {}
            }
            return clicked;
        """
        try:
            return int(driver.execute_script(script, labels, bottom_only) or 0)
        except Exception:
            return 0

    @staticmethod
    def _force_hide_cookie_overlays(driver: webdriver.Chrome) -> int:
        script = """
            const cookieRe = /(cookies|cookie|\u0444\u0430\u0439\u043b\u044b cookie)/i;
            const rejectRe = /(\u043e\u0442\u043a\u0430\u0437\u0430\u0442\u044c\u0441\u044f|reject|decline|deny)/i;
            const allowRe = /(\u0440\u0430\u0437\u0440\u0435\u0448\u0438\u0442\u044c|accept|allow)/i;

            let hidden = 0;
            const candidates = [];
            candidates.push(...Array.from(document.querySelectorAll('[id*="cookie" i], [class*="cookie" i]')));

            for (const el of document.querySelectorAll('body *')) {
              const text = (el.innerText || '').trim();
              if (!text) continue;
              const rect = el.getBoundingClientRect();
              if (rect.width < 260 || rect.height < 70) continue;
              if (rect.top < window.innerHeight * 0.45) continue;
              if (cookieRe.test(text) || (rejectRe.test(text) && allowRe.test(text))) {
                candidates.push(el);
              }
            }

            const seen = new Set();
            for (const el of candidates) {
              let target = el.closest('section, article, aside, div') || el;
              if (!target || seen.has(target)) continue;
              seen.add(target);
              try {
                target.style.setProperty('display', 'none', 'important');
                target.style.setProperty('visibility', 'hidden', 'important');
                target.style.setProperty('opacity', '0', 'important');
                hidden += 1;
              } catch (e) {}
            }
            return hidden;
        """
        try:
            return int(driver.execute_script(script) or 0)
        except Exception:
            return 0

    def _close_notifications(self, driver: webdriver.Chrome) -> int:
        closed = 0
        try:
            notifications = WebDriverWait(driver, 5).until(
                EC.presence_of_all_elements_located((By.CSS_SELECTOR, ".ant-notification-notice-close"))
            )
            for close_button in notifications:
                if self._safe_click(driver, close_button, "notification close"):
                    closed += 1
                    time.sleep(0.2)
        except Exception:
            logger.debug("No ant notifications found")
        return closed

    def _close_text_buttons(self, driver: webdriver.Chrome, labels: list[str], bottom_only: bool = False) -> int:
        clicked = 0
        for label in labels:
            try:
                xpath = (
                    f"//*[self::button or @role='button' or self::span or self::div]"
                    f"[contains(normalize-space(.), '{label}')]"
                )
                elements = driver.find_elements(By.XPATH, xpath)
                for element in elements[:6]:
                    if bottom_only:
                        try:
                            rect = element.rect
                            if rect and rect.get("y", 0) < 300:
                                continue
                        except Exception:
                            pass

                    if self._safe_click(driver, element, f"text button {label}"):
                        clicked += 1
                        time.sleep(0.2)
            except Exception:
                logger.debug("No clickable text button found for %s", label)
        return clicked

    def _close_cookie_in_iframes(self, driver: webdriver.Chrome, labels: list[str]) -> int:
        clicked = 0
        try:
            frames = driver.find_elements(By.TAG_NAME, "iframe")
        except Exception:
            frames = []

        for frame in frames[:8]:
            try:
                driver.switch_to.frame(frame)
                clicked += self._close_text_buttons(driver, labels, bottom_only=False)
                clicked += self._js_click_text_buttons(driver, labels, bottom_only=False)
                hidden = self._force_hide_cookie_overlays(driver)
                if hidden:
                    logger.info("Cookie overlays hidden in iframe: %s", hidden)
            except Exception:
                pass
            finally:
                try:
                    driver.switch_to.default_content()
                except Exception:
                    pass
        return clicked

    def _close_cookie_banner(self, driver: webdriver.Chrome) -> bool:
        labels = [
            "\u041e\u0442\u043a\u0430\u0437\u0430\u0442\u044c\u0441\u044f",
            "\u0422\u043e\u043b\u044c\u043a\u043e \u043d\u0435\u043e\u0431\u0445\u043e\u0434\u0438\u043c\u044b\u0435",
            "Reject",
            "Decline",
            "Deny",
            "No, thanks",
        ]

        for _ in range(6):
            clicked = 0
            clicked += self._close_text_buttons(driver, labels, bottom_only=True)
            clicked += self._js_click_text_buttons(driver, labels, bottom_only=True)
            clicked += self._close_cookie_in_iframes(driver, labels)

            hidden = self._force_hide_cookie_overlays(driver)
            if hidden:
                logger.info("Cookie overlays hidden in main context: %s", hidden)

            if clicked:
                logger.info("Cookie close clicks: %s", clicked)
                time.sleep(0.4)

            if not self._is_cookie_banner_visible(driver):
                return True

            time.sleep(0.3)

        return not self._is_cookie_banner_visible(driver)

    @staticmethod
    def _is_filters_panel_open(driver: webdriver.Chrome) -> bool:
        try:
            return bool(driver.find_elements(By.XPATH, PICKUP_VISIBILITY_XPATHS[0]))
        except Exception:
            return False

    def _close_popups(self, driver: webdriver.Chrome, timeout_seconds: int) -> None:
        total_closed = 0

        try:
            close_button = WebDriverWait(driver, min(timeout_seconds, 8)).until(
                EC.element_to_be_clickable((By.CLASS_NAME, "ant-drawer-close"))
            )
            if self._safe_click(driver, close_button, "ant drawer close"):
                total_closed += 1
                time.sleep(0.3)
        except Exception:
            logger.debug("No drawer close button found")

        total_closed += self._close_notifications(driver)

        total_closed += self._close_text_buttons(
            driver,
            ["\u0417\u0430\u043a\u0440\u044b\u0442\u044c", "\u0421\u043a\u0440\u044b\u0442\u044c", "\u041f\u0440\u043e\u043f\u0443\u0441\u0442\u0438\u0442\u044c", "\u041f\u043e\u043d\u044f\u0442\u043d\u043e", "\u041e\u041a", "OK", "\u0425\u043e\u0440\u043e\u0448\u043e"],
        )

        if not self._close_cookie_banner(driver):
            logger.warning("Cookie banner still visible after close attempts")

        if total_closed:
            logger.info("Closed popups/buttons: %s", total_closed)

    def _try_open_filters(self, driver: webdriver.Chrome) -> bool:
        if self._is_filters_panel_open(driver):
            return True

        try:
            toggle = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.XPATH, FILTER_TOGGLE_XPATH)))
            if self._safe_click(driver, toggle, "open filters legendControl"):
                time.sleep(0.4)
                if self._is_filters_panel_open(driver):
                    return True
        except Exception as exc:
            logger.debug("Failed to open filters via explicit xpath: %s", exc)

        return self._is_filters_panel_open(driver)

    def _close_filters_panel(self, driver: webdriver.Chrome) -> bool:
        if not self._is_filters_panel_open(driver):
            return True

        try:
            toggle = WebDriverWait(driver, 3).until(EC.element_to_be_clickable((By.XPATH, FILTER_TOGGLE_XPATH)))
            if self._safe_click(driver, toggle, "close filters legendControl"):
                time.sleep(0.4)
                if not self._is_filters_panel_open(driver):
                    return True
        except Exception as exc:
            logger.debug("Failed to close filters via explicit xpath: %s", exc)

        try:
            body = driver.find_element(By.TAG_NAME, "body")
            body.send_keys(Keys.ESCAPE)
            time.sleep(0.2)
        except Exception:
            pass

        return not self._is_filters_panel_open(driver)

    def _hide_pickup_markers(self, driver: webdriver.Chrome) -> int:
        if not self._try_open_filters(driver):
            logger.warning("Filter panel was not opened; marker visibility may stay unchanged")
            return 0

        clicked = 0
        clicked_names: list[str] = []
        missing_names: list[str] = []

        for index, xpath in enumerate(PICKUP_VISIBILITY_XPATHS):
            name = PICKUP_STATUS_NAMES[index] if index < len(PICKUP_STATUS_NAMES) else f"status_{index + 1}"
            try:
                buttons = driver.find_elements(By.XPATH, xpath)
                if not buttons:
                    missing_names.append(name)
                    continue

                button = buttons[0]
                if button.find_elements(By.CSS_SELECTOR, ".anticon-eye-invisible, [data-icon='eye-invisible']"):
                    # Already hidden.
                    continue

                if self._safe_click(driver, button, f"hide pickup status {index + 1}"):
                    clicked += 1
                    clicked_names.append(name)
                    time.sleep(0.15)
            except Exception as exc:
                logger.debug("Failed to toggle pickup status %s: %s", index + 1, exc)
                missing_names.append(name)

        logger.info("Pickup status toggles clicked=%s labels=%s", clicked, clicked_names)
        if missing_names:
            logger.warning("Some pickup statuses were not toggled: %s", missing_names)
        return clicked

    @staticmethod
    def _close_left_menu_panel(driver: webdriver.Chrome) -> bool:
        script = """
            const isOpen = () => {
              const text = ((document.body && document.body.innerText) || '').toLowerCase();
              return text.includes('\\u043a\\u0430\\u0440\\u0442\\u0430 wb \\u043f\\u0432\\u0437');
            };

            if (!isOpen()) return 1;

            const points = [[28, 28], [40, 28], [56, 28]];
            for (const [x, y] of points) {
              let node = document.elementFromPoint(x, y);
              while (node && !['BUTTON', 'A'].includes(node.tagName) && node.getAttribute('role') !== 'button') {
                node = node.parentElement;
              }
              if (!node) continue;
              try { node.click(); } catch (e) {}
              if (!isOpen()) return 1;
            }
            return isOpen() ? 0 : 1;
        """
        try:
            return bool(int(driver.execute_script(script) or 0))
        except Exception:
            return False

    @staticmethod
    def _hide_ui_side_panels(driver: webdriver.Chrome) -> int:
        script = """
            const textIncludes = (text, token) => (text || '').toLowerCase().includes(token);
            const isLeftPanel = (text, rect) => (
              textIncludes(text, '\\u043a\\u0430\\u0440\\u0442\\u0430 wb \\u043f\\u0432\\u0437') &&
              rect.left < window.innerWidth * 0.45 &&
              rect.width > 240
            );
            const isRightPanel = (text, rect) => (
              (textIncludes(text, '\\u0437\\u043e\\u043d\\u044b \\u0434\\u043b\\u044f \\u043e\\u0442\\u043a\\u0440\\u044b\\u0442\\u0438\\u044f') ||
               textIncludes(text, '\\u043f\\u0443\\u043d\\u043a\\u0442\\u044b \\u0432\\u044b\\u0434\\u0430\\u0447\\u0438')) &&
              rect.left > window.innerWidth * 0.45 &&
              rect.width > 240
            );

            let hidden = 0;
            for (const node of document.querySelectorAll('div, section, aside, article')) {
              const text = (node.innerText || '').toLowerCase();
              if (!text) continue;
              const rect = node.getBoundingClientRect();
              if (rect.height < 120) continue;
              if (!isLeftPanel(text, rect) && !isRightPanel(text, rect)) continue;

              try {
                node.style.setProperty('display', 'none', 'important');
                node.style.setProperty('visibility', 'hidden', 'important');
                node.style.setProperty('opacity', '0', 'important');
                hidden += 1;
              } catch (e) {}
            }
            return hidden;
        """
        try:
            return int(driver.execute_script(script) or 0)
        except Exception:
            return 0

    def capture_map(self, map_link: str, tracked_item_id: int) -> ScreenshotResult:
        self._validate_link(map_link)

        driver = None
        try:
            driver = self._init_driver()
            driver.get(map_link)
            WebDriverWait(driver, self.settings.selenium_wait_timeout_seconds).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )

            time.sleep(5)

            self._close_popups(driver, self.settings.selenium_wait_timeout_seconds)
            self._hide_pickup_markers(driver)
            self._close_filters_panel(driver)
            self._close_left_menu_panel(driver)
            self._close_cookie_banner(driver)
            self._hide_ui_side_panels(driver)


            time.sleep(2)

            screenshot_data = driver.get_screenshot_as_png()
            image = cv2.imdecode(np.frombuffer(screenshot_data, dtype=np.uint8), cv2.IMREAD_COLOR)
            if image is None or image.size == 0:
                raise EmptyScreenshotError("Screenshot is empty or cannot be decoded")

            filename = (
                f"tracked_{tracked_item_id}_"
                f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}_"
                f"{uuid4().hex[:8]}.png"
            )
            screenshot_path = Path(self.settings.screenshots_dir) / filename
            cv2.imwrite(str(screenshot_path), image)
            return ScreenshotResult(image=image, screenshot_path=str(screenshot_path))
        except TimeoutException as exc:
            raise BrowserTimeoutError(f"Browser timeout for link {map_link}") from exc
        except WebDriverException as exc:
            raise MapLoadError(f"Map loading failed for link {map_link}") from exc
        finally:
            if driver is not None:
                driver.quit()







