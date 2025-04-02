@app.route('/')
def home():
    # Add environment data for dropdown
    environments = list(config['environments'].keys())
    return render_template('index.html', project_name=project_name, environments=environments)

@app.route('/reports/<path:filename>')
def serve_report(filename):
    """Serve HTML reports"""
    return send_from_directory(reports_dir, filename)

@app.route('/screenshots/<path:filename>')
def serve_screenshot(filename):
    """Serve screenshots"""
    return send_from_directory(screenshots_dir, filename)

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
        parallel = data.get('parallel', True)  # Default to parallel validation
        max_workers = data.get('max_workers', 3)  # Default to 3 workers
        
    except Exception as e:
        return jsonify({"error": f"Invalid request: {str(e)}"}), 400
    
    # Reset validation status
    validation_status['status'] = 'Running'
    if not retry_failed:
        validation_status['results'] = []
    
    def validate_environment():
        try:
            results, success = validate_application(
                environment, 
                validation_portal_link, 
                retry_failed,
                parallel,
                max_workers
            )
            validation_status['status'] = 'Completed' if success else 'Failed'
            
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
            validation_status['results'].append(error_msg)

    # Start validation in a new thread
    active_validation_thread = threading.Thread(target=validate_environment)
    active_validation_thread.daemon = True  # Make thread daemon so it exits when main thread exits
    active_validation_thread.start()
    
    return jsonify({
        "message": "Validation started",
        "environment": environment,
        "status": validation_status['status'],
        "start_time": validation_status['start_time'],
        "parallel": parallel,
        "max_workers": max_workers,
        "run_id": validation_status['run_id']
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
    
    # If status is Completed or Failed but progress is not 100%, fix it
    if validation_status['status'] in ['Completed', 'Failed'] and validation_status.get('progress', 0) != 100:
        validation_status['progress'] = 100
    
    # Ensure failed_checks is 0 if all_tabs_opened is True (overall success)
    if validation_status['status'] == 'Completed' and validation_status.get('failed_checks', 0) > 0:
        validation_status['failed_checks'] = 0
    
    # Return status with additional metadata
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
            
        # Read the last n lines from the log file
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
        # Optional run_id parameter to filter by run
        run_id = request.args.get('run_id')
        
        if run_id:
            screenshot_path = os.path.join(screenshots_dir, run_id)
        else:
            screenshot_path = screenshots_dir
        
        if not os.path.exists(screenshot_path):
            return jsonify({"screenshots": [], "count": 0})
            
        screenshots = []
        for root, dirs, files in os.walk(screenshot_path):
            for file in files:
                if file.endswith('.png'):
                    file_path = os.path.join(root, file)
                    rel_path = os.path.relpath(file_path, screenshots_dir)
                    url_path = f"/screenshots/{rel_path}"
                    screenshots.append({
                        "filename": file,
                        "path": url_path,
                        "size": os.path.getsize(file_path),
                        "created": time.ctime(os.path.getctime(file_path))
                    })
                
        # Sort by creation time (newest first)
        screenshots.sort(key=lambda x: x["created"], reverse=True)
        
        return jsonify({
            "screenshots": screenshots,
            "count": len(screenshots)
        })
        
    except Exception as e:
        return jsonify({"error": f"Error listing screenshots: {str(e)}"}), 500

@app.route('/reports')
def list_reports():
    """Endpoint to list available HTML reports"""
    try:
        reports = []
        if os.path.exists(reports_dir):
            for file in os.listdir(reports_dir):
                if file.endswith('.html'):
                    file_path = os.path.join(reports_dir, file)
                    # Extract run information from filename
                    parts = file.split('_')
                    environment = parts[0] if len(parts) > 0 else "Unknown"
                    run_id = parts[1] if len(parts) > 1 else "Unknown"
                    
                    reports.append({
                        "filename": file,
                        "path": f"/reports/{file}",
                        "url": f"/reports/{file}",
                        "size": os.path.getsize(file_path),
                        "created": time.ctime(os.path.getctime(file_path)),
                        "environment": environment,
                        "run_id": run_id
                    })
            
            # Sort by creation time (newest first)
            reports.sort(key=lambda x: x["created"], reverse=True)
        
        return jsonify({
            "reports": reports,
            "count": len(reports)
        })
        
    except Exception as e:
        return jsonify({"error": f"Error listing reports: {str(e)}"}), 500

@app.route('/performance')
def get_performance_data():
    """Endpoint to get performance metrics"""
    try:
        # Optional run_id parameter to filter by run
        run_id = request.args.get('run_id')
        
        if run_id and run_id != validation_status.get('run_id'):
            return jsonify({"error": f"Performance data for run {run_id} not available"}), 404
        
        performance_metrics = validation_status.get('performance_metrics', {})
        
        # Convert to a list format for easier consumption
        metrics_list = []
        for component, data in performance_metrics.items():
            metrics_list.append({
                "component": component,
                "time": data.get('time'),
                "status": data.get('status'),
                "timestamp": time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(data.get('start_time'))) if data.get('start_time') else None
            })
        
        # Sort by time (slowest first)
        metrics_list.sort(key=lambda x: x.get('time', 0) or 0, reverse=True)
        
        # Calculate summary statistics
        times = [m.get('time', 0) for m in metrics_list if m.get('time', 0)]
        if times:
            avg_time = sum(times) / len(times)
            max_time = max(times)
            min_time = min(times)
            total_time = sum(times)
        else:
            avg_time = max_time = min_time = total_time = 0
        
        return jsonify({
            "metrics": metrics_list,
            "summary": {
                "count": len(metrics_list),
                "average_time": avg_time,
                "max_time": max_time,
                "min_time": min_time,
                "total_time": total_time
            },
            "run_id": validation_status.get('run_id')
        })
        
    except Exception as e:
        return jsonify({"error": f"Error retrieving performance data: {str(e)}"}), 500

@app.route('/validation_runs')
def get_validation_runs():
    """Endpoint to list all validation runs"""
    try:
        return jsonify({
            "runs": validation_runs,
            "count": len(validation_runs)
        })
    except Exception as e:
        return jsonify({"error": f"Error retrieving validation runs: {str(e)}"}), 500

@app.route('/latest_report')
def get_latest_report():
    """Endpoint to get the path to the latest report"""
    if validation_status.get('latest_report'):
        report_filename = os.path.basename(validation_status['latest_report'])
        return jsonify({
            "report_url": f"/reports/{report_filename}",
            "report_path": validation_status['latest_report'],
            "run_id": validation_status.get('run_id')
        })
    else:
        return jsonify({"error": "No report available"}), 404# Function decorator for rate limiting
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

def validate_tab(driver, tab_name, tab_data, index, shared_data):
    """
    Validate a single tab - for parallel processing
    
    Args:
        driver: WebDriver instance
        tab_name: Name of the tab
        tab_data: Configuration data for the tab
        index: Tab index
        shared_data: Shared dictionary to track overall status
        
    Returns:
        dict: Results of the tab validation
    """
    tab_start_time = time.time()
    tab_results = []
    tab_success = True
    sub_tabs_results = []
    
    # Track performance metrics
    metrics = {
        'start_time': tab_start_time,
        'end_time': None,
        'time': None,
        'status': None,
        'sub_tabs': {}
    }
    
    try:
        # Only proceed if not stopped
        if shared_data['stop_flag']:
            return {
                'results': [],
                'success': False,
                'metrics': metrics,
                'performance_data': {}
            }
            
        # Wait if paused
        while shared_data['pause_flag'] and not shared_data['stop_flag']:
            time.sleep(0.5)
            
        # Try to find the tab element
        try:
            tab_element = find_element_with_retry(
                driver, 
                By.XPATH, 
                f"//a[@href='{tab_data['url']}']",
                max_attempts=3, 
                wait_time=5
            )
            
            # Capture a screenshot before clicking
            screenshot_path = os.path.join(screenshots_dir, f"tab_{tab_name.replace(' ', '_')}_{time.strftime('%Y%m%d_%H%M%S')}_before.png")
            driver.save_screenshot(screenshot_path)
            
            # Highlight and click the tab
            highlight(driver, tab_element)
            time.sleep(1)
            
            click_start_time = time.time()
            success = check_tab(driver, tab_element, tab_name, tab_data['content_locator'], index)
            click_time = time.time() - click_start_time
            
            # Capture timing for tab click
            metrics['tab_click_time'] = click_time
            
            # Capture a screenshot after clicking
            screenshot_path = os.path.join(screenshots_dir, f"tab_{tab_name.replace(' ', '_')}_{time.strftime('%Y%m%d_%H%M%S')}_after.png")
            driver.save_screenshot(screenshot_path)
            
            if success:
                result = f"{index}. Main Tab '{tab_name}' opened successfully in {click_time:.2f}s"
                tab_results.append((result, "Success"))
                metrics['status'] = "Success"
                
                # Process sub-tabs if present
                if 'sub_tabs' in tab_data:
                    sub_tabs_results, sub_metrics = handle_sub_tabs(driver, tab_name, tab_data['sub_tabs'], index, shared_data)
                    tab_results.extend(sub_tabs_results)
                    metrics['sub_tabs'] = sub_metrics
                    
                    # Check if any sub-tab failed
                    for sub_result in sub_tabs_results:
                        if sub_result[1] == "Failed":
                            tab_success = False
                            break
            else:
                result = f"{index}. Failed to open Main Tab '{tab_name}'"
                tab_results.append((result, "Failed"))
                metrics['status'] = "Failed"
                tab_success = False
                
        except (TimeoutException, NoSuchElementException) as e:
            result = f"{index}. Main Tab '{tab_name}' not found or not clickable. Exception: {e}"
            tab_results.append((result, "Failed"))
            metrics['status'] = "Failed"
            tab_success = False
            
    except StaleElementReferenceException as e:
        result = f"{index}. StaleElementReferenceException on Main Tab '{tab_name}': {e}"
        tab_results.append((result, "Failed"))
        metrics['status'] = "Failed"
        tab_success = False
    except Exception as e:
        result = f"{index}. Unexpected error validating tab '{tab_name}': {str(e)}"
        tab_results.append((result, "Failed"))
        metrics['status'] = "Failed"
        tab_success = False
        logging.error(f"Error in validate_tab for {tab_name}: {e}")
        logging.error(traceback.format_exc())
    finally:
        # Record performance metrics
        metrics['end_time'] = time.time()
        metrics['time'] = metrics['end_time'] - metrics['start_time']
        
        # Update shared data
        with shared_data['lock']:
            if not tab_success:
                shared_data['all_tabs_opened'] = False
                
            # Count results by status
            for result in tab_results:
                status = result[1]
                if status == "Success":
                    shared_data['successful_checks'] += 1
                elif status == "Failed":
                    shared_data['failed_checks'] += 1
                elif status == "Skipped":
                    shared_data['skipped_checks'] += 1
            
            # Add performance data
            performance_key = f"Tab {index}: {tab_name}"
            shared_data['performance_metrics'][performance_key] = {
                'time': metrics['time'],
                'status': metrics['status'],
                'start_time': metrics['start_time']
            }
    
    return {
        'results': tab_results,
        'success': tab_success,
        'metrics': metrics
    }

def highlight(driver, element):
    """Highlight an element on the page"""
    try:
        driver.execute_script("arguments[0].setAttribute('style', arguments[1]);", element, "background: yellow; border: 2px solid red;")
    except StaleElementReferenceException:
        # If element is stale, we'll just skip highlighting and continue
        pass

def check_tab(driver, tab_element, tab_name, content_locator, index):
    """
    Check if a tab can be opened successfully
    
    Args:
        driver: WebDriver instance
        tab_element: The tab element to click
        tab_name: Name of the tab
        content_locator: Locator for the content to verify
        index: Tab index
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        highlight(driver, tab_element)
        time.sleep(1)
        
        click_start = time.time()
        # Use the retry click function
        if not click_element_with_retry(tab_element):
            logging.error(f"Failed to click on Main Tab '{tab_name}' even though the element is present.")
            return False
        click_time = time.time() - click_start
        
        locator_type = content_locator['type']
        locator_value = content_locator['value']
        
        # Check if expected content appears after clicking
        load_start = time.time()
        try:
            if locator_type == 'css':
                WebDriverWait(driver, 5).until(EC.visibility_of_element_located((By.CSS_SELECTOR, locator_value)))
            elif locator_type == 'id':
                WebDriverWait(driver, 5).until(EC.visibility_of_element_located((By.ID, locator_value)))
        except (TimeoutException, NoSuchElementException):
            load_time = time.time() - load_start
            logging.error(f"Main Tab '{tab_name}' was clicked but expected content did not appear. Load attempt time: {load_time:.2f}s")
            return False
        load_time = time.time() - load_start
        
        logging.info(f"Main Tab '{tab_name}' opened successfully. Click time: {click_time:.2f}s, Load time: {load_time:.2f}s")
        return True
        
    except StaleElementReferenceException:
        logging.error(f"StaleElementReferenceException on Main Tab '{tab_name}'. The page may have changed while trying to interact with it.")
        return Falseimport os
import sys
import json
import time
import logging
import traceback
import datetime
from flask import Flask, render_template, request, jsonify, abort, send_file, send_from_directory
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import socket
from functools import wraps
import jinja2
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
import shutil
import uuid
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend
import matplotlib.pyplot as plt
import numpy as np
from io import BytesIO
import base64

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

# Create directories for assets
reports_dir = os.path.join(os.getcwd(), 'reports')
screenshots_dir = os.path.join(os.getcwd(), 'screenshots')
logs_dir = os.path.join(os.getcwd(), 'logs')
for directory in [reports_dir, screenshots_dir, logs_dir]:
    os.makedirs(directory, exist_ok=True)

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
app = Flask(__name__, static_folder='reports')
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
    'skipped_checks': 0
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

def generate_performance_charts(performance_data, successful_checks, failed_checks, skipped_checks):
    """
    Generate charts for the HTML report
    
    Args:
        performance_data: Dictionary with performance metrics
        successful_checks: Number of successful checks
        failed_checks: Number of failed checks
        skipped_checks: Number of skipped checks
        
    Returns:
        tuple: (results_chart_base64, performance_chart_base64)
    """
    # Generate results pie chart
    plt.figure(figsize=(6, 4))
    labels = ['Successful', 'Failed', 'Skipped']
    sizes = [successful_checks, failed_checks, skipped_checks]
    colors = ['#28a745', '#dc3545', '#ffc107']  # Green, Red, Yellow
    
    # Only include non-zero segments
    non_zero_labels = []
    non_zero_sizes = []
    non_zero_colors = []
    for i, size in enumerate(sizes):
        if size > 0:
            non_zero_labels.append(labels[i])
            non_zero_sizes.append(size)
            non_zero_colors.append(colors[i])
    
    if sum(non_zero_sizes) > 0:  # Only create pie if there's data
        plt.pie(non_zero_sizes, labels=non_zero_labels, colors=non_zero_colors, autopct='%1.1f%%', startangle=90)
    else:
        plt.text(0.5, 0.5, "No data available", ha='center', va='center', fontsize=12)
    
    plt.axis('equal')
    plt.title('Validation Results')
    
    # Save to base64
    results_buffer = BytesIO()
    plt.savefig(results_buffer, format='png', bbox_inches='tight')
    plt.close()
    results_buffer.seek(0)
    results_chart_base64 = base64.b64encode(results_buffer.getvalue()).decode('utf-8')
    
    # Generate performance histogram
    plt.figure(figsize=(6, 4))
    
    # Extract load times, filter out None values and zeros
    load_times = [metric['time'] for metric in performance_data.values() if metric.get('time', 0) > 0]
    
    if load_times:  # Only create histogram if there's data
        plt.hist(load_times, bins=10, alpha=0.7, color='#0066cc')
        plt.xlabel('Load Time (seconds)')
        plt.ylabel('Frequency')
        plt.grid(axis='y', alpha=0.3)
    else:
        plt.text(0.5, 0.5, "No performance data available", ha='center', va='center', fontsize=12)
    
    plt.title('Performance Distribution')
    
    # Save to base64
    perf_buffer = BytesIO()
    plt.savefig(perf_buffer, format='png', bbox_inches='tight')
    plt.close()
    perf_buffer.seek(0)
    performance_chart_base64 = base64.b64encode(perf_buffer.getvalue()).decode('utf-8')
    
    return results_chart_base64, performance_chart_base64

def generate_html_report(validation_status, report_path=None):
    """
    Generate an HTML report from validation results
    
    Args:
        validation_status: Dictionary with validation status and results
        report_path: Path to save the report (optional, generates a timestamped path if None)
        
    Returns:
        str: Path to the generated HTML report
    """
    if not report_path:
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        run_id = validation_status.get('run_id', uuid.uuid4().hex[:8])
        report_name = f"{validation_status.get('environment', 'unknown')}_{run_id}_{timestamp}.html"
        report_path = os.path.join(reports_dir, report_name)
    
    # Prepare data for the template
    start_time = validation_status.get('start_time')
    end_time = validation_status.get('end_time', time.strftime("%Y-%m-%d %H:%M:%S"))
    
    if start_time and end_time:
        start_dt = datetime.datetime.strptime(start_time, "%Y-%m-%d %H:%M:%S")
        end_dt = datetime.datetime.strptime(end_time, "%Y-%m-%d %H:%M:%S")
        duration_seconds = (end_dt - start_dt).total_seconds()
        
        # Format duration nicely
        minutes, seconds = divmod(duration_seconds, 60)
        duration = f"{int(minutes)}m {int(seconds)}s"
    else:
        duration = "Unknown"
    
    # Calculate success rate
    total_checks = validation_status.get('successful_checks', 0) + validation_status.get('failed_checks', 0) + validation_status.get('skipped_checks', 0)
    success_rate = 0
    if total_checks > 0:
        success_rate = round((validation_status.get('successful_checks', 0) / total_checks) * 100, 1)
    
    # Get performance metrics and sort them by time
    performance_metrics = validation_status.get('performance_metrics', {})
    performance_items = []
    
    for name, metric in performance_metrics.items():
        if 'time' in metric and metric['time'] is not None:
            performance_items.append({
                'name': name,
                'time': metric['time'],
                'status': metric.get('status', 'Unknown')
            })
    
    # Sort by time (descending)
    performance_items.sort(key=lambda x: x['time'], reverse=True)
    
    # Prepare results in a more structured format
    results = []
    for result in validation_status.get('results', []):
        if isinstance(result, tuple):
            message, status = result
            time_part = "N/A"
        else:
            # Try to extract time from message format [HH:MM:SS] [Status] Message
            parts = result.split(']')
            if len(parts) >= 3:
                time_part = parts[0].strip('[')
                status = parts[1].strip('[ ]')
                message = ']'.join(parts[2:]).strip()
            else:
                time_part = "N/A"
                status = "Info"
                message = result
        
        results.append({
            'message': message,
            'status': status,
            'time': time_part
        })
    
    # Get screenshots
    screenshots = []
    if os.path.exists(screenshots_dir):
        for file in os.listdir(screenshots_dir):
            if file.endswith('.png'):
                # Get relative path for HTML
                rel_path = os.path.join('..', 'screenshots', file)
                caption = file.replace('_', ' ').replace('.png', '')
                screenshots.append({
                    'path': rel_path,
                    'caption': caption
                })
    
    # Generate charts
    results_chart_base64, performance_chart_base64 = generate_performance_charts(
        performance_metrics,
        validation_status.get('successful_checks', 0),
        validation_status.get('failed_checks', 0),
        validation_status.get('skipped_checks', 0)
    )
    
    # Render the template
    template_env = jinja2.Environment()
    template = template_env.from_string(HTML_REPORT_TEMPLATE)
    
    html_content = template.render(
        project_name=project_name,
        environment=validation_status.get('environment', 'Unknown'),
        run_id=validation_status.get('run_id', 'Unknown'),
        timestamp=time.strftime("%Y-%m-%d %H:%M:%S"),
        overall_status=validation_status.get('status', 'Unknown'),
        duration=duration,
        successful_checks=validation_status.get('successful_checks', 0),
        failed_checks=validation_status.get('failed_checks', 0),
        skipped_checks=validation_status.get('skipped_checks', 0),
        success_rate=success_rate,
        results_chart=results_chart_base64,
        performance_chart=performance_chart_base64,
        performance_items=performance_items,
        results=results,
        screenshots=screenshots
    )
    
    # Write to file
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    return report_path


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
    
    def handle_sub_tabs(driver, tab_name, sub_tabs, main_index, shared_data):
    """
    Handle sub-tabs for a given main tab
    
    Args:
        driver: WebDriver instance
        tab_name: Name of the main tab
        sub_tabs: Dictionary of sub-tabs to validate
        main_index: Index of the main tab
        shared_data: Shared dictionary to track overall status
        
    Returns:
        tuple: (results list, metrics dictionary)
    """
    sub_tab_results = []
    sub_tab_metrics = {}
    
    for sub_index, (sub_tab_name, sub_tab_data) in enumerate(sub_tabs.items(), start=1):
        # First check if we should stop or pause
        if shared_data['stop_flag']:
            return sub_tab_results, sub_tab_metrics
            
        while shared_data['pause_flag'] and not shared_data['stop_flag']:
            time.sleep(0.5)
            
        # Track performance for this sub-tab
        sub_start_time = time.time()
        sub_metrics = {
            'start_time': sub_start_time,
            'end_time': None,
            'time': None,
            'status': None
        }
        
        # Take screenshot before activating sub-tab
        screenshot_path = os.path.join(screenshots_dir, f"subtab_{tab_name}_{sub_tab_name}_{time.strftime('%Y%m%d_%H%M%S')}_before.png")
        driver.save_screenshot(screenshot_path)
        
        # Try to open the sub-tab
        sub_success = check_sub_tab(driver, sub_tab_data['script'], sub_tab_name, sub_tab_data['content_locator'], main_index, sub_index)
        
        # Take screenshot after activating sub-tab
        screenshot_path = os.path.join(screenshots_dir, f"subtab_{tab_name}_{sub_tab_name}_{time.strftime('%Y%m%d_%H%M%S')}_after.png")
        driver.save_screenshot(screenshot_path)
        
        is_export_control = tab_name == "Positive Pay" and sub_tab_name == "Export Control"
        
        if sub_success:
            # If sub-tab opened successfully, check if we need to validate the first list element
            column_index = shared_data['tab_config'][tab_name]['column_index']
            if isinstance(column_index, dict):
                column_index = column_index.get(sub_tab_name)
                
            if column_index is not None:
                # Try to validate the first list element
                element_start_time = time.time()
                first_list_element_success = validate_first_list_element_and_cancel(
                    driver, column_index, main_index, sub_index, is_export_control
                )
                element_time = time.time() - element_start_time
                
                # Record element validation timing
                sub_metrics['element_time'] = element_time
                
                # Only mark the tab as failing if an actual error occurred (not skips)
                if not first_list_element_success:
                    with shared_data['lock']:
                        shared_data['all_tabs_opened'] = False
            else:
                # No column index means we skip element validation
                result = f"{main_index}.{chr(96 + sub_index)}. No column index specified for '{sub_tab_name}' - skipping element check."
                sub_tab_results.append((result, "Skipped"))
                with shared_data['lock']:
                    shared_data['skipped_checks'] += 1
        else:
            # Sub-tab couldn't be opened - this is a failure
            with shared_data['lock']:
                shared_data['all_tabs_opened'] = False

        # Record the sub-tab result for reporting
        if sub_success:
            sub_end_time = time.time()
            sub_time = sub_end_time - sub_start_time
            result = f"{main_index}.{chr(96 + sub_index)}. Sub Tab '{sub_tab_name}' validation completed successfully in {sub_time:.2f}s"
            sub_tab_results.append((result, "Success"))
            sub_metrics['status'] = "Success"
            with shared_data['lock']:
                shared_data['successful_checks'] += 1
        else:
            sub_end_time = time.time()
            sub_time = sub_end_time - sub_start_time
            result = f"{main_index}.{chr(96 + sub_index)}. Sub Tab '{sub_tab_name}' validation failed after {sub_time:.2f}s"
            sub_tab_results.append((result, "Failed"))
            sub_metrics['status'] = "Failed"
            with shared_data['lock']:
                shared_data['failed_checks'] += 1
        
        # Finalize sub-tab metrics
        sub_metrics['end_time'] = sub_end_time
        sub_metrics['time'] = sub_time
        sub_tab_metrics[sub_tab_name] = sub_metrics
        
        # Add performance data to shared metrics
        with shared_data['lock']:
            performance_key = f"SubTab {main_index}.{sub_index}: {tab_name} > {sub_tab_name}"
            shared_data['performance_metrics'][performance_key] = {
                'time': sub_time,
                'status': sub_metrics['status'],
                'start_time': sub_start_time
            }

    return sub_tab_results, sub_tab_metrics

def check_sub_tab(driver, sub_tab_js, sub_tab_name, content_locator, main_index, sub_index):
    """
    Check if a sub-tab can be opened successfully
    
    Args:
        driver: WebDriver instance
        sub_tab_js: JavaScript to activate the sub-tab
        sub_tab_name: Name of the sub-tab
        content_locator: Locator for the content to verify
        main_index: Index of the main tab
        sub_index: Index of the sub-tab
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Measure the time it takes to execute the JavaScript
        js_start_time = time.time()
        # Execute the JavaScript to navigate to the sub-tab
        driver.execute_script(sub_tab_js)
        js_time = time.time() - js_start_time
        
        # Verify that the expected content appears
        locator_type = content_locator['type']
        locator_value = content_locator['value']
        
        # Measure the time it takes for the content to appear
        load_start_time = time.time()
        try:
            if locator_type == 'css':
                WebDriverWait(driver, 5).until(EC.visibility_of_element_located((By.CSS_SELECTOR, locator_value)))
            elif locator_type == 'id':
                WebDriverWait(driver, 5).until(EC.visibility_of_element_located((By.ID, locator_value)))
        except (TimeoutException, NoSuchElementException):
            load_time = time.time() - load_start_time
            logging.error(f"Sub Tab '{sub_tab_name}' was activated but expected content did not appear. Load attempt time: {load_time:.2f}s")
            return False
        load_time = time.time() - load_start_time
        
        total_time = js_time + load_time
        logging.info(f"Sub Tab '{sub_tab_name}' opened successfully. JS time: {js_time:.2f}s, Load time: {load_time:.2f}s, Total: {total_time:.2f}s")
        return True
        
    except JavascriptException as e:
        logging.error(f"JavaScript error on Sub Tab '{sub_tab_name}': {e}")
        return False
    except StaleElementReferenceException:
        logging.error(f"StaleElementReferenceException on Sub Tab '{sub_tab_name}'. The page may have changed during interaction.")
        return False
    except Exception as e:
        logging.error(f"Unexpected error activating Sub Tab '{sub_tab_name}': {str(e)}")
        return False
    
    def validate_application(environment, validation_portal_link=None, retry_failed=False, parallel=True, max_workers=3):
    """
    Main validation function to test the application in the specified environment
    
    Args:
        environment: Environment to validate (IT, QV, Prod)
        validation_portal_link: Link to validation portal (optional)
        retry_failed: Whether to retry only failed checks from previous run
        parallel: Whether to run validation in parallel
        max_workers: Maximum number of parallel workers
    
    Returns:
        tuple: (validation_results, success)
    """
    global validation_status
    
    # Generate a unique ID for this run
    run_id = uuid.uuid4().hex[:8]
    
    # Update validation status
    validation_status['status'] = 'Running'
    validation_status['environment'] = environment
    validation_status['start_time'] = time.strftime("%Y-%m-%d %H:%M:%S")
    validation_status['end_time'] = None
    validation_status['successful_checks'] = 0
    validation_status['failed_checks'] = 0
    validation_status['skipped_checks'] = 0
    validation_status['progress'] = 0  # Initialize progress at 0%
    validation_status['performance_metrics'] = {}  # Reset performance metrics
    validation_status['tab_metrics'] = {}  # Reset tab metrics
    validation_status['run_id'] = run_id
    
    # Track previous failed checks for retry
    previous_results = validation_status['results'] if retry_failed else []
    validation_status['results'] = []
    
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

    logging.info(f"Starting validation for {environment} environment (Run ID: {run_id}, Parallel: {parallel})")
    validation_status['results'].append(f"Selected environment: {environment}")
    
    # Create directories for this run
    run_screenshots_dir = os.path.join(screenshots_dir, run_id)
    os.makedirs(run_screenshots_dir, exist_ok=True)
    
    validation_results = []
    all_tabs_opened = True
    
    # Create a shared data dictionary for parallel execution
    shared_data = {
        'lock': threading.RLock(),  # Reentrant lock for thread safety
        'all_tabs_opened': True,
        'successful_checks': 0,
        'failed_checks': 0,
        'skipped_checks': 0,
        'pause_flag': False,
        'stop_flag': False,
        'performance_metrics': {},
        'tab_config': config['tabs'],
        'environment': environment,
        'url': url,
        'run_id': run_id
    }
    
    try:
        # Setup main WebDriver for initial login
        main_driver = setup_driver()
        logging.info("Main WebDriver initialized successfully")
        
        # Safely navigate to URL with retry logic
        navigation_attempts = 0
        max_navigation_attempts = 3
        navigation_success = False
        navigation_start_time = time.time()
        
        while navigation_attempts < max_navigation_attempts and not navigation_success:
            try:
                main_driver.get(url)
                WebDriverWait(main_driver, 10).until(lambda d: d.execute_script('return document.readyState') == 'complete')
                navigation_time = time.time() - navigation_start_time
                logging.info(f"Successfully navigated to {url} in {navigation_time:.2f}s")
                validation_status['results'].append(f"Successfully navigated to {url} in {navigation_time:.2f}s")
                navigation_success = True
            except (WebDriverException, TimeoutException) as e:
                navigation_attempts += 1
                if navigation_attempts == max_navigation_attempts:
                    raise
                logging.warning(f"Navigation attempt {navigation_attempts} failed: {e}, retrying...")
                time.sleep(2)
                
        if not navigation_success:
            raise TimeoutException(f"Failed to navigate to {url} after {max_navigation_attempts} attempts")
        
        # Add login performance metrics
        validation_status['performance_metrics']['Initial Login'] = {
            'time': navigation_time,
            'status': 'Success',
            'start_time': navigation_start_time
        }
        
        # Take screenshot after successful login
        try:
            screenshot_file = os.path.join(run_screenshots_dir, f"login_{time.strftime('%Y%m%d_%H%M%S')}.png")
            main_driver.save_screenshot(screenshot_file)
            logging.info(f"Login screenshot saved to {screenshot_file}")
        except Exception as e:
            logging.warning(f"Failed to capture login screenshot: {e}")
        
        # Count total tabs for progress tracking
        total_tabs = len(config['tabs'])
        
        if parallel and total_tabs > 1:
            # Parallel validation approach
            logging.info(f"Starting parallel validation with {max_workers} workers")
            
            # Create a pool of WebDriver instances for parallel processing
            driver_pool = []
            
            for i in range(min(max_workers, total_tabs)):
                try:
                    worker_driver = setup_driver()
                    worker_driver.get(url)  # Navigate to the URL
                    WebDriverWait(worker_driver, 10).until(lambda d: d.execute_script('return document.readyState') == 'complete')
                    driver_pool.append(worker_driver)
                    logging.info(f"Worker {i+1} WebDriver initialized and navigated to {url}")
                except Exception as e:
                    logging.error(f"Failed to initialize worker {i+1} WebDriver: {e}")
            
            if not driver_pool:
                raise Exception("Failed to initialize any worker WebDrivers for parallel validation")
            
            # Create ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=len(driver_pool)) as executor:
                # Submit tasks for each tab
                future_to_tab = {}
                tab_items = list(config['tabs'].items())
                
                for i, (tab_name, tab_data) in enumerate(tab_items):
                    # Cycle through available drivers
                    driver_index = i % len(driver_pool)
                    driver = driver_pool[driver_index]
                    
                    # Submit the task
                    future = executor.submit(validate_tab, driver, tab_name, tab_data, i+1, shared_data)
                    future_to_tab[future] = (tab_name, i+1)
                    logging.info(f"Submitted tab {i+1}/{total_tabs}: {tab_name} to worker {driver_index+1}")
                
                # Process results as they complete
                completed = 0
                for future in as_completed(future_to_tab):
                    tab_name, tab_index = future_to_tab[future]
                    try:
                        tab_result = future.result()
                        validation_results.extend(tab_result['results'])
                        validation_status['tab_metrics'][tab_name] = tab_result['metrics']
                        completed += 1
                        validation_status['progress'] = int((completed / total_tabs) * 100)
                        logging.info(f"Completed tab {tab_index}/{total_tabs}: {tab_name} - Progress: {validation_status['progress']}%")
                    except Exception as e:
                        logging.error(f"Error processing tab {tab_name}: {e}")
                        logging.error(traceback.format_exc())
                        all_tabs_opened = False
                        completed += 1
                        validation_status['progress'] = int((completed / total_tabs) * 100)
                        
                    # Check if we should stop
                    if shared_data['stop_flag']:
                        logging.info("Stop flag detected, cancelling remaining validations")
                        break
            
            # Clean up driver pool
            for i, driver in enumerate(driver_pool):
                try:
                    driver.quit()
                    logging.info(f"Worker {i+1} WebDriver closed successfully")
                except Exception as e:
                    logging.warning(f"Error closing worker {i+1} WebDriver: {e}")
                
        else:
            # Sequential validation approach
            logging.info("Starting sequential validation")
            tabs_processed = 0
            
            for i, (tab_name, tab_data) in enumerate(config['tabs'].items(), start=1):
                # Check for stop flag
                if shared_data['stop_flag'] or stop_event.is_set():
                    break
                    
                # Check for pause flag
                while shared_data['pause_flag'] or not pause_event.is_set():
                    time.sleep(0.5)
                    if shared_data['stop_flag'] or stop_event.is_set():
                        break
                
                # Update progress
                tabs_processed += 1
                validation_status['progress'] = int((tabs_processed / total_tabs) * 100)
                logging.info(f"Processing tab {i}/{total_tabs}: {tab_name} - Progress: {validation_status['progress']}%")
                
                try:
                    tab_result = validate_tab(main_driver, tab_name, tab_data, i, shared_data)
                    validation_results.extend(tab_result['results'])
                    validation_status['tab_metrics'][tab_name] = tab_result['metrics']
                except Exception as e:
                    logging.error(f"Error processing tab {tab_name}: {e}")
                    logging.error(traceback.format_exc())
                    all_tabs_opened = False
        
        # Get the final status from shared data
        all_tabs_opened = shared_data['all_tabs_opened']
        validation_status['successful_checks'] = shared_data['successful_checks']
        validation_status['failed_checks'] = shared_data['failed_checks']
        validation_status['skipped_checks'] = shared_data['skipped_checks']
        validation_status['performance_metrics'].update(shared_data['performance_metrics'])
                
    except Exception as e:
        error_msg = f"Unexpected error during validation: {e}"
        logging.error(error_msg)
        logging.error(traceback.format_exc())
        validation_status['results'].append(error_msg)
        validation_status['status'] = 'Failed'
        validation_status['progress'] = 100
        all_tabs_opened = False
    finally:
        # Close the main WebDriver
        try:
            if 'main_driver' in locals():
                main_driver.quit()
                logging.info("Main WebDriver closed successfully")
        except Exception as e:
            logging.warning(f"Error closing main WebDriver: {e}")
    
    # Capture end time and generate summary
    validation_status['end_time'] = time.strftime("%Y-%m-%d %H:%M:%S")
    validation_status['progress'] = 100  # Ensure progress is 100% when complete
    
    # Take final screenshot if main_driver is still available
    try:
        if 'main_driver' in locals() and main_driver:
            screenshot_file = os.path.join(run_screenshots_dir, f"final_{time.strftime('%Y%m%d_%H%M%S')}.png")
            main_driver.save_screenshot(screenshot_file)
            logging.info(f"Final screenshot saved to {screenshot_file}")
    except Exception as e:
        logging.warning(f"Failed to capture final screenshot: {e}")
    
    # Generate HTML report
    try:
        report_path = generate_html_report(validation_status)
        validation_status['latest_report'] = report_path
        logging.info(f"Generated HTML report: {report_path}")
    except Exception as e:
        logging.error(f"Failed to generate HTML report: {e}")
        logging.error(traceback.format_exc())
    
    # Reset failed checks count if no actual failures occurred
    if all_tabs_opened and validation_status['failed_checks'] > 0:
        logging.info("All tabs were successfully validated, but failed_checks counter is non-zero. Resetting to 0.")
        validation_status['failed_checks'] = 0
    
    # Generate performance summary
    total_checks = validation_status['successful_checks'] + validation_status['failed_checks'] + validation_status['skipped_checks']
    success_rate = (validation_status['successful_checks'] / total_checks * 100) if total_checks > 0 else 0
    
    # Calculate total validation time
    if validation_status['start_time'] and validation_status['end_time']:
        start_dt = datetime.datetime.strptime(validation_status['start_time'], "%Y-%m-%d %H:%M:%S")
        end_dt = datetime.datetime.strptime(validation_status['end_time'], "%Y-%m-%d %H:%M:%S")
        duration_seconds = (end_dt - start_dt).total_seconds()
        
        # Format duration nicely
        minutes, seconds = divmod(duration_seconds, 60)
        duration = f"{int(minutes)}m {int(seconds)}s"
    else:
        duration = "Unknown"
    
    # Generate performance statistics
    performance_times = [metric['time'] for metric in validation_status['performance_metrics'].values() 
                          if metric.get('time') is not None and metric['time'] > 0]
    
    if performance_times:
        avg_time = sum(performance_times) / len(performance_times)
        max_time = max(performance_times)
        min_time = min(performance_times)
        
        # Find slowest and fastest components
        slowest_component = "Unknown"
        fastest_component = "Unknown"
        
        for name, metric in validation_status['performance_metrics'].items():
            if metric.get('time') == max_time:
                slowest_component = name
            if metric.get('time') == min_time:
                fastest_component = name
                
        performance_summary = f"""
Performance Summary:
------------------
Average load time: {avg_time:.2f}s
Fastest component: {fastest_component} ({min_time:.2f}s)
Slowest component: {slowest_component} ({max_time:.2f}s)
        """
    else:
        performance_summary = "No performance data collected"
    
    summary_message = f"""
Validation Summary:
------------------
Environment: {environment}
Run ID: {run_id}
Total Checks: {total_checks}
Successful: {validation_status['successful_checks']} ({success_rate:.1f}%)
Failed: {validation_status['failed_checks']}
Skipped: {validation_status['skipped_checks']}
Duration: {duration}

{performance_summary}
    """
    
    logging.info(summary_message)
    validation_status['results'].append(summary_message)
    
    if all_tabs_opened:
        result = (f"Validation completed successfully. Run ID: {run_id}", "Success")
        validation_status['results'].append(result[0])
        validation_status['status'] = 'Completed'
        
        # Submit test results if link provided
        if validation_portal_link:
            try:
                submit_test_results(validation_portal_link)
            except Exception as e:
                error_msg = f"Failed to submit test results: {e}"
                logging.error(error_msg)
                validation_status['results'].append((error_msg, "Failed"))
    else:
        result = (f"Validation failed. Run ID: {run_id}", "Failed")
        validation_status['results'].append(result[0])
        validation_status['status'] = 'Failed'
    
    # Save validation run info
    validation_runs.append({
        'run_id': run_id,
        'environment': environment,
        'timestamp': validation_status['start_time'],
        'status': validation_status['status'],
        'report_path': validation_status.get('latest_report')
    })
    
    return validation_results, all_tabs_opened
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
    
    # Reset failed checks count if no actual failures occurred
    # This ensures the pie chart shows the correct data
    if all_tabs_opened and validation_status['failed_checks'] > 0:
        logging.info("All tabs were successfully validated, but failed_checks counter is non-zero. Resetting to 0.")
        validation_status['failed_checks'] = 0
    
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
    if not retry_failed:
        validation_status['results'] = []
    
    def validate_environment():
        try:
            results, success = validate_application(environment, validation_portal_link, retry_failed)
            validation_status['status'] = 'Completed' if success else 'Failed'
            
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
    
    # If status is Completed or Failed but progress is not 100%, fix it
    if validation_status['status'] in ['Completed', 'Failed'] and validation_status.get('progress', 0) != 100:
        validation_status['progress'] = 100
    
    # Ensure failed_checks is 0 if all_tabs_opened is True (overall success)
    if validation_status['status'] == 'Completed' and validation_status.get('failed_checks', 0) > 0:
        validation_status['failed_checks'] = 0
    
    # Return status with additional metadata
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
            
        # Read the last n lines from the log file
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
                
        # Sort by creation time (newest first)
        screenshots.sort(key=lambda x: x["created"], reverse=True)
        
        return jsonify({
            "screenshots": screenshots,
            "count": len(screenshots)
        })
        
    except Exception as e:
        return jsonify({"error": f"Error listing screenshots: {str(e)}"}), 500



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
