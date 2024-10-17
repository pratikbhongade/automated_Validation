import os
import json
import time
import logging
from flask import Flask, render_template, request, jsonify
import threading
import pythoncom
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, JavascriptException
from email_sender import send_email
import pyautogui

app = Flask(__name__)

# Load JSON configuration
config_path = os.path.join(os.getcwd(), 'validation_config.json')
with open(config_path) as config_file:
    config = json.load(config_file)

project_name = config['project_name']

# Set up logging
log_file_path = os.path.join(os.getcwd(), 'validation.log')
logging.basicConfig(filename=log_file_path, level=logging.INFO, format='%(asctime)s:%(levelname)s:%(message)s')

validation_status = {'status': 'Not Started', 'results': [], 'paused': False, 'stopped': False}

pause_event = threading.Event()
pause_event.set()

stop_event = threading.Event()
stop_event.clear()


def validate_application(environment, validation_portal_link=None):
    global validation_status
    # Set the URL based on environment
    url = config['environments'].get(environment.upper())
    if not url:
        raise ValueError("Invalid environment selected. Please choose 'IT', 'QV', or 'Prod'.")

    logging.info(f"Selected environment: {environment}")
    validation_status['results'].append(f"Selected environment: {environment}")

    # Initialize Edge WebDriver
    driver = webdriver.Edge()

    validation_results = []

    def log_and_update_status(message, status="Success"):
        print(message)
        logging.info(message)
        validation_results.append((message, status))
        validation_status['results'].append(message)

    # Function to highlight an element
    def highlight(element):
        driver.execute_script("arguments[0].setAttribute('style', arguments[1]);", element, "background: yellow; border: 2px solid red;")

    # Function to check if a tab opens properly
    def check_tab(tab_element, tab_name, content_locator, index):
        pause_event.wait()
        if stop_event.is_set():
            return False

        try:
            highlight(tab_element)
            time.sleep(1)
            tab_element.click()
            locator_type = content_locator['type']
            locator_value = content_locator['value']
            if locator_type == 'css':
                WebDriverWait(driver, 3).until(EC.visibility_of_element_located((By.CSS_SELECTOR, locator_value)))
            elif locator_type == 'id':
                WebDriverWait(driver, 3).until(EC.visibility_of_element_located((By.ID, locator_value)))
            result = f"{index}. Main Tab '{tab_name}' opened successfully."
            log_and_update_status(result)
            return True
        except TimeoutException:
            result = f"{index}. Failed to open Main Tab '{tab_name}'."
            log_and_update_status(result, "Failed")
            return False

    # Function to check if a sub-tab opens properly by executing JavaScript
    def check_sub_tab(sub_tab_js, sub_tab_name, content_locator, main_index, sub_index):
        pause_event.wait()
        if stop_event.is_set():
            return False

        try:
            time.sleep(1)
            driver.execute_script(sub_tab_js)
            locator_type = content_locator['type']
            locator_value = content_locator['value']
            if locator_type == 'css':
                WebDriverWait(driver, 3).until(EC.visibility_of_element_located((By.CSS_SELECTOR, locator_value)))
            elif locator_type == 'id':
                WebDriverWait(driver, 3).until(EC.visibility_of_element_located((By.ID, locator_value)))
            result = f"{main_index}.{chr(96 + sub_index)}. Sub Tab '{sub_tab_name}' opened successfully."
            log_and_update_status(result)
            return True
        except TimeoutException:
            result = f"{main_index}.{chr(96 + sub_index)}. Failed to open Sub Tab '{sub_tab_name}'."
            log_and_update_status(result, "Failed")
            return False
        except JavascriptException as e:
            result = f"{main_index}.{chr(96 + sub_index)}. JavaScript error on Sub Tab '{sub_tab_name}': {e}"
            log_and_update_status(result, "Failed")
            return False

    # Function to validate the first list element under the specified column and click the cancel button
    def validate_first_list_element_and_cancel(column_index, main_index, sub_index, is_export_control=False):
        pause_event.wait()
        if stop_event.is_set():
            return False

        try:
            WebDriverWait(driver, 3).until(EC.visibility_of_element_located((By.CSS_SELECTOR, "table.ListView")))
            rows = driver.find_elements(By.XPATH, f"//table[@class='ListView']/tbody/tr")
            if len(rows) <= 1:
                result = f"{main_index}.{chr(96 + sub_index)}. There is no data in the sub tab '{sub_index}' to check so skipping."
                log_and_update_status(result, "Skipped")
                return True

            try:
                first_element = driver.find_element(By.XPATH, f"//table[@class='ListView']/tbody/tr[2]/td[{column_index}]/a")
                highlight(first_element)
                time.sleep(1)
                first_element.click()
                WebDriverWait(driver, 3).until(EC.visibility_of_element_located((By.CSS_SELECTOR, "div#content")))

                time.sleep(1)

                if is_export_control:
                    cancel_button = WebDriverWait(driver, 3).until(
                        EC.element_to_be_clickable((By.XPATH, "//img[@src='/fpa/images/btn_cancel.jpg']"))
                    )
                else:
                    cancel_button = WebDriverWait(driver, 3).until(
                        EC.element_to_be_clickable((By.XPATH, "//img[@src='/fpa/images/btn_cancel.gif']"))
                    )
                highlight(cancel_button)
                time.sleep(1)
                cancel_button.click()

                return True
            except NoSuchElementException:
                result = f"{main_index}.{chr(96 + sub_index)}. There is no first element in the sub tab '{sub_index}' to click so skipping."
                log_and_update_status(result, "Skipped")
                return True
        except (TimeoutException, NoSuchElementException) as e:
            result = f"{main_index}.{chr(96 + sub_index)}. Failed to open the first list element. Exception: {e}"
            log_and_update_status(result, "Failed")
            return False

    driver.get(url)
    logging.info(f"Navigated to {url}")
    validation_status['results'].append(f"Navigated to {url}")

    all_tabs_opened = True

    def handle_sub_tabs(tab_name, sub_tabs, main_index):
        global all_tabs_opened
        sub_tab_results = []
        for sub_index, (sub_tab_name, sub_tab_data) in enumerate(sub_tabs.items(), start=1):
            sub_success = check_sub_tab(sub_tab_data['script'], sub_tab_name, sub_tab_data['content_locator'], main_index, sub_index)
            is_export_control = tab_name == "Positive Pay" and sub_tab_name == "Export Control"
            if sub_success:
                column_index = config['tabs'][tab_name]['column_index']
                if isinstance(column_index, dict):
                    column_index = column_index.get(sub_tab_name)
                if column_index is not None:
                    first_list_element_success = validate_first_list_element_and_cancel(column_index, main_index, sub_index, is_export_control=is_export_control)
                    if not first_list_element_success:
                        all_tabs_opened = False
                else:
                    result = f"{main_index}.{chr(96 + sub_index)}. There is no data in the sub tab '{sub_tab_name}' to check so skipping."
                    log_and_update_status(result, "Skipped")
            else:
                all_tabs_opened = False

            if sub_success:
                result = f"{main_index}.{chr(96 + sub_index)}. Sub Tab '{sub_tab_name}' opened successfully."
                sub_tab_results.append((result, "Success"))
            else:
                result = f"{main_index}.{chr(96 + sub_index)}. Failed to open Sub Tab '{sub_tab_name}'."
                sub_tab_results.append((result, "Failed"))

        return sub_tab_results

    for i, (tab_name, tab_data) in enumerate(config['tabs'].items(), start=1):
        try:
            tab_element = WebDriverWait(driver, 3).until(
                EC.element_to_be_clickable((By.XPATH, f"//a[@href='{tab_data['url']}']"))
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

    time.sleep(1)
    driver.quit()

    if all_tabs_opened:
        result = ("Validation completed successfully.", "Success")
        log_and_update_status(result[0])

        # If a validation portal link is provided, navigate and submit results
        if validation_portal_link:
            submit_test_results(validation_portal_link)
    else:
        result = ("Validation failed.", "Failed")
        log_and_update_status(result[0], "Failed")

    return validation_results, all_tabs_opened


def submit_test_results(validation_portal_link):
    try:
        driver = webdriver.Edge()
        driver.get(validation_portal_link)

        # Locate the "Set Testing Results" button and click it
        set_results_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//button[contains(text(),'Set Testing Results')]"))
        )
        set_results_button.click()
        time.sleep(5)  # Wait for the new page to load

        # Use pyautogui for clicking success radio button and OK buttons
        pyautogui.click(536, 460)  # Click Success
        time.sleep(1)
        pyautogui.click(1395, 896)  # Click OK
        time.sleep(1)
        pyautogui.click(1113, 374)  # Confirm OK
        logging.info("Test results successfully submitted via Validation Portal.")

    except Exception as e:
        logging.error(f"Error submitting results to validation portal: {e}")
    finally:
        driver.quit()


@app.route('/')
def home():
    return render_template('index.html', project_name=project_name)


@app.route('/start_validation', methods=['POST'])
def start_validation():
    global stop_event, pause_event
    stop_event.clear()
    pause_event.set()
    data = request.json
    environment = data.get('environment')
    validation_portal_link = data.get('validation_portal_link', None)
    validation_status['status'] = 'Running'
    validation_status['results'] = []

    def validate_environment():
        results, success = validate_application(environment, validation_portal_link)
        validation_status['status'] = 'Completed' if success else 'Failed'
        validation_status['results'] = results
        subject = f"{project_name} {environment.upper()} Environment Validation Results"
        send_email(subject, results, success, log_file_path)

    thread = threading.Thread(target=validate_environment)
    thread.start()
    return jsonify({"message": "Validation started"}), 202


@app.route('/pause_resume_validation', methods=['POST'])
def pause_resume_validation():
    global pause_event, validation_status
    if validation_status['status'] == 'Running' and not validation_status.get('paused', False):
        validation_status['paused'] = True
        pause_event.clear()
        validation_status['status'] = 'Paused'
    elif validation_status['status'] == 'Paused':
        validation_status['paused'] = False
        pause_event.set()
        validation_status['status'] = 'Running'
    return jsonify({"message": "Validation paused/resumed"}), 200


@app.route('/stop_validation', methods=['POST'])
def stop_validation():
    global stop_event, validation_status
    stop_event.set()
    validation_status['status'] = 'Stopped'
    return jsonify({"message": "Validation stopped"}), 200


@app.route('/status')
def status():
    return jsonify(validation_status)


if __name__ == '__main__':
    app.run(debug=True)
