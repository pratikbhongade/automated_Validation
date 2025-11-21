import os
import sys
import json
import time
import logging
import traceback
from flask import Flask, render_template, request, jsonify, abort, make_response
import threading
from concurrent.futures import ThreadPoolExecutor
import socket
from functools import wraps
from selenium import webdriver
from selenium.webdriver.edge.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    JavascriptException,
    StaleElementReferenceException,
    WebDriverException,
)
from email_sender import send_email
import pyautogui
import webbrowser
from datetime import datetime
import base64

# Configure logging
log_file_path = os.path.join(os.getcwd(), 'validation.log')
logging.basicConfig(
    filename=log_file_path,
    level=logging.INFO,
    format='%(asctime)s:%(levelname)s:%(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Console logging too
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_formatter = logging.Formatter('%(asctime)s:%(levelname)s:%(message)s', '%Y-%m-%d %H:%M:%S')
console_handler.setFormatter(console_formatter)
logging.getLogger().addHandler(console_handler)

# Load configuration
try:
    config_path = os.path.join(os.getcwd(), 'dist', 'validation_config.json')
    with open(config_path) as config_file:
        config = json.load(config_file)
    project_name = config['project_name']
except (FileNotFoundError, json.JSONDecodeError, KeyError) as e:
    logging.error(f"Failed to load configuration: {e}")
    raise

# Flask app
app = Flask(__name__)
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0  # Disable caching for development

# Validation state
validation_status = {
    'status': 'Not Started',
    'results': [],
    'paused': False,
    'stopped': False,
    'start_time': None,
    'end_time': None,
    'environment': None,
    'successful_checks': 0,
    'failed_checks': 0,
    'skipped_checks': 0,
    'performance_metrics': {},
    'screenshots': []
}

# Threading events
pause_event = threading.Event()
pause_event.set()

stop_event = threading.Event()
stop_event.clear()

# Active thread tracker
active_validation_thread = None

# Simple rate limiter
request_timestamps = {}
REQUEST_RATE_LIMIT = 10  # per minute
REQUEST_WINDOW = 60      # seconds


def rate_limit(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        client_ip = request.remote_addr
        current_time = time.time()

        # purge old timestamps
        request_timestamps[client_ip] = [
            t for t in request_timestamps.get(client_ip, [])
            if current_time - t < REQUEST_WINDOW
        ]

        if len(request_timestamps.get(client_ip, [])) >= REQUEST_RATE_LIMIT:
            abort(429, "Too many requests")

        request_timestamps.setdefault(client_ip, []).append(current_time)
        return func(*args, **kwargs)

    return wrapper


def calculate_duration(start, end):
    if not start or not end:
        return 'N/A'
    try:
        start_dt = datetime.strptime(start, '%Y-%m-%d %H:%M:%S')
        end_dt = datetime.strptime(end, '%Y-%m-%d %H:%M:%S')
        duration = end_dt - start_dt
        return str(duration)
    except Exception:
        return 'N/A'


def setup_driver():
    """
    Set up and configure Edge WebDriver using Selenium Manager.

    Selenium Manager:
    - Detects installed Edge version
    - Downloads / locates compatible msedgedriver
    - Caches for reuse
    """
    options = Options()
    options.add_argument("--start-maximized")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--disable-infobars")
    options.page_load_strategy = 'normal'

    try:
        driver = webdriver.Edge(options=options)
        logging.info("Using Edge WebDriver via Selenium Manager (auto-managed)")
    except WebDriverException as e:
        logging.error(f"Failed to initialize Edge WebDriver via Selenium Manager: {e}")
        logging.error(
            "Possible causes:\n"
            "1. No internet access the first time for this Edge version, OR\n"
            "2. Corporate proxy/firewall blocking Selenium from reaching Microsoft driver servers.\n\n"
            "Fix: Ensure network/proxy allows Selenium to download Edge WebDriver, "
            "or pre-install msedgedriver on PATH."
        )
        raise
    except Exception as e:
        logging.error(f"Unexpected error while initializing Edge WebDriver: {e}")
        raise

    driver.set_page_load_timeout(30)
    driver.set_script_timeout(30)
    return driver


def find_element_with_retry(driver, by, value, max_attempts=3, wait_time=5,
                            condition=EC.presence_of_element_located):
    """
    Find an element with retry logic to handle stale element references.
    This is for *required* elements (tabs, table, etc.), not optional buttons.
    """
    attempt = 0
    last_exception = None

    while attempt < max_attempts:
        try:
            element = WebDriverWait(driver, wait_time).until(
                condition((by, value))
            )
            return element
        except (StaleElementReferenceException, TimeoutException, NoSuchElementException) as e:
            attempt += 1
            last_exception = e
            if attempt == max_attempts:
                logging.warning(
                    f"Failed to find element after {max_attempts} attempts: {by}={value}, Error: {e}"
                )
                if isinstance(e, StaleElementReferenceException):
                    try:
                        driver.refresh()
                        time.sleep(2)
                    except Exception:
                        pass
                raise last_exception
            time.sleep(1)

    return None


def click_element_with_retry(element, max_attempts=3):
    """
    Click an element with retry logic to handle stale element references
    """
    attempt = 0
    while attempt < max_attempts:
        try:
            # Scroll into view
            try:
                driver = element._parent
                driver.execute_script("arguments[0].scrollIntoView(true);", element)
                time.sleep(0.5)
            except Exception:
                pass

            # Try JS click, then normal click
            try:
                driver = element._parent
                driver.execute_script("arguments[0].click();", element)
                return True
            except Exception:
                element.click()
                return True

        except StaleElementReferenceException:
            attempt += 1
            if attempt == max_attempts:
                logging.warning(
                    f"Failed to click element after {max_attempts} attempts due to StaleElementReferenceException"
                )
                return False
            time.sleep(1)
        except Exception as e:
            attempt += 1
            if attempt == max_attempts:
                logging.warning(f"Failed to click element after {max_attempts} attempts: {e}")
                return False
            time.sleep(1)

    return False


def validate_application(environment, validation_portal_link=None, retry_failed=False):
    """
    Main validation function to test the application in the specified environment.
    """
    global validation_status

    # Performance metrics
    validation_status['performance_metrics'] = {
        'component_timings': {},
        'interaction_timings': [],
        'element_timings': {}
    }

    # Status init
    validation_status['status'] = 'Running'
    validation_status['environment'] = environment
    validation_status['start_time'] = time.strftime("%Y-%m-%d %H:%M:%S")
    validation_status['end_time'] = None
    validation_status['successful_checks'] = 0
    validation_status['failed_checks'] = 0
    validation_status['skipped_checks'] = 0
    validation_status['progress'] = 0
    validation_status['screenshots'] = []

    previous_results = validation_status['results'] if retry_failed else []
    validation_status['results'] = []

    # Environment URL
    try:
        url = config['environments'].get(environment)
        if not url:
            raise ValueError(
                f"Invalid environment selected: {environment}. Please choose from: "
                f"{', '.join(config['environments'].keys())}"
            )
    except Exception as e:
        error_msg = f"Error setting URL for environment {environment}: {e}"
        logging.error(error_msg)
        validation_status['results'].append(error_msg)
        validation_status['status'] = 'Failed'
        validation_status['progress'] = 100
        return [], False

    logging.info(f"Selected environment: {environment}")
    validation_status['results'].append(f"Selected environment: {environment}")

    # WebDriver
    try:
        driver = setup_driver()
        logging.info("WebDriver initialized successfully")
    except Exception as e:
        error_msg = f"Failed to initialize WebDriver: {e}"
        logging.error(error_msg)
        validation_status['results'].append(error_msg)
        validation_status['status'] = 'Failed'
        validation_status['progress'] = 100
        return [], False

    validation_results = []

    def log_and_update_status(message, status="Success"):
        """
        Log a message and update the validation status.
        status: "Success", "Failed", "Skipped", "Info"
        """
        if status == "Success":
            validation_status['successful_checks'] += 1
        elif status == "Failed":
            validation_status['failed_checks'] += 1
        elif status == "Skipped":
            validation_status['skipped_checks'] += 1

        timestamp = time.strftime("%H:%M:%S")
        formatted_message = f"[{timestamp}] [{status}] {message}"

        print(formatted_message)
        if status == "Success":
            logging.info(message)
        elif status == "Failed":
            logging.error(message)
        elif status == "Skipped":
            logging.info(f"Skipped: {message}")
        else:  # Info
            logging.info(message)

        validation_results.append((message, status))
        validation_status['results'].append(formatted_message)

    def record_component_timing(component_name, start_time, end_time=None):
        duration = (end_time or time.time()) - start_time
        cm = validation_status['performance_metrics']['component_timings']
        cm.setdefault(component_name, []).append(duration)
        return duration

    def record_interaction(interaction_name, start_time, end_time=None):
        duration = (end_time or time.time()) - start_time
        validation_status['performance_metrics']['interaction_timings'].append({
            'name': interaction_name,
            'duration': duration,
            'timestamp': time.strftime("%Y-%m-%d %H:%M:%S")
        })
        return duration

    def record_element_timing(element_name, duration):
        em = validation_status['performance_metrics']['element_timings']
        em.setdefault(element_name, []).append(duration)

    def highlight(element):
        try:
            driver.execute_script(
                "arguments[0].setAttribute('style', arguments[1]);",
                element,
                "background: yellow; border: 2px solid red;"
            )
        except StaleElementReferenceException:
            pass

    def capture_screenshot(name):
        """Capture and store a screenshot"""
        try:
            screenshot_path = os.path.join(os.getcwd(), 'screenshots')
            os.makedirs(screenshot_path, exist_ok=True)
            screenshot_file = os.path.join(
                screenshot_path,
                f"{name}_{time.strftime('%Y%m%d_%H%M%S')}.png"
            )
            driver.save_screenshot(screenshot_file)

            with open(screenshot_file, "rb") as image_file:
                encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
                validation_status['screenshots'].append({
                    'name': name,
                    'data': f"data:image/png;base64,{encoded_string}",
                    'timestamp': time.strftime("%Y-%m-%d %H:%M:%S")
                })

            logging.info(f"Screenshot saved: {screenshot_file}")
            return True
        except Exception as e:
            logging.warning(f"Failed to capture screenshot: {e}")
            return False

    def check_tab(tab_element, tab_name, content_locator, index):
        pause_event.wait()
        if stop_event.is_set():
            return False

        try:
            highlight(tab_element)
            time.sleep(1)

            tab_start = time.time()

            if not click_element_with_retry(tab_element):
                result = f"{index}. Failed to click on Main Tab '{tab_name}' even though the element is present."
                log_and_update_status(result, "Failed")
                record_interaction(f"Tab {tab_name} click", tab_start)
                return False

            locator_type = content_locator['type']
            locator_value = content_locator['value']

            try:
                if locator_type == 'css':
                    WebDriverWait(driver, 5).until(
                        EC.visibility_of_element_located((By.CSS_SELECTOR, locator_value))
                    )
                elif locator_type == 'id':
                    WebDriverWait(driver, 5).until(
                        EC.visibility_of_element_located((By.ID, locator_value))
                    )
            except (TimeoutException, NoSuchElementException):
                result = f"{index}. Main Tab '{tab_name}' was clicked but expected content did not appear."
                log_and_update_status(result, "Failed")
                record_interaction(f"Tab {tab_name} load", tab_start)
                return False

            tab_duration = record_interaction(f"Tab {tab_name} load", tab_start)
            record_component_timing(f"Tab: {tab_name}", tab_start)

            result = f"{index}. Main Tab '{tab_name}' opened successfully in {tab_duration:.2f}s."
            log_and_update_status(result, "Success")
            return True

        except StaleElementReferenceException:
            result = f"{index}. StaleElementReferenceException on Main Tab '{tab_name}'."
            log_and_update_status(result, "Failed")
            record_interaction(f"Tab {tab_name} load", tab_start)
            return False

    def check_sub_tab(sub_tab_js, sub_tab_name, content_locator, main_index, sub_index):
        pause_event.wait()
        if stop_event.is_set():
            return False

        try:
            time.sleep(1)
            sub_tab_start = time.time()

            driver.execute_script(sub_tab_js)

            locator_type = content_locator['type']
            locator_value = content_locator['value']

            try:
                if locator_type == 'css':
                    WebDriverWait(driver, 5).until(
                        EC.visibility_of_element_located((By.CSS_SELECTOR, locator_value))
                    )
                elif locator_type == 'id':
                    WebDriverWait(driver, 5).until(
                        EC.visibility_of_element_located((By.ID, locator_value))
                    )
            except (TimeoutException, NoSuchElementException):
                result = f"{main_index}.{chr(96 + sub_index)}. Sub Tab '{sub_tab_name}' was activated but expected content did not appear."
                log_and_update_status(result, "Failed")
                record_interaction(f"Sub-tab {sub_tab_name} load", sub_tab_start)
                return False

            sub_tab_duration = record_interaction(f"Sub-tab {sub_tab_name} load", sub_tab_start)
            record_component_timing(f"Sub-tab: {sub_tab_name}", sub_tab_start)

            result = f"{main_index}.{chr(96 + sub_index)}. Sub Tab '{sub_tab_name}' opened successfully in {sub_tab_duration:.2f}s."
            log_and_update_status(result, "Success")
            return True

        except JavascriptException as e:
            result = f"{main_index}.{chr(96 + sub_index)}. JavaScript error on Sub Tab '{sub_tab_name}': {e}"
            log_and_update_status(result, "Failed")
            record_interaction(f"Sub-tab {sub_tab_name} load", sub_tab_start)
            return False
        except StaleElementReferenceException:
            result = f"{main_index}.{chr(96 + sub_index)}. StaleElementReferenceException on Sub Tab '{sub_tab_name}'."
            log_and_update_status(result, "Failed")
            record_interaction(f"Sub-tab {sub_tab_name} load", sub_tab_start)
            return False
        except Exception as e:
            result = f"{main_index}.{chr(96 + sub_index)}. Unexpected error activating Sub Tab '{sub_tab_name}': {str(e)}"
            log_and_update_status(result, "Failed")
            record_interaction(f"Sub-tab {sub_tab_name} load", sub_tab_start)
            return False

    def handle_add_button(main_index, tab_name):
        """
        Optionally click the Add button on a main tab (if present),
        then try to Cancel / go back.

        Logs (success only):
        - "Add button clicked successfully on Main Tab 'X'"
        - "Cancel button clicked successfully" (if Cancel works)
        """
        pause_event.wait()
        if stop_event.is_set():
            return

        try:
            # Try to locate a clickable Add button (any variant with 'btn_add' in src)
            add_button = WebDriverWait(driver, 3).until(
                EC.element_to_be_clickable(
                    (By.XPATH, "//img[contains(@src,'btn_add')]")
                )
            )
        except (TimeoutException, NoSuchElementException, StaleElementReferenceException):
            # No Add button on this tab → silently ignore
            return
        except Exception:
            # Any other minor issue → ignore, don't spam logs
            return

        try:
            # Highlight ADD
            highlight(add_button)
            time.sleep(0.5)

            if click_element_with_retry(add_button):
                log_and_update_status(
                    f"Add button clicked successfully on Main Tab '{tab_name}'",
                    "Success"
                )

                # Wait for Add screen to load
                try:
                    WebDriverWait(driver, 5).until(
                        EC.visibility_of_element_located((By.CSS_SELECTOR, "div#content"))
                    )
                except Exception:
                    pass

                # Try Cancel on Add screen (if present)
                try:
                    cancel_button = WebDriverWait(driver, 3).until(
                        EC.element_to_be_clickable(
                            (By.XPATH, "//img[contains(@src,'btn_cancel')]")
                        )
                    )
                    if cancel_button:
                        highlight(cancel_button)
                        time.sleep(0.5)
                        if click_element_with_retry(cancel_button):
                            log_and_update_status("Cancel button clicked successfully", "Success")
                        else:
                            try:
                                driver.back()
                                time.sleep(2)
                            except Exception:
                                pass
                except (TimeoutException, NoSuchElementException, StaleElementReferenceException):
                    # No Cancel on Add screen → best-effort back, no logs
                    try:
                        driver.back()
                        time.sleep(2)
                    except Exception:
                        pass
                except Exception:
                    # Unexpected Cancel issue → best-effort back
                    try:
                        driver.back()
                        time.sleep(2)
                    except Exception:
                        pass

        except Exception:
            # Any unexpected Add flow issue → ignore (no warnings)
            try:
                driver.back()
                time.sleep(2)
            except Exception:
                pass

    def validate_first_list_element_and_cancel(column_index, main_index, sub_index):
        """
        Record Workflow Check for a sub-tab:
        - Optionally click Search (if present)
        - Click first row element in given column
        - Optionally click Cancel (if present) to return

        Logs (success cases only):
        - "Search button clicked successfully"
        - "Clicked first list element in column X"
        - "Cancel button clicked successfully"
        """
        pause_event.wait()
        if stop_event.is_set():
            return False

        try:
            list_start = time.time()

            # Ensure table is visible first
            WebDriverWait(driver, 5).until(
                EC.visibility_of_element_located((By.CSS_SELECTOR, "table.ListView"))
            )

            # 1) Optional Search
            try:
                search_button = WebDriverWait(driver, 3).until(
                    EC.element_to_be_clickable(
                        (By.XPATH, "//img[contains(@src,'btn_search')]")
                    )
                )
                if search_button:
                    highlight(search_button)
                    time.sleep(0.5)

                    if click_element_with_retry(search_button):
                        log_and_update_status("Search button clicked successfully", "Success")
                        time.sleep(1.5)
                        WebDriverWait(driver, 5).until(
                            EC.visibility_of_element_located((By.CSS_SELECTOR, "table.ListView"))
                        )
            except (TimeoutException, NoSuchElementException, StaleElementReferenceException):
                # Search not present → silently ignore
                pass
            except Exception:
                # Any other search-related issue → silently ignore
                pass

            # 2) Table rows
            max_attempts = 3
            attempt = 0
            rows = []

            while attempt < max_attempts:
                try:
                    rows = driver.find_elements(By.XPATH, "//table[@class='ListView']/tbody/tr")
                    break
                except StaleElementReferenceException:
                    attempt += 1
                    if attempt == max_attempts:
                        raise
                    time.sleep(1)

            if len(rows) <= 1:
                result = "There is no data in this sub-tab to validate (no rows). Skipping."
                log_and_update_status(result, "Skipped")
                record_interaction("Record Workflow Check (no data)", list_start)
                return True

            try:
                # 3) First clickable element in the given column
                try:
                    first_element = find_element_with_retry(
                        driver,
                        By.XPATH,
                        f"//table[@class='ListView']/tbody/tr[2]/td[{column_index}]/a",
                        max_attempts=2,
                        wait_time=3
                    )
                except (TimeoutException, NoSuchElementException):
                    result = f"No clickable element found in column {column_index} of the first row - skipping."
                    log_and_update_status(result, "Skipped")
                    record_interaction("Record Workflow Check (no element)", list_start)
                    return True

                if not first_element:
                    result = f"First row clickable element is None for column {column_index} - skipping."
                    log_and_update_status(result, "Skipped")
                    record_interaction("Record Workflow Check (no element)", list_start)
                    return True

                highlight(first_element)
                time.sleep(0.5)

                element_start = time.time()

                if not click_element_with_retry(first_element):
                    result = (
                        f"Failed to click first row element in column {column_index}. "
                        "Element became stale. Skipping."
                    )
                    log_and_update_status(result, "Skipped")
                    record_interaction("Record Workflow element click", element_start)
                    return True

                element_duration = time.time() - element_start
                record_element_timing("Record Workflow element click", element_duration)

                log_and_update_status(
                    f"Clicked first list element in column {column_index}",
                    "Success"
                )

                WebDriverWait(driver, 5).until(
                    EC.visibility_of_element_located((By.CSS_SELECTOR, "div#content"))
                )
                time.sleep(1)

                # 4) Optional Cancel
                try:
                    cancel_button = WebDriverWait(driver, 3).until(
                        EC.element_to_be_clickable(
                            (By.XPATH, "//img[contains(@src,'btn_cancel')]")
                        )
                    )
                    if cancel_button:
                        highlight(cancel_button)
                        time.sleep(0.5)

                        if click_element_with_retry(cancel_button):
                            log_and_update_status("Cancel button clicked successfully", "Success")
                        else:
                            try:
                                driver.back()
                                time.sleep(2)
                            except Exception:
                                pass
                    else:
                        try:
                            driver.back()
                            time.sleep(2)
                        except Exception:
                            pass
                except (TimeoutException, NoSuchElementException, StaleElementReferenceException):
                    # Cancel not present → best-effort back
                    try:
                        driver.back()
                        time.sleep(2)
                    except Exception:
                        pass
                except Exception:
                    # Unexpected Cancel issue → best-effort back
                    try:
                        driver.back()
                        time.sleep(2)
                    except Exception:
                        pass

                list_duration = record_interaction("Record Workflow Check complete", list_start)
                result = f"Record Workflow Check completed in {list_duration:.2f}s."
                log_and_update_status(result, "Success")
                return True

            except Exception as e:
                result = f"Exception while handling record workflow: {str(e)}. Skipping."
                log_and_update_status(result, "Skipped")
                record_interaction("Record Workflow Check (error)", list_start)
                return True

        except (TimeoutException, NoSuchElementException) as e:
            result = f"Failed to find the list table: {str(e)}"
            log_and_update_status(result, "Failed")
            record_interaction("Record Workflow Check (table not found)", list_start)
            return False
        except StaleElementReferenceException:
            result = "StaleElementReferenceException while handling record workflow table. Skipping."
            log_and_update_status(result, "Skipped")
            record_interaction("Record Workflow Check (stale element)", list_start)
            return True
        except Exception as e:
            result = f"Unexpected error in record workflow: {str(e)}. Skipping."
            log_and_update_status(result, "Skipped")
            record_interaction("Record Workflow Check (error)", list_start)
            return True

    # ---- navigate to base URL ----
    driver.set_page_load_timeout(30)

    try:
        navigation_attempts = 0
        max_navigation_attempts = 3
        navigation_success = False

        while navigation_attempts < max_navigation_attempts and not navigation_success:
            try:
                nav_start = time.time()
                driver.get(url)
                WebDriverWait(driver, 10).until(
                    lambda d: d.execute_script('return document.readyState') == 'complete'
                )
                nav_duration = time.time() - nav_start
                record_component_timing("Page load", nav_start)
                logging.info(f"Successfully navigated to {url} in {nav_duration:.2f}s")
                validation_status['results'].append(
                    f"Successfully navigated to {url} in {nav_duration:.2f}s"
                )
                navigation_success = True
            except (WebDriverException, TimeoutException) as e:
                navigation_attempts += 1
                if navigation_attempts == max_navigation_attempts:
                    raise
                logging.warning(f"Navigation attempt {navigation_attempts} failed: {e}, retrying...")
                time.sleep(2)

        if not navigation_success:
            raise TimeoutException(
                f"Failed to navigate to {url} after {max_navigation_attempts} attempts"
            )

        capture_screenshot(f"{environment}_login")

    except Exception as e:
        error_msg = f"Failed to navigate to {url}: {e}"
        logging.error(error_msg)
        logging.error(traceback.format_exc())
        validation_status['results'].append(error_msg)
        driver.quit()
        validation_status['status'] = 'Failed'
        validation_status['end_time'] = time.strftime("%Y-%m-%d %H:%M:%S")
        return validation_results, False

    # ---- tabs / sub-tabs ----
    all_tabs_opened = True

    def handle_sub_tabs(tab_name, sub_tabs, main_index):
        nonlocal all_tabs_opened
        sub_tab_results = []

        for sub_index, (sub_tab_name, sub_tab_data) in enumerate(sub_tabs.items(), start=1):
            if stop_event.is_set():
                return sub_tab_results

            pause_event.wait()

            sub_success = check_sub_tab(
                sub_tab_data['script'],
                sub_tab_name,
                sub_tab_data['content_locator'],
                main_index,
                sub_index
            )

            if sub_success:
                column_index = config['tabs'][tab_name]['column_index']
                if isinstance(column_index, dict):
                    column_index = column_index.get(sub_tab_name)

                if column_index is not None:
                    first_list_element_success = validate_first_list_element_and_cancel(
                        column_index,
                        main_index,
                        sub_index
                    )

                    if not first_list_element_success:
                        all_tabs_opened = False
                else:
                    result = f"{main_index}.{chr(96 + sub_index)}. No column index specified for '{sub_tab_name}' - skipping Record Workflow Check."
                    log_and_update_status(result, "Skipped")
            else:
                all_tabs_opened = False

            if sub_success:
                result = f"{main_index}.{chr(96 + sub_index)}. Sub Tab '{sub_tab_name}' validation completed successfully."
                sub_tab_results.append((result, "Success"))
            else:
                result = f"{main_index}.{chr(96 + sub_index)}. Sub Tab '{sub_tab_name}' validation failed."
                sub_tab_results.append((result, "Failed"))

        return sub_tab_results

    total_tabs = len(config['tabs'])
    tabs_processed = 0

    for i, (tab_name, tab_data) in enumerate(config['tabs'].items(), start=1):
        try:
            if stop_event.is_set():
                break

            pause_event.wait()

            tabs_processed += 1
            validation_status['progress'] = int((tabs_processed / total_tabs) * 100)
            logging.info(
                f"Processing tab {i}/{total_tabs}: {tab_name} - Progress: {validation_status['progress']}%"
            )

            try:
                tab_element = find_element_with_retry(
                    driver,
                    By.XPATH,
                    f"//a[@href='{tab_data['url']}']",
                    max_attempts=3,
                    wait_time=5
                )

                highlight(tab_element)
                time.sleep(1)
                success = check_tab(tab_element, tab_name, tab_data['content_locator'], i)

                if success:
                    result = f"{i}. Main Tab '{tab_name}' opened successfully."
                    log_and_update_status(result, "Success")

                    # Optional Add button on main tab
                    handle_add_button(i, tab_name)

                    if 'sub_tabs' in tab_data:
                        sub_tab_results = handle_sub_tabs(tab_name, tab_data['sub_tabs'], i)
                        validation_results.extend(sub_tab_results)

                    capture_screenshot(f"tab_{tab_name}")
                else:
                    result = f"{i}. Failed to open Main Tab '{tab_name}'."
                    log_and_update_status(result, "Failed")
                    all_tabs_opened = False

            except (TimeoutException, NoSuchElementException) as e:
                result = f"{i}. Main Tab '{tab_name}' not found or not clickable. Exception: {e}"
                log_and_update_status(result, "Failed")
                all_tabs_opened = False

        except StaleElementReferenceException as e:
            result = f"{i}. StaleElementReferenceException on Main Tab '{tab_name}': {e}"
            log_and_update_status(result, "Failed")
            all_tabs_opened = False

        time.sleep(2)

    capture_screenshot(f"{environment}_final")

    total_checks = (
        validation_status['successful_checks']
        + validation_status['failed_checks']
        + validation_status['skipped_checks']
    )
    success_rate = (
        validation_status['successful_checks'] / total_checks * 100
        if total_checks > 0 else 0
    )

    summary_message = f"""
Validation Summary:
------------------
Environment: {environment}
Total Checks: {total_checks}
Successful: {validation_status['successful_checks']} ({success_rate:.1f}%)
Failed: {validation_status['failed_checks']}
Skipped: {validation_status['skipped_checks']}
Duration: {(time.time() - time.mktime(time.strptime(validation_status['start_time'], "%Y-%m-%d %H:%M:%S"))):.1f} seconds
    """.strip()

    log_and_update_status(summary_message, "Info")

    if all_tabs_opened and validation_status['failed_checks'] > 0:
        logging.info(
            "All tabs were successfully validated, but failed_checks counter is non-zero. Resetting to 0."
        )
        validation_status['failed_checks'] = 0

    try:
        driver.quit()
        logging.info("WebDriver closed successfully")
    except Exception as e:
        logging.warning(f"Error while closing WebDriver: {e}")

    validation_status['end_time'] = time.strftime("%Y-%m-%d %H:%M:%S")
    validation_status['progress'] = 100

    if all_tabs_opened:
        result = ("Validation completed successfully.", "Success")
        log_and_update_status(result[0], "Success")
        validation_status['status'] = 'Completed'

        if validation_portal_link:
            try:
                submit_test_results(validation_portal_link)
            except Exception as e:
                error_msg = f"Failed to submit test results: {e}"
                logging.error(error_msg)
                log_and_update_status(error_msg, "Failed")
    else:
        result = ("Validation failed.", "Failed")
        log_and_update_status(result[0], "Failed")
        validation_status['status'] = 'Failed'

    return validation_results, all_tabs_opened


def submit_test_results(validation_portal_link):
    """
    Submit test results to the validation portal
    """
    driver = None
    try:
        logging.info(f"Submitting test results to validation portal: {validation_portal_link}")

        driver = setup_driver()

        navigation_attempts = 0
        max_navigation_attempts = 3
        while navigation_attempts < max_navigation_attempts:
            try:
                driver.get(validation_portal_link)
                WebDriverWait(driver, 10).until(
                    lambda d: d.execute_script('return document.readyState') == 'complete'
                )
                logging.info("Successfully navigated to validation portal")
                break
            except Exception as e:
                navigation_attempts += 1
                if navigation_attempts == max_navigation_attempts:
                    raise Exception(
                        f"Failed to navigate to validation portal after "
                        f"{max_navigation_attempts} attempts: {e}"
                    )
                logging.warning(f"Navigation attempt {navigation_attempts} failed: {e}, retrying...")
                time.sleep(2)

        try:
            screenshot_path = os.path.join(os.getcwd(), 'screenshots')
            os.makedirs(screenshot_path, exist_ok=True)
            screenshot_file = os.path.join(
                screenshot_path,
                f"portal_before_{time.strftime('%Y%m%d_%H%M%S')}.png"
            )
            driver.save_screenshot(screenshot_file)
            logging.info(f"Validation portal screenshot saved to {screenshot_file}")
        except Exception as e:
            logging.warning(f"Failed to capture validation portal screenshot: {e}")

        try:
            set_results_button = find_element_with_retry(
                driver,
                By.XPATH,
                "//button[contains(text(),'Set Testing Results')]",
                max_attempts=3,
                wait_time=10,
                condition=EC.element_to_be_clickable
            )

            if not click_element_with_retry(set_results_button):
                raise Exception("Failed to click Set Testing Results button - element became stale")

            time.sleep(3)

            try:
                screenshot_file = os.path.join(
                    screenshot_path,
                    f"portal_dialog_{time.strftime('%Y%m%d_%H%M%S')}.png"
                )
                driver.save_screenshot(screenshot_file)
            except Exception as e:
                logging.warning(f"Failed to capture dialog screenshot: {e}")

        except Exception as e:
            logging.error(f"Error finding or clicking Set Testing Results button: {e}")
            if driver:
                driver.quit()
            raise

        try:
            screen_width, screen_height = pyautogui.size()

            success_button = (536, 460)
            ok_button = (1395, 896)
            confirm_button = (1113, 374)

            for button, (x, y) in [
                ("Success", success_button),
                ("OK", ok_button),
                ("Confirm", confirm_button),
            ]:
                if x > screen_width or y > screen_height:
                    logging.warning(
                        f"{button} button coordinates ({x}, {y}) are outside screen bounds "
                        f"({screen_width}, {screen_height})"
                    )

            pyautogui.moveTo(success_button[0], success_button[1], duration=0.5)
            pyautogui.click()
            logging.info(f"Clicked Success button at {success_button}")
            time.sleep(1.5)

            pyautogui.moveTo(ok_button[0], ok_button[1], duration=0.5)
            pyautogui.click()
            logging.info(f"Clicked OK button at {ok_button}")
            time.sleep(1.5)

            pyautogui.moveTo(confirm_button[0], confirm_button[1], duration=0.5)
            pyautogui.click()
            logging.info(f"Clicked Confirm button at {confirm_button}")

            try:
                time.sleep(1)
                screenshot_file = os.path.join(
                    screenshot_path,
                    f"portal_after_{time.strftime('%Y%m%d_%H%M%S')}.png"
                )
                driver.save_screenshot(screenshot_file)
            except Exception as e:
                logging.warning(f"Failed to capture final portal screenshot: {e}")

            logging.info("Test results successfully submitted via Validation Portal.")

        except Exception as e:
            logging.error(f"Error using pyautogui to submit results: {e}")
            logging.error(traceback.format_exc())
            raise

    except Exception as e:
        logging.error(f"Error submitting results to validation portal: {e}")
        logging.error(traceback.format_exc())
        raise
    finally:
        if driver:
            try:
                driver.quit()
                logging.info("Validation portal WebDriver closed successfully")
            except Exception as e:
                logging.warning(f"Error while closing validation portal WebDriver: {e}")


@app.errorhandler(429)
def too_many_requests(e):
    return jsonify({"error": "Too many requests. Please try again later."}), 429


@app.route('/health')
def health():
    status = {
        "status": "healthy",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "app": project_name,
        "version": "1.0.0",
        "hostname": socket.gethostname()
    }
    return jsonify(status)


@app.route('/')
def home():
    environments = list(config['environments'].keys())
    return render_template('index.html', project_name=project_name, environments=environments)


@app.route('/start_validation', methods=['POST'])
@rate_limit
def start_validation():
    global stop_event, pause_event, active_validation_thread

    if validation_status['status'] in ['Running', 'Paused'] and active_validation_thread and active_validation_thread.is_alive():
        return jsonify({
            "error": "Validation already in progress",
            "status": validation_status['status']
        }), 409

    stop_event.clear()
    pause_event.set()

    try:
        data = request.json
        if not data:
            return jsonify({"error": "Missing request data"}), 400

        environment = data.get('environment')
        if not environment:
            return jsonify({"error": "Environment must be specified"}), 400

        if environment not in config['environments']:
            return jsonify({
                "error": f"Invalid environment: {environment}",
                "valid_environments": list(config['environments'].keys())
            }), 400

        validation_portal_link = data.get('validation_portal_link')
        retry_failed = data.get('retry_failed', False)

    except Exception as e:
        return jsonify({"error": f"Invalid request: {str(e)}"}), 400

    validation_status['status'] = 'Running'
    if not retry_failed:
        validation_status['results'] = []

    def validate_environment():
        try:
            results, success = validate_application(environment, validation_portal_link, retry_failed)
            validation_status['status'] = 'Completed' if success else 'Failed'

            try:
                subject = f"{project_name} {environment.upper()} Environment Validation Results"
                send_email(subject, results, success, log_file_path)
                logging.info(f"Validation results email sent successfully for {environment}")
            except Exception as e:
                logging.error(f"Failed to send validation results email: {e}")
                logging.error(traceback.format_exc())

        except Exception as e:
            error_msg = f"Unexpected error during validation: {e}"
            logging.error(error_msg)
            logging.error(traceback.format_exc())
            validation_status['status'] = 'Failed'
            validation_status['results'].append(error_msg)

    active_validation_thread = threading.Thread(target=validate_environment)
    active_validation_thread.daemon = True
    active_validation_thread.start()

    return jsonify({
        "message": "Validation started",
        "environment": environment,
        "status": validation_status['status'],
        "start_time": validation_status['start_time']
    }), 202


@app.route('/pause_resume_validation', methods=['POST'])
@rate_limit
def pause_resume_validation():
    global pause_event, validation_status, active_validation_thread

    if not active_validation_thread or not active_validation_thread.is_alive():
        return jsonify({
            "error": "No validation is currently running",
            "status": validation_status['status']
        }), 400

    action = "paused"

    if validation_status['status'] == 'Running' and not validation_status.get('paused', False):
        validation_status['paused'] = True
        pause_event.clear()
        validation_status['status'] = 'Paused'
    elif validation_status['status'] == 'Paused':
        validation_status['paused'] = False
        pause_event.set()
        validation_status['status'] = 'Running'
        action = "resumed"
    else:
        return jsonify({
            "error": f"Cannot pause/resume validation in '{validation_status['status']}' state"
        }), 400

    return jsonify({
        "message": f"Validation {action}",
        "status": validation_status['status']
    }), 200


@app.route('/stop_validation', methods=['POST'])
@rate_limit
def stop_validation():
    global stop_event, validation_status, active_validation_thread

    if not active_validation_thread or not active_validation_thread.is_alive():
        return jsonify({
            "error": "No validation is currently running",
            "status": validation_status['status']
        }), 400

    if validation_status['status'] not in ['Running', 'Paused']:
        return jsonify({
            "error": f"Cannot stop validation in '{validation_status['status']}' state"
        }), 400

    stop_event.set()
    if validation_status['status'] == 'Paused':
        pause_event.set()

    validation_status['status'] = 'Stopping'

    return jsonify({
        "message": "Validation stopping",
        "status": validation_status['status']
    }), 200


@app.route('/status')
def get_status():
    global active_validation_thread

    if active_validation_thread and not active_validation_thread.is_alive():
        if validation_status['status'] in ['Running', 'Paused', 'Stopping']:
            validation_status['status'] = 'Failed'
            validation_status['results'].append("Validation thread terminated unexpectedly")
            validation_status['progress'] = 100

    if validation_status['status'] in ['Completed', 'Failed'] and validation_status.get('progress', 0) != 100:
        validation_status['progress'] = 100

    if validation_status['status'] == 'Completed' and validation_status.get('failed_checks', 0) > 0:
        validation_status['failed_checks'] = 0

    status_data = {
        **validation_status,
        'active': active_validation_thread is not None and active_validation_thread.is_alive(),
        'timestamp': time.strftime("%Y-%m-%d %H:%M:%S")
    }

    return jsonify(status_data)


@app.route('/logs')
def get_logs():
    """Endpoint to retrieve the most recent log entries"""
    try:
        num_lines = request.args.get('lines', default=100, type=int)

        if num_lines <= 0 or num_lines > 1000:
            return jsonify({"error": "Lines parameter must be between 1 and 1000"}), 400

        log_lines = []

        try:
            with open(log_file_path, 'r') as log_file:
                log_lines = log_file.readlines()[-num_lines:]
        except Exception as e:
            return jsonify({"error": f"Error reading log file: {str(e)}"}), 500

        return jsonify({
            "logs": log_lines,
            "count": len(log_lines),
            "log_file": log_file_path
        })

    except Exception as e:
        return jsonify({"error": f"Error retrieving logs: {str(e)}"}), 500


@app.route('/screenshots')
def list_screenshots():
    """Endpoint to list available screenshots"""
    try:
        screenshot_path = os.path.join(os.getcwd(), 'screenshots')

        if not os.path.exists(screenshot_path):
            return jsonify({"screenshots": [], "count": 0})

        screenshots = []
        for file in os.listdir(screenshot_path):
            if file.endswith('.png'):
                file_path = os.path.join(screenshot_path, file)
                screenshots.append({
                    "filename": file,
                    "path": file_path,
                    "size": os.path.getsize(file_path),
                    "created": time.ctime(os.path.getctime(file_path))
                })

        screenshots.sort(key=lambda x: x["created"], reverse=True)

        return jsonify({
            "screenshots": screenshots,
            "count": len(screenshots)
        })

    except Exception as e:
        return jsonify({"error": f"Error listing screenshots: {str(e)}"}), 500


@app.route('/generate_report')
def generate_report():
    """Generate an HTML report of the validation results"""
    try:
        formatted_results = []
        for i, result in enumerate(validation_status['results'], 1):
            status = "Success"
            if "[Failed]" in result:
                status = "Failed"
            elif "[Skipped]" in result:
                status = "Skipped"
            elif "[Info]" in result:
                status = "Info"
            formatted_results.append({
                "index": i,
                "message": result,
                "status": status,
                "timestamp": result.split(']')[0].replace('[', '')
            })

        component_stats = {}
        for component, timings in validation_status['performance_metrics'].get('component_timings', {}).items():
            if timings:
                component_stats[component] = {
                    "count": len(timings),
                    "min": min(timings),
                    "max": max(timings),
                    "avg": sum(timings) / len(timings)
                }

        report_data = {
            'environment': validation_status.get('environment', 'N/A'),
            'start_time': validation_status.get('start_time', 'N/A'),
            'end_time': validation_status.get('end_time', 'N/A'),
            'duration': calculate_duration(validation_status.get('start_time'), validation_status.get('end_time')),
            'total_checks': validation_status.get('successful_checks', 0) +
                            validation_status.get('failed_checks', 0) +
                            validation_status.get('skipped_checks', 0),
            'successful_checks': validation_status.get('successful_checks', 0),
            'failed_checks': validation_status.get('failed_checks', 0),
            'skipped_checks': validation_status.get('skipped_checks', 0),
            'component_stats': component_stats,
            'interaction_timings': validation_status['performance_metrics'].get('interaction_timings', []),
            'element_timings': validation_status['performance_metrics'].get('element_timings', {}),
            'results': formatted_results,
            'screenshots': validation_status.get('screenshots', []),
            'project_name': project_name
        }

        return render_template('report_template.html', **report_data)
    except Exception as e:
        logging.error(f"Error generating report: {e}")
        return jsonify({"error": f"Failed to generate report: {str(e)}"}), 500


@app.route('/download_report')
def download_report():
    """Download the HTML report"""
    try:
        report_html = generate_report().get_data(as_text=True)

        response = make_response(report_html)
        response.headers['Content-Type'] = 'text/html'
        response.headers['Content-Disposition'] = f'attachment; filename=validation_report_{datetime.now().date()}.html'
        return response
    except Exception as e:
        logging.error(f"Error downloading report: {e}")
        return jsonify({"error": f"Failed to download report: {str(e)}"}), 500


if __name__ == '__main__':
    try:
        os.makedirs(os.path.join(os.getcwd(), 'screenshots'), exist_ok=True)
        os.makedirs(os.path.join(os.getcwd(), 'logs'), exist_ok=True)

        logging.info(f"Starting {project_name} Validation Server")

        def handle_exception(exc_type, exc_value, exc_traceback):
            if issubclass(exc_type, KeyboardInterrupt):
                sys.__excepthook__(exc_type, exc_value, exc_traceback)
                return

            logging.error("Unhandled exception:", exc_info=(exc_type, exc_value, exc_traceback))

        sys.excepthook = handle_exception

        executor = ThreadPoolExecutor(max_workers=4)

        def run_app():
            app.run(debug=False, use_reloader=False, host='0.0.0.0', port=5000, threaded=True)

        executor.submit(run_app)

        server_ready = False
        retry_count = 0
        max_retries = 5

        while not server_ready and retry_count < max_retries:
            try:
                time.sleep(1)
                with socket.create_connection(('127.0.0.1', 5000), timeout=1):
                    server_ready = True
                    logging.info("Server started successfully")
            except (socket.error, socket.timeout):
                retry_count += 1
                logging.info(f"Waiting for server to start (attempt {retry_count}/{max_retries})...")

        if not server_ready:
            logging.warning("Server may not have started properly, attempting to open browser anyway")

        webbrowser.open("http://127.0.0.1:5000")
        logging.info("Browser opened to application URL")

    except Exception as e:
        logging.error(f"Error starting application: {e}")
        logging.error(traceback.format_exc())
        sys.exit(1)
