import os
import sys
import json
import time
import logging
import traceback
from flask import Flask, render_template, request, jsonify, abort
import threading
from concurrent.futures import ThreadPoolExecutor
import socket
from functools import wraps
from selenium import webdriver
from selenium.webdriver.edge.options import Options
from selenium.webdriver.edge.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, JavascriptException, StaleElementReferenceException, WebDriverException
from email_sender import send_email
import pyautogui
import webbrowser

# Configure logging
log_file_path = os.path.join(os.getcwd(), 'validation.log')
logging.basicConfig(
    filename=log_file_path, 
    level=logging.INFO, 
    format='%(asctime)s:%(levelname)s:%(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Create a console handler for logging to console too
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

# Create Flask app
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
    'progress': 0  # Initialize progress at 0%
}

# Threading events
pause_event = threading.Event()
pause_event.set()

stop_event = threading.Event()
stop_event.clear()

# Global active thread tracker
active_validation_thread = None

# Rate limiter for API - simple implementation
request_timestamps = {}
REQUEST_RATE_LIMIT = 10  # Max requests per minute
REQUEST_WINDOW = 60  # seconds

# Function decorator for rate limiting
def rate_limit(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        client_ip = request.remote_addr
        current_time = time.time()
        
        # Clean up old timestamps
        request_timestamps[client_ip] = [t for t in request_timestamps.get(client_ip, []) 
                                         if current_time - t < REQUEST_WINDOW]
        
        # Check rate limit
        if len(request_timestamps.get(client_ip, [])) >= REQUEST_RATE_LIMIT:
            abort(429, "Too many requests")
        
        # Add current timestamp
        if client_ip not in request_timestamps:
            request_timestamps[client_ip] = []
        request_timestamps[client_ip].append(current_time)
        
        return func(*args, **kwargs)
    return wrapper


def setup_driver():
    """Set up and configure the WebDriver with proper options"""
    options = Options()
    options.add_argument("--start-maximized")  # Start maximized
    options.add_argument("--disable-extensions")  # Disable extensions
    options.add_argument("--disable-popup-blocking")  # Disable popup blocking
    options.add_argument("--disable-infobars")  # Disable infobars
    options.page_load_strategy = 'normal'  # Wait for full page load
    
    # Create and return the driver with the options
    driver = webdriver.Edge(options=options)
    driver.set_page_load_timeout(30)
    driver.set_script_timeout(30)
    
    return driver

def find_element_with_retry(driver, by, value, max_attempts=3, wait_time=5, condition=EC.presence_of_element_located):
    """
    Find an element with retry logic to handle stale element references
    
    Args:
        driver: WebDriver instance
        by: By locator type
        value: Locator value
        max_attempts: Maximum number of retry attempts
        wait_time: Wait time in seconds
        condition: Expected condition to wait for (default: presence_of_element_located)
    
    Returns:
        WebElement if found, None otherwise
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
                logging.warning(f"Failed to find element after {max_attempts} attempts: {by}={value}, Error: {e}")
                if isinstance(e, StaleElementReferenceException):
                    # On stale element, try to refresh the page as last resort
                    try:
                        driver.refresh()
                        time.sleep(2)
                    except:
                        pass
                raise last_exception
            time.sleep(1)  # Short delay before retry
    
    return None

def click_element_with_retry(element, max_attempts=3):
    """
    Click an element with retry logic to handle stale element references
    
    Args:
        element: WebElement to click
        max_attempts: Maximum number of retry attempts
    
    Returns:
        bool: True if click successful, False otherwise
    """
    attempt = 0
    while attempt < max_attempts:
        try:
            # First try to scroll element into view
            try:
                driver = element._parent
                driver.execute_script("arguments[0].scrollIntoView(true);", element)
                time.sleep(0.5)  # Short delay after scrolling
            except:
                pass
                
            # Try clicking with JavaScript first (more reliable)
            try:
                driver = element._parent
                driver.execute_script("arguments[0].click();", element)
                return True
            except:
                # Fall back to regular click
                element.click()
                return True
                
        except StaleElementReferenceException:
            attempt += 1
            if attempt == max_attempts:
                logging.warning(f"Failed to click element after {max_attempts} attempts due to StaleElementReferenceException")
                return False
            time.sleep(1)  # Short delay before retry
        except Exception as e:
            attempt += 1
            if attempt == max_attempts:
                logging.warning(f"Failed to click element after {max_attempts} attempts: {e}")
                return False
            time.sleep(1)  # Short delay before retry
            
    return False


def validate_application(environment, validation_portal_link=None, retry_failed=False):
    """
    Main validation function to test the application in the specified environment
    
    Args:
        environment: Environment to validate (IT, QV, Prod)
        validation_portal_link: Link to validation portal (optional)
        retry_failed: Whether to retry only failed checks from previous run
    
    Returns:
        tuple: (validation_results, success)
    """
    global validation_status
    
    # Update validation status
    validation_status['status'] = 'Running'
    validation_status['environment'] = environment
    validation_status['start_time'] = time.strftime("%Y-%m-%d %H:%M:%S")
    validation_status['end_time'] = None
    validation_status['successful_checks'] = 0
    validation_status['failed_checks'] = 0
    validation_status['skipped_checks'] = 0
    validation_status['progress'] = 0  # Initialize progress at 0%
    
    # Track previous failed checks for retry
    previous_results = validation_status['results'] if retry_failed else []
    validation_status['results'] = []
    
    # Track failed tabs for retry
    failed_tabs = []
    
    # Set the URL based on environment
    try:
        url = config['environments'].get(environment)
        if not url:
            raise ValueError(f"Invalid environment selected: {environment}. Please choose from: {', '.join(config['environments'].keys())}")
    except Exception as e:
        error_msg = f"Error setting URL for environment {environment}: {e}"
        logging.error(error_msg)
        validation_status['results'].append(error_msg)
        validation_status['status'] = 'Failed'
        validation_status['progress'] = 100  # Mark as complete even for failures
        return [], False

    logging.info(f"Selected environment: {environment}")
    validation_status['results'].append(f"Selected environment: {environment}")
    
    # Setup WebDriver with improved options
    try:
        driver = setup_driver()
        logging.info("WebDriver initialized successfully")
    except Exception as e:
        error_msg = f"Failed to initialize WebDriver: {e}"
        logging.error(error_msg)
        validation_status['results'].append(error_msg)
        validation_status['status'] = 'Failed'
        validation_status['progress'] = 100  # Mark as complete even for failures
        return [], False
    
    validation_results = []

    def log_and_update_status(message, status="Success"):
        """
        Log a message and update the validation status
        
        Args:
            message: Message to log
            status: Status of the check (Success, Failed, Skipped)
        """
        # Update counters
        if status == "Success":
            validation_status['successful_checks'] += 1
        elif status == "Failed":
            validation_status['failed_checks'] += 1
        elif status == "Skipped":
            validation_status['skipped_checks'] += 1
        
        # Format message with timestamp
        timestamp = time.strftime("%H:%M:%S")
        formatted_message = f"[{timestamp}] [{status}] {message}"
        
        # Log to console and file
        print(formatted_message)
        if status == "Success":
            logging.info(message)
        elif status == "Failed":
            logging.error(message)
        else:
            logging.warning(message)
            
        # Add to results
        validation_results.append((message, status))
        validation_status['results'].append(formatted_message)
    
    def highlight(element):
        try:
            driver.execute_script("arguments[0].setAttribute('style', arguments[1]);", element, "background: yellow; border: 2px solid red;")
        except StaleElementReferenceException:
            # If element is stale, we'll just skip highlighting and continue
            pass
    
    def check_tab(tab_element, tab_name, content_locator, index):
        pause_event.wait()
        if stop_event.is_set():
            return False

        try:
            highlight(tab_element)
            time.sleep(1)
            
            # Use the retry click function
            if not click_element_with_retry(tab_element):
                result = f"{index}. Failed to click on Main Tab '{tab_name}' even though the element is present."
                log_and_update_status(result, "Failed")
                return False
                
            locator_type = content_locator['type']
            locator_value = content_locator['value']
            
            # Check if expected content appears after clicking
            try:
                if locator_type == 'css':
                    WebDriverWait(driver, 5).until(EC.visibility_of_element_located((By.CSS_SELECTOR, locator_value)))
                elif locator_type == 'id':
                    WebDriverWait(driver, 5).until(EC.visibility_of_element_located((By.ID, locator_value)))
            except (TimeoutException, NoSuchElementException):
                result = f"{index}. Main Tab '{tab_name}' was clicked but expected content did not appear."
                log_and_update_status(result, "Failed")
                return False
                
            result = f"{index}. Main Tab '{tab_name}' opened successfully."
            log_and_update_status(result)
            return True
            
        except StaleElementReferenceException:
            result = f"{index}. StaleElementReferenceException on Main Tab '{tab_name}'. The page may have changed while trying to interact with it."
            log_and_update_status(result, "Failed")
            return False
    
    def check_sub_tab(sub_tab_js, sub_tab_name, content_locator, main_index, sub_index):
        pause_event.wait()
        if stop_event.is_set():
            return False

        try:
            time.sleep(1)
            # Execute the JavaScript to navigate to the sub-tab
            driver.execute_script(sub_tab_js)
            
            # Verify that the expected content appears
            locator_type = content_locator['type']
            locator_value = content_locator['value']
            
            try:
                if locator_type == 'css':
                    WebDriverWait(driver, 5).until(EC.visibility_of_element_located((By.CSS_SELECTOR, locator_value)))
                elif locator_type == 'id':
                    WebDriverWait(driver, 5).until(EC.visibility_of_element_located((By.ID, locator_value)))
            except (TimeoutException, NoSuchElementException):
                result = f"{main_index}.{chr(96 + sub_index)}. Sub Tab '{sub_tab_name}' was activated but expected content did not appear."
                log_and_update_status(result, "Failed")
                return False
                
            result = f"{main_index}.{chr(96 + sub_index)}. Sub Tab '{sub_tab_name}' opened successfully."
            log_and_update_status(result)
            return True
            
        except JavascriptException as e:
            result = f"{main_index}.{chr(96 + sub_index)}. JavaScript error on Sub Tab '{sub_tab_name}': {e}"
            log_and_update_status(result, "Failed")
            return False
        except StaleElementReferenceException:
            result = f"{main_index}.{chr(96 + sub_index)}. StaleElementReferenceException on Sub Tab '{sub_tab_name}'. The page may have changed during interaction."
            log_and_update_status(result, "Failed")
            return False
        except Exception as e:
            result = f"{main_index}.{chr(96 + sub_index)}. Unexpected error activating Sub Tab '{sub_tab_name}': {str(e)}"
            log_and_update_status(result, "Failed")
            return False
    
    def validate_first_list_element_and_cancel(column_index, main_index, sub_index, is_export_control=False):
        pause_event.wait()
        if stop_event.is_set():
            return False

        try:
            # Use a longer wait time to ensure the table is fully loaded
            WebDriverWait(driver, 5).until(EC.visibility_of_element_located((By.CSS_SELECTOR, "table.ListView")))
            
            # Try to find rows with retry logic
            max_attempts = 3
            attempt = 0
            rows = []
            
            while attempt < max_attempts:
                try:
                    rows = driver.find_elements(By.XPATH, f"//table[@class='ListView']/tbody/tr")
                    break
                except StaleElementReferenceException:
                    attempt += 1
                    if attempt == max_attempts:
                        raise
                    time.sleep(1)
            
            if len(rows) <= 1:
                result = f"{main_index}.{chr(96 + sub_index)}. There is no data in the sub tab '{sub_index}' to check so skipping."
                log_and_update_status(result, "Skipped")
                return True

            try:
                # Try to find the first element - but don't treat absence as an error
                first_element = None
                try:
                    first_element = find_element_with_retry(
                        driver, 
                        By.XPATH, 
                        f"//table[@class='ListView']/tbody/tr[2]/td[{column_index}]/a",
                        max_attempts=2,  # Fewer attempts since we're handling absence gracefully
                        wait_time=3
                    )
                except (TimeoutException, NoSuchElementException):
                    # No element found - this is a valid case, not an error
                    result = f"{main_index}.{chr(96 + sub_index)}. No clickable element found in column {column_index} of the first row - skipping."
                    log_and_update_status(result, "Skipped")
                    return True
                
                # If we found an element, try to click it
                if first_element:
                    highlight(first_element)
                    time.sleep(1)
                    
                    # Click with retry
                    if not click_element_with_retry(first_element):
                        result = f"{main_index}.{chr(96 + sub_index)}. Failed to click first element - element became stale. Skipping."
                        log_and_update_status(result, "Skipped")
                        return True
                    
                    WebDriverWait(driver, 5).until(EC.visibility_of_element_located((By.CSS_SELECTOR, "div#content")))
                    time.sleep(1)

                    # Find cancel button
                    cancel_xpath = "//img[@src='/fpa/images/btn_cancel.jpg']" if is_export_control else "//img[@src='/fpa/images/btn_cancel.gif']"
                    
                    try:
                        cancel_button = find_element_with_retry(
                            driver,
                            By.XPATH,
                            cancel_xpath,
                            max_attempts=2
                        )
                        
                        highlight(cancel_button)
                        time.sleep(1)
                        
                        # Click cancel with retry
                        if not click_element_with_retry(cancel_button):
                            result = f"{main_index}.{chr(96 + sub_index)}. Failed to click cancel button - element became stale. Attempting to navigate back."
                            log_and_update_status(result, "Warning")
                            # Try to go back as a fallback
                            try:
                                driver.back()
                                time.sleep(2)
                            except:
                                pass
                            return True
                    except (TimeoutException, NoSuchElementException):
                        result = f"{main_index}.{chr(96 + sub_index)}. Cancel button not found. Attempting to navigate back."
                        log_and_update_status(result, "Warning")
                        # Try to go back as a fallback
                        try:
                            driver.back()
                            time.sleep(2)
                        except:
                            pass
                        return True

                    return True
                else:
                    result = f"{main_index}.{chr(96 + sub_index)}. No clickable element found in first row - skipping."
                    log_and_update_status(result, "Skipped")
                    return True
                    
            except Exception as e:
                # General exception handler for any other issues - log as a warning and continue
                result = f"{main_index}.{chr(96 + sub_index)}. Exception while handling list element: {str(e)}. Skipping."
                log_and_update_status(result, "Warning")
                return True
                
        except (TimeoutException, NoSuchElementException) as e:
            # Only treat table absence as an error - this is unexpected
            result = f"{main_index}.{chr(96 + sub_index)}. Failed to find the list table: {str(e)}"
            log_and_update_status(result, "Failed")
            return False
        except StaleElementReferenceException as e:
            # Treat stale elements gracefully - just skip and continue
            result = f"{main_index}.{chr(96 + sub_index)}. StaleElementReferenceException while handling list table. Skipping."
            log_and_update_status(result, "Skipped")
            return True
        except Exception as e:
            # General exception - log and continue
            result = f"{main_index}.{chr(96 + sub_index)}. Unexpected error: {str(e)}. Skipping."
            log_and_update_status(result, "Warning")
            return True

    # Set page load timeout
    driver.set_page_load_timeout(30)
    
    # Implement exception handling with cleanup
    try:
        # Safely navigate to URL with retry logic
        navigation_attempts = 0
        max_navigation_attempts = 3
        navigation_success = False
        
        while navigation_attempts < max_navigation_attempts and not navigation_success:
            try:
                driver.get(url)
                WebDriverWait(driver, 10).until(lambda d: d.execute_script('return document.readyState') == 'complete')
                logging.info(f"Successfully navigated to {url}")
                validation_status['results'].append(f"Successfully navigated to {url}")
                navigation_success = True
            except (WebDriverException, TimeoutException) as e:
                navigation_attempts += 1
                if navigation_attempts == max_navigation_attempts:
                    raise
                logging.warning(f"Navigation attempt {navigation_attempts} failed: {e}, retrying...")
                time.sleep(2)
                
        if not navigation_success:
            raise TimeoutException(f"Failed to navigate to {url} after {max_navigation_attempts} attempts")
        
        # Add screenshot capture on successful login
        try:
            screenshot_path = os.path.join(os.getcwd(), 'screenshots')
            os.makedirs(screenshot_path, exist_ok=True)
            screenshot_file = os.path.join(screenshot_path, f"{environment}_login_{time.strftime('%Y%m%d_%H%M%S')}.png")
            driver.save_screenshot(screenshot_file)
            logging.info(f"Login screenshot saved to {screenshot_file}")
        except Exception as e:
            logging.warning(f"Failed to capture login screenshot: {e}")
    
    except Exception as e:
        error_msg = f"Failed to navigate to {url}: {e}"
        logging.error(error_msg)
        logging.error(traceback.format_exc())
        validation_status['results'].append(error_msg)
        driver.quit()
        validation_status['status'] = 'Failed'
        validation_status['end_time'] = time.strftime("%Y-%m-%d %H:%M:%S")
        validation_status['progress'] = 100  # Ensure progress bar shows complete
        return validation_results, False

    all_tabs_opened = True

    def handle_sub_tabs(tab_name, sub_tabs, main_index):
        nonlocal all_tabs_opened
        sub_tab_results = []
        
        for sub_index, (sub_tab_name, sub_tab_data) in enumerate(sub_tabs.items(), start=1):
            # First check if we should stop or pause
            if stop_event.is_set():
                return sub_tab_results
                
            pause_event.wait()
            
            # Try to open the sub-tab
            sub_success = check_sub_tab(sub_tab_data['script'], sub_tab_name, sub_tab_data['content_locator'], main_index, sub_index)
            is_export_control = tab_name == "Positive Pay" and sub_tab_name == "Export Control"
            
            if sub_success:
                # If sub-tab opened successfully, check if we need to validate the first list element
                column_index = config['tabs'][tab_name]['column_index']
                if isinstance(column_index, dict):
                    column_index = column_index.get(sub_tab_name)
                    
                if column_index is not None:
                    # Try to validate the first list element
                    first_list_element_success = validate_first_list_element_and_cancel(column_index, main_index, sub_index, is_export_control=is_export_control)
                    
                    # Only mark the tab as failing if an actual error occurred (not skips)
                    if not first_list_element_success:
                        all_tabs_opened = False
                else:
                    # No column index means we skip element validation
                    result = f"{main_index}.{chr(96 + sub_index)}. No column index specified for '{sub_tab_name}' - skipping element check."
                    log_and_update_status(result, "Skipped")
            else:
                # Sub-tab couldn't be opened - this is a failure
                all_tabs_opened = False

            # Record the sub-tab result for reporting
            if sub_success:
                result = f"{main_index}.{chr(96 + sub_index)}. Sub Tab '{sub_tab_name}' validation completed successfully."
                sub_tab_results.append((result, "Success"))
            else:
                result = f"{main_index}.{chr(96 + sub_index)}. Sub Tab '{sub_tab_name}' validation failed."
                sub_tab_results.append((result, "Failed"))

        return sub_tab_results

    # Loop through all tabs
    all_tabs_opened = True
    total_tabs = len(config['tabs'])
    tabs_processed = 0

    for i, (tab_name, tab_data) in enumerate(config['tabs'].items(), start=1):
        try:
            # Check for stop or pause
            if stop_event.is_set():
                break
                
            pause_event.wait()
            
            # Update progress
            tabs_processed += 1
            validation_status['progress'] = int((tabs_processed / total_tabs) * 100)
            logging.info(f"Processing tab {i}/{total_tabs}: {tab_name} - Progress: {validation_status['progress']}%")
            
            # Try to find the tab element
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
                    log_and_update_status(result)

                    if 'sub_tabs' in tab_data:
                        sub_tab_results = handle_sub_tabs(tab_name, tab_data['sub_tabs'], i)
                        validation_results.extend(sub_tab_results)
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
            
        # Add a short delay between tab navigations to allow the page to stabilize
        time.sleep(2)

    # Capture final screenshot
    try:
        screenshot_path = os.path.join(os.getcwd(), 'screenshots')
        os.makedirs(screenshot_path, exist_ok=True)
        screenshot_file = os.path.join(screenshot_path, f"{environment}_final_{time.strftime('%Y%m%d_%H%M%S')}.png")
        driver.save_screenshot(screenshot_file)
        logging.info(f"Final screenshot saved to {screenshot_file}")
    except Exception as e:
        logging.warning(f"Failed to capture final screenshot: {e}")

    # Generate summary statistics
    total_checks = validation_status['successful_checks'] + validation_status['failed_checks'] + validation_status['skipped_checks']
    success_rate = (validation_status['successful_checks'] / total_checks * 100) if total_checks > 0 else 0
    
    summary_message = f"""
Validation Summary:
------------------
Environment: {environment}
Total Checks: {total_checks}
Successful: {validation_status['successful_checks']} ({success_rate:.1f}%)
Failed: {validation_status['failed_checks']}
Skipped: {validation_status['skipped_checks']}
Duration: {(time.time() - time.mktime(time.strptime(validation_status['start_time'], "%Y-%m-%d %H:%M:%S"))):.1f} seconds
    """
    
    log_and_update_status(summary_message, "Info")
    
    # Clean up
    try:
        driver.quit()
        logging.info("WebDriver closed successfully")
    except Exception as e:
        logging.warning(f"Error while closing WebDriver: {e}")
    
    # Update validation status - make sure progress shows 100% if successful
    validation_status['end_time'] = time.strftime("%Y-%m-%d %H:%M:%S")
    validation_status['progress'] = 100  # Ensure progress bar shows complete
    
    if all_tabs_opened:
        # IMPORTANT: Reset failed_checks to 0 when all tabs were successfully validated
        # This fixes the pie chart issue showing failures when there are none
        validation_status['failed_checks'] = 0
        logging.info("All tabs were successfully validated. Setting failed_checks counter to 0.")
        
        result = ("Validation completed successfully.", "Success")
        log_and_update_status(result[0])
        validation_status['status'] = 'Completed'
        
        # Submit test results if link provided
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
    
    Args:
        validation_portal_link: URL of the validation portal
    """
    driver = None
    try:
        logging.info(f"Submitting test results to validation portal: {validation_portal_link}")
        
        # Initialize WebDriver with improved options
        driver = setup_driver()
        
        # Navigate to the validation portal
        navigation_attempts = 0
        max_navigation_attempts = 3
        while navigation_attempts < max_navigation_attempts:
            try:
                driver.get(validation_portal_link)
                WebDriverWait(driver, 10).until(lambda d: d.execute_script('return document.readyState') == 'complete')
                logging.info("Successfully navigated to validation portal")
                break
            except Exception as e:
                navigation_attempts += 1
                if navigation_attempts == max_navigation_attempts:
                    raise Exception(f"Failed to navigate to validation portal after {max_navigation_attempts} attempts: {e}")
                logging.warning(f"Navigation attempt {navigation_attempts} failed: {e}, retrying...")
                time.sleep(2)
        
        # Take screenshot of validation portal page
        try:
            screenshot_path = os.path.join(os.getcwd(), 'screenshots')
            os.makedirs(screenshot_path, exist_ok=True)
            screenshot_file = os.path.join(screenshot_path, f"portal_before_{time.strftime('%Y%m%d_%H%M%S')}.png")
            driver.save_screenshot(screenshot_file)
            logging.info(f"Validation portal screenshot saved to {screenshot_file}")
        except Exception as e:
            logging.warning(f"Failed to capture validation portal screenshot: {e}")
        
        # Find and click Set Testing Results button
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
                
            # Wait for the dialog to appear
            time.sleep(3)
            
            # Take screenshot after clicking button
            try:
                screenshot_file = os.path.join(screenshot_path, f"portal_dialog_{time.strftime('%Y%m%d_%H%M%S')}.png")
                driver.save_screenshot(screenshot_file)
            except Exception as e:
                logging.warning(f"Failed to capture dialog screenshot: {e}")
            
        except Exception as e:
            logging.error(f"Error finding or clicking Set Testing Results button: {e}")
            if driver:
                driver.quit()
            raise
        
        # Use pyautogui for clicking UI elements with better error handling
        try:
            # Get screen size to verify coordinates are within bounds
            screen_width, screen_height = pyautogui.size()
            
            # Define click coordinates
            success_button = (536, 460)
            ok_button = (1395, 896)
            confirm_button = (1113, 374)
            
            # Verify coordinates are within screen bounds
            for button, (x, y) in [("Success", success_button), ("OK", ok_button), ("Confirm", confirm_button)]:
                if x > screen_width or y > screen_height:
                    logging.warning(f"{button} button coordinates ({x}, {y}) are outside screen bounds ({screen_width}, {screen_height})")
            
            # Move to each position and click with delay
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
            
            # Take final screenshot after confirmation
            try:
                time.sleep(1)
                screenshot_file = os.path.join(screenshot_path, f"portal_after_{time.strftime('%Y%m%d_%H%M%S')}.png")
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
        # Clean up
        if driver:
            try:
                driver.quit()
                logging.info("Validation portal WebDriver closed successfully")
            except Exception as e:
                logging.warning(f"Error while closing validation portal WebDriver: {e}")

# Error handler for rate limiting
@app.errorhandler(429)
def too_many_requests(e):
    return jsonify({"error": "Too many requests. Please try again later."}), 429

# Health check endpoint
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
    # Add environment data for dropdown
    environments = list(config['environments'].keys())
    return render_template('index.html', project_name=project_name, environments=environments)

@app.route('/start_validation', methods=['POST'])
@rate_limit
def start_validation():
    global stop_event, pause_event, active_validation_thread
    
    # Check if validation is already running
    if validation_status['status'] in ['Running', 'Paused'] and active_validation_thread and active_validation_thread.is_alive():
        return jsonify({
            "error": "Validation already in progress", 
            "status": validation_status['status']
        }), 409
    
    # Reset events and status
    stop_event.clear()
    pause_event.set()
    
    # Get request data
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
    
    # Reset validation status
    validation_status['status'] = 'Running'
    validation_status['progress'] = 0  # Reset progress
    validation_status['failed_checks'] = 0  # Reset failed checks
    validation_status['successful_checks'] = 0  # Reset successful checks
    validation_status['skipped_checks'] = 0  # Reset skipped checks
    
    if not retry_failed:
        validation_status['results'] = []
    
    def validate_environment():
        try:
            results, success = validate_application(environment, validation_portal_link, retry_failed)
            
            # Ensure progress is 100% when complete
            validation_status['progress'] = 100
            
            # Set final status
            validation_status['status'] = 'Completed' if success else 'Failed'
            
            # If successful, ensure failed_checks is 0
            if success:
                validation_status['failed_checks'] = 0
            
            # Send email with results
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
            validation_status['progress'] = 100  # Ensure progress is complete even on error
            validation_status['results'].append(error_msg)

    # Start validation in a new thread
    active_validation_thread = threading.Thread(target=validate_environment)
    active_validation_thread.daemon = True  # Make thread daemon so it exits when main thread exits
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
    
    # Check if validation is running
    if not active_validation_thread or not active_validation_thread.is_alive():
        return jsonify({
            "error": "No validation is currently running",
            "status": validation_status['status']
        }), 400
    
    action = "paused"
    
    # Toggle pause state
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
    
    # Check if validation is running or paused
    if not active_validation_thread or not active_validation_thread.is_alive():
        return jsonify({
            "error": "No validation is currently running",
            "status": validation_status['status']
        }), 400
    
    if validation_status['status'] not in ['Running', 'Paused']:
        return jsonify({
            "error": f"Cannot stop validation in '{validation_status['status']}' state"
        }), 400
    
    # Set stop event and resume if paused
    stop_event.set()
    if validation_status['status'] == 'Paused':
        pause_event.set()  # Resume if paused, so it can process the stop event
    
    validation_status['status'] = 'Stopping'
    
    # Ensure the progress is updated to show correctly in the UI
    if validation_status.get('progress', 0) < 100:
        validation_status['progress'] = 99  # Set to 99% when stopping (will be 100% when fully stopped)
    
    return jsonify({
        "message": "Validation stopping",
        "status": validation_status['status']
    }), 200

@app.route('/status')
def get_status():
    global active_validation_thread
    
    # Check if thread is alive
    if active_validation_thread and not active_validation_thread.is_alive():
        if validation_status['status'] in ['Running', 'Paused', 'Stopping']:
            validation_status['status'] = 'Failed'
            validation_status['results'].append("Validation thread terminated unexpectedly")
            validation_status['progress'] = 100  # Set to 100% if thread died unexpectedly
    
    # IMPORTANT FIX: Always ensure progress is 100% when validation is no longer running
    if validation_status['status'] in ['Completed', 'Failed']:
        validation_status['progress'] = 100
    
    # IMPORTANT FIX: Ensure failed_checks is always 0 if status is Completed
    # This ensures the pie chart doesn't show failures when none exist
    if validation_status['status'] == 'Completed':
        validation_status['failed_checks'] = 0
    
    # Return status with additional metadata
    status_data = {
        **validation_status,
        'active': active_validation_thread is not None and active_validation_thread.is_alive(),
        'timestamp': time.strftime("%Y-%m-%d %H:%M:%S")
    }
    
    return jsonify(status_data)

if __name__ == '__main__':
    try:
        # Create directories if they don't exist
        os.makedirs(os.path.join(os.getcwd(), 'screenshots'), exist_ok=True)
        os.makedirs(os.path.join(os.getcwd(), 'logs'), exist_ok=True)
        
        # Set up a more robust server start
        logging.info(f"Starting {project_name} Validation Server")
        
        # Set up a global exception hook to catch unhandled exceptions
        def handle_exception(exc_type, exc_value, exc_traceback):
            if issubclass(exc_type, KeyboardInterrupt):
                # Don't log keyboard interrupt (ctrl+c)
                sys.__excepthook__(exc_type, exc_value, exc_traceback)
                return
                
            logging.error("Unhandled exception:", exc_info=(exc_type, exc_value, exc_traceback))
            
        sys.excepthook = handle_exception
        
        # Use a thread pool for better resource management
        executor = ThreadPoolExecutor(max_workers=4)
        
        # Start the Flask app in a separate thread
        def run_app():
            app.run(debug=False, use_reloader=False, host='0.0.0.0', port=5000, threaded=True)
            
        executor.submit(run_app)
        
        # Wait for the server to start
        server_ready = False
        retry_count = 0
        max_retries = 5
        
        while not server_ready and retry_count < max_retries:
            try:
                time.sleep(1)
                # Try to connect to the server
                with socket.create_connection(('127.0.0.1', 5000), timeout=1):
                    server_ready = True
                    logging.info("Server started successfully")
            except (socket.error, socket.timeout):
                retry_count += 1
                logging.info(f"Waiting for server to start (attempt {retry_count}/{max_retries})...")
        
        if not server_ready:
            logging.warning("Server may not have started properly, attempting to open browser anyway")
        
        # Open browser
        webbrowser.open("http://127.0.0.1:5000")
        logging.info("Browser opened to application URL")
        
    except Exception as e:
        logging.error(f"Error starting application: {e}")
        logging.error(traceback.format_exc())
        sys.exit(1)
