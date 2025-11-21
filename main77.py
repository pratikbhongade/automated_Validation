
import pyodbc
import pandas as pd
import dash
import dash_bootstrap_components as dbc
from dash import dcc, html
from dash.dependencies import Input, Output, State
from datetime import datetime, timedelta
import os
import sys
from PIL import Image
from selenium import webdriver
from selenium.webdriver.edge.service import Service as EdgeService
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from io import BytesIO
import io
import json
import time
import urllib.parse
from time import perf_counter
import win32com.client as win32
# Removed multiprocessing to avoid PyInstaller issues
import plotly.express as px
import plotly.graph_objects as go
import base64
time.clock = time.time
import webbrowser
import threading
import logging
import logging.handlers
import subprocess
import socket
import threading
import traceback
from pathlib import Path

# Chatbot functionality removed

# ============================================================================
# LOGGING CONFIGURATION
# ============================================================================

def setup_logging():
    """Set up comprehensive logging for debugging PyInstaller issues"""
    try:
        # Determine log directory - prefer user directory for write access
        if hasattr(sys, '_MEIPASS'):
            # In PyInstaller bundle - use user directory
            log_dir = os.path.join(os.path.expanduser("~"), "AspireDashboard", "logs")
        else:
            # In development - use project directory
            log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
        
        # Create log directory
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, "dashboard.log")
        
        # Configure root logger
        logger = logging.getLogger()
        logger.setLevel(logging.DEBUG)
        
        # Remove any existing handlers to avoid duplicates
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
        
        # File handler with rotation
        file_handler = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=10*1024*1024, backupCount=5
        )
        file_handler.setLevel(logging.DEBUG)
        
        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        
        # Formatter
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s'
        )
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(logging.Formatter('%(levelname)s - %(message)s'))
        
        # Add handlers
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)
        
        # Log startup information
        logger.info("="*60)
        logger.info("ASPIRE DASHBOARD STARTUP")
        logger.info("="*60)
        logger.info(f"Python executable: {sys.executable}")
        logger.info(f"Python version: {sys.version}")
        logger.info(f"Current working directory: {os.getcwd()}")
        logger.info(f"Script location: {os.path.abspath(__file__)}")
        logger.info(f"PyInstaller bundle: {hasattr(sys, '_MEIPASS')}")
        if hasattr(sys, '_MEIPASS'):
            logger.info(f"_MEIPASS directory: {sys._MEIPASS}")
        logger.info(f"Log directory: {log_dir}")
        logger.info(f"Log file: {log_file}")
        
        return logger, log_file
        
    except Exception as e:
        # Fallback logging setup
        logging.basicConfig(
            level=logging.DEBUG,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        logger = logging.getLogger()
        logger.error(f"Failed to setup comprehensive logging: {e}")
        return logger, None

# Initialize logging
logger, log_file_path = setup_logging()

# ----------------------------------------------------------------------------
# CONFIG LOADING
# ----------------------------------------------------------------------------
def load_config():
    """Load configuration from JSON. Falls back to sane defaults if missing."""
    try:
        # Try next to script, and support PyInstaller bundles
        config_candidates = [
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json"),
            resource_path("config.json"),
            "config.json"
        ]
        for cfg in config_candidates:
            if os.path.exists(cfg):
                with open(cfg, "r", encoding="utf-8") as f:
                    cfg_data = json.load(f)
                logger.info(f"Loaded configuration from: {cfg}")
                return cfg_data
        logger.warning("config.json not found; using built-in defaults")
    except Exception as e:
        logger.error(f"Error loading config.json: {e}")

    # Defaults if config.json missing or invalid
    return {
        "database_environments": {
            "PROD": {"SERVER": r"SDC01ASRSQPD01S\PSQLINST01", "DATABASE": "ASPIRE", "DISPLAY_NAME": "Production"},
            "IT": {"SERVER": r"SDC01ASRSQIT01S\PSQLINST01", "DATABASE": "ASPIRE", "DISPLAY_NAME": "IT Environment"},
            "QV": {"SERVER": r"SDC01ASRSQQV01S\PSQLINST01", "DATABASE": "ASPIRE", "DISPLAY_NAME": "QV Environment"}
        },
        "email": {
            "to": ["Pratik_Bhongade@Keybank.com", "karen.a.tiemann-wozniak@key.com"],
            "cc": []
        }
    }

# ============================================================================
# ENHANCED PYINSTALLER COMPATIBILITY FUNCTIONS
# ============================================================================

def resource_path(relative_path):
    """Get absolute path to resource, works for dev and for PyInstaller with enhanced logging"""
    try:
        if hasattr(sys, '_MEIPASS'):
            # PyInstaller creates a temp folder and stores path in _MEIPASS
            base_path = sys._MEIPASS
            full_path = os.path.join(base_path, relative_path)
            logger.debug(f"PyInstaller resource path: {full_path}")
        else:
            base_path = os.path.abspath(".")
            full_path = os.path.join(base_path, relative_path)
            logger.debug(f"Development resource path: {full_path}")
        
        logger.debug(f"Resource path for '{relative_path}': {full_path}")
        logger.debug(f"Resource exists: {os.path.exists(full_path)}")
        
        return full_path
        
    except Exception as e:
        logger.error(f"Error in resource_path for '{relative_path}': {e}")
        # Fallback
        fallback_path = os.path.join(os.path.abspath("."), relative_path)
        logger.warning(f"Using fallback path: {fallback_path}")
        return fallback_path

# Load configuration once (after resource_path is defined)
CONFIG = load_config()

def get_edge_driver_path():
    """Get the path to Edge WebDriver for both dev and PyInstaller with enhanced error handling"""
    try:
        if hasattr(sys, '_MEIPASS'):
            # In PyInstaller bundle
            driver_path = resource_path(os.path.join('edgedriver_win64', 'msedgedriver.exe'))
            logger.info(f"PyInstaller Edge driver path: {driver_path}")
        else:
            # In development - updated for new project structure
            driver_path = r"C:\Dashboard Test\EXETest\build_files\edgedriver_win64\msedgedriver.exe"
            logger.info(f"Development Edge driver path: {driver_path}")
        
        # Verify the driver exists
        if os.path.exists(driver_path):
            logger.info(f"Edge driver found at: {driver_path}")
        else:
            logger.error(f"Edge driver NOT found at: {driver_path}")
            # Try alternative locations
            alternative_paths = [
                resource_path("msedgedriver.exe"),
                os.path.join(os.path.dirname(sys.executable), "msedgedriver.exe"),
                "msedgedriver.exe"
            ]
            
            for alt_path in alternative_paths:
                logger.debug(f"Checking alternative path: {alt_path}")
                if os.path.exists(alt_path):
                    logger.info(f"Found Edge driver at alternative location: {alt_path}")
                    return alt_path
            
            logger.error("Could not find Edge driver in any location")
        
        return driver_path
        
    except Exception as e:
        logger.error(f"Error getting Edge driver path: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return "msedgedriver.exe"  # Fallback

def get_logo_path():
    """Get the path to the logo for both dev and PyInstaller with enhanced error handling"""
    try:
        if hasattr(sys, '_MEIPASS'):
            # In PyInstaller bundle
            logo_path = resource_path(os.path.join('assets', 'Aspire.png'))
            logger.debug(f"PyInstaller logo path: {logo_path}")
        else:
            # In development - check multiple possible locations
            possible_paths = [
                r'C:\Dashboard Test\EXETest\assets\Aspire.png',
                r'C:\Dashboard Test\EXETest\build_files\assets\Aspire.png',
                r'assets\Aspire.png',
                r'Aspire.png'
            ]
            
            logo_path = None
            for path in possible_paths:
                logger.debug(f"Checking logo path: {path}")
                if os.path.exists(path):
                    logo_path = path
                    logger.debug(f"Found logo at: {path}")
                    break
            
            if not logo_path:
                # If no file found, return the expected path
                logo_path = r'C:\Dashboard Test\EXETest\assets\Aspire.png'
                logger.warning(f"Using default logo path: {logo_path}")
        
        logger.info(f"Logo path: {logo_path} (exists: {os.path.exists(logo_path)})")
        return logo_path
        
    except Exception as e:
        logger.error(f"Error getting logo path: {e}")
        return resource_path(os.path.join('assets', 'Aspire.png'))

def get_template_path():
    """Get the path to templates for both dev and PyInstaller"""
    try:
        if hasattr(sys, '_MEIPASS'):
            # In PyInstaller bundle
            template_path = resource_path(os.path.join('templates', 'layout.html'))
            logger.debug(f"PyInstaller template path: {template_path}")
        else:
            # In development - updated for new project structure
            template_path = r'C:\Dashboard Test\EXETest\templates\layout.html'
            logger.debug(f"Development template path: {template_path}")
        
        logger.info(f"Template path: {template_path} (exists: {os.path.exists(template_path)})")
        return template_path
        
    except Exception as e:
        logger.error(f"Error getting template path: {e}")
        return resource_path(os.path.join('templates', 'layout.html'))

def get_output_directory():
    """Get the output directory for screenshots and temp files with enhanced error handling"""
    try:
        # Try to use a writable directory in user space
        output_dir = os.path.join(os.path.expanduser("~"), "AspireDashboard")
        os.makedirs(output_dir, exist_ok=True)
        logger.info(f"Output directory created/verified: {output_dir}")
        
        # Test write access
        test_file = os.path.join(output_dir, "test_write.tmp")
        with open(test_file, 'w') as f:
            f.write("test")
        os.remove(test_file)
        logger.debug("Write access confirmed for output directory")
        
        return output_dir
        
    except Exception as e:
        logger.error(f"Error creating output directory: {e}")
        # Fallback to current directory
        fallback_dir = os.path.abspath(".")
        logger.warning(f"Using fallback output directory: {fallback_dir}")
        return fallback_dir

def check_port_available(port):
    """Check if a port is available"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(1)
            result = sock.connect_ex(('127.0.0.1', port))
            available = result != 0
            logger.debug(f"Port {port} available: {available}")
            return available
    except Exception as e:
        logger.error(f"Error checking port {port}: {e}")
        return False

# ============================================================================
# ENHANCED INITIALIZATION WITH ERROR HANDLING
# ============================================================================

# Path to your logo image - Updated for PyInstaller with enhanced error handling
logo_path = get_logo_path()

# Encode the image to base64 with comprehensive error handling
logo_base64 = None
try:
    if os.path.exists(logo_path):
        with open(logo_path, 'rb') as f:
            logo_base64 = base64.b64encode(f.read()).decode('ascii')
        logger.info(f"Logo loaded successfully from: {logo_path}")
    else:
        raise FileNotFoundError(f"Logo file not found at: {logo_path}")
        
except FileNotFoundError as e:
    logger.warning(f"Warning: {e}")
    
    # Try to find logo in common locations
    search_paths = [
        'assets/Aspire.png',
        'assets\\Aspire.png',
        'Aspire.png',
        'build_files/assets/Aspire.png',
        'build_files\\assets\\Aspire.png',
        resource_path('Aspire.png'),
        resource_path(os.path.join('assets', 'Aspire.png')),
        r'C:\Dashboard Test\EXETest\assets\Aspire.png',
        r'C:\Dashboard Test\EXETest\build_files\assets\Aspire.png'
    ]
    
    logo_found = False
    for search_path in search_paths:
        logger.debug(f"Searching for logo at: {search_path}")
        if os.path.exists(search_path):
            try:
                with open(search_path, 'rb') as f:
                    logo_base64 = base64.b64encode(f.read()).decode('ascii')
                logger.info(f"Logo found and loaded from: {search_path}")
                logo_found = True
                break
            except Exception as e2:
                logger.error(f"Error loading logo from {search_path}: {e2}")
                continue
    
    if not logo_found:
        logger.warning("Using placeholder logo - please ensure Aspire.png is in the assets folder")
        # Create a placeholder base64 image (1x1 transparent pixel)
        logo_base64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="

except Exception as e:
    logger.error(f"Unexpected error loading logo: {e}")
    logger.error(f"Traceback: {traceback.format_exc()}")
    logo_base64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="

# ============================================================================
# ORIGINAL FUNCTIONS (Enhanced with logging)
# ============================================================================

# Function to get the last business day
def get_last_business_day():
    logger.debug("Calculating last business day")
    today = datetime.today()
    if today.weekday() == 0:  # Monday
        last_business_day = today - timedelta(days=3)
    elif today.weekday() == 6:  # Sunday
        last_business_day = today - timedelta(days=2)
    else:  # Any other day (Tuesday to Saturday)
        last_business_day = today - timedelta(days=1)

    # Ensure the date is within the current month
    if last_business_day.month != today.month:
        last_business_day = today.replace(day=1) - timedelta(days=1)
        while last_business_day.weekday() >= 5:  # Skip weekends
            last_business_day -= timedelta(days=1)
    
    logger.debug(f"Last business day calculated: {last_business_day.strftime('%Y-%m-%d')}")
    return last_business_day

# Get the default date
default_date = get_last_business_day().strftime('%Y-%m-%d')
logger.info(f"Default date set to: {default_date}")

# Database configuration for different environments (loaded from CONFIG)
DATABASE_CONFIG = CONFIG.get('database_environments', {})

# Function to fetch data
def fetch_data(selected_date, environment='PROD'):
    logger.info(f"Fetching data for date: {selected_date}, Environment: {environment}")
    try:
        # Get database configuration for the selected environment
        db_config = DATABASE_CONFIG.get(environment, DATABASE_CONFIG['PROD'])
        
        # Log resolved config
        driver = db_config.get('DRIVER', '{SQL Server}')
        trusted = db_config.get('TRUSTED_CONNECTION', 'yes')
        logger.info(
            f"Resolved DB config -> SERVER={db_config.get('SERVER')}, DATABASE={db_config.get('DATABASE')}, "
            f"DRIVER={driver}, TRUSTED_CONNECTION={trusted}"
        )
        conn_str = (
            f"DRIVER={driver};"
            f"SERVER={db_config['SERVER']};"
            f"DATABASE={db_config['DATABASE']};"
            f"Trusted_Connection={trusted};"
        )
        logger.debug(f"Attempting database connection to {db_config['DISPLAY_NAME']}...")
        conn = pyodbc.connect(conn_str)
        logger.info(f"Database connection successful to {db_config['DISPLAY_NAME']}")

        query = f"""
        SELECT 
            CASE 
                WHEN DATEPART(hour, JSH.StartTime) < 14 THEN CONVERT(varchar, DATEADD(day, -1, JSH.StartTime), 23) 
                ELSE CONVERT(varchar, JSH.StartTime, 23) 
            END as ProcessingDate, 
            JSJ.JobStreamJoboid as Joboid, 
            JSJ.Name as JobName,
            CONVERT(datetime, JSH.StartTime AT TIME ZONE 'UTC' AT TIME ZONE 'Eastern Standard Time') AS [StartTime], 
            CONVERT(datetime, JSH.EndTime AT TIME ZONE 'UTC' AT TIME ZONE 'Eastern Standard Time') AS [EndTime], 
            JSH.Status, 
            JSH.Message 
        FROM JobStreamTaskHistory JSH
        LEFT JOIN JobStreamTask JST ON JSH.JobStreamTaskOid = JST.JobStreamTaskoid 
        JOIN JobStreamJob JSJ ON JSJ.JobStreamJoboid = JST.JobStreamJoboid
        WHERE 
            CASE 
                WHEN DATEPART(hour, JSH.StartTime) < 14 THEN CONVERT(varchar, DATEADD(day, -1, JSH.StartTime), 23) 
                ELSE CONVERT(varchar, JSH.StartTime, 23) 
            END = '{selected_date}'
        ORDER BY StartTime ASC
        """
        logger.debug("Executing main data query")
        df = pd.read_sql(query, conn)
        logger.debug(f"Main query returned {len(df)} rows")

        query_50_days = """
        SELECT 
            CONVERT(varchar, JSH.StartTime, 23) as ProcessingDate, 
            JSH.Status,
            JSJ.Name as JobName,
            CONVERT(datetime, JSH.StartTime AT TIME ZONE 'UTC' AT TIME ZONE 'Eastern Standard Time') AS [StartTime],
            CONVERT(datetime, JSH.EndTime AT TIME ZONE 'UTC' AT TIME ZONE 'Eastern Standard Time') AS [EndTime],
            JSH.Message
        FROM JobStreamTaskHistory JSH
        LEFT JOIN JobStreamTask JST ON JSH.JobStreamTaskOid = JST.JobStreamTaskoid 
        JOIN JobStreamJob JSJ ON JSJ.JobStreamJoboid = JST.JobStreamJoboid
        WHERE JSH.StartTime >= DATEADD(day, -50, GETDATE())
        """
        logger.debug("Executing 50-day data query")
        df_50_days = pd.read_sql(query_50_days, conn)
        logger.debug(f"50-day query returned {len(df_50_days)} rows")

        query_job_duration = """
        SELECT 
            CONVERT(varchar, JSH.StartTime, 23) as ProcessingDate, 
            JSJ.Name as JobName,
            DATEDIFF(SECOND, JSH.StartTime, JSH.EndTime) / 60.0 as DurationMinutes
        FROM JobStreamTaskHistory JSH
        LEFT JOIN JobStreamTask JST ON JSH.JobStreamTaskOid = JST.JobStreamTaskoid 
        JOIN JobStreamJob JSJ ON JSJ.JobStreamJoboid = JST.JobStreamJoboid
        WHERE JSH.StartTime >= DATEADD(month, -6, GETDATE())
        """
        logger.debug("Executing job duration query")
        df_job_duration = pd.read_sql(query_job_duration, conn)
        logger.debug(f"Job duration query returned {len(df_job_duration)} rows")

        query_unlock_online = f"""
        SELECT JobName, CONVERT(datetime, EndTime) AS CompletionTime, Status 
        FROM Job_StatsVW 
        WHERE JobName = 'UnLock Online' 
        AND ProcessingDate = '{selected_date}'
        """
        logger.debug("Executing unlock online query")
        df_unlock_online = pd.read_sql(query_unlock_online, conn)
        logger.debug(f"Unlock online query returned {len(df_unlock_online)} rows")

        conn.close()
        logger.debug("Database connection closed")

        return df, df_50_days, df_job_duration, df_unlock_online
    except Exception as e:
        logger.error(f"Error fetching data: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return None, None, None, None

# Fetch initial data with enhanced error handling and logging
logger.info("Fetching initial data...")
try:
    df, df_50_days, df_job_duration, df_unlock_online = fetch_data(default_date)
    if df is not None:
        logger.info(f"Initial data loaded successfully for {default_date}")
    else:
        raise Exception("Database query returned None")
except Exception as e:
    logger.error(f"Warning: Could not fetch initial data: {e}")
    logger.error(f"Traceback: {traceback.format_exc()}")
    # Create empty DataFrames as fallback
    df = pd.DataFrame()
    df_50_days = pd.DataFrame()
    df_job_duration = pd.DataFrame()
    df_unlock_online = pd.DataFrame()
    logger.info("Using empty DataFrames as fallback")

# Initialize the Dash app with Bootstrap CSS and suppress callback exceptions
logger.info("Initializing Dash application...")
try:
    app = dash.Dash(
        __name__, 
        external_stylesheets=[dbc.themes.BOOTSTRAP], 
        assets_folder='assets', 
        suppress_callback_exceptions=True
    )
    logger.info("Dash app initialized successfully")
except Exception as e:
    logger.error(f"Error initializing Dash app: {e}")
    logger.error(f"Traceback: {traceback.format_exc()}")
    raise

# Set custom HTML template - Updated for PyInstaller with enhanced error handling
logger.info("Setting up HTML template...")
template_path = get_template_path()
try:
    if os.path.exists(template_path):
        with open(template_path, 'r') as f:
            app.index_string = f.read()
        logger.info(f"Custom template loaded from: {template_path}")
    else:
        raise FileNotFoundError(f"Template file not found at: {template_path}")
except FileNotFoundError as e:
    logger.warning(f"Warning: {e}")
    logger.info("Using fallback HTML template")
    # Fallback if template not found
    app.index_string = '''
    <!DOCTYPE html>
    <html>
        <head>
            {%metas%}
            <title>{%title%}</title>
            {%favicon%}
            {%css%}
        </head>
        <body>
            {%app_entry%}
            <footer>
                {%config%}
                {%scripts%}
                {%renderer%}
            </footer>
        </body>
    </html>
    '''
except Exception as e:
    logger.error(f"Error loading template: {e}")
    logger.error(f"Traceback: {traceback.format_exc()}")

# Create assets folder if it doesn't exist - Enhanced with logging
logger.info("Setting up assets directory...")
assets_path = None
try:
    assets_path = resource_path('assets')
    os.makedirs(assets_path, exist_ok=True)
    logger.info(f"Assets directory created/verified: {assets_path}")
except Exception as e:
    logger.warning(f"Primary assets path failed: {e}")
    try:
        assets_path = os.path.join(get_output_directory(), 'assets')
        os.makedirs(assets_path, exist_ok=True)
        logger.info(f"Fallback assets directory created: {assets_path}")
    except Exception as e2:
        logger.warning(f"Fallback assets path failed: {e2}")
        try:
            assets_path = 'assets'
            os.makedirs(assets_path, exist_ok=True)
            logger.info(f"Local assets directory created: {assets_path}")
        except Exception as e3:
            logger.error(f"Could not create any assets directory: {e3}")
            assets_path = '.'  # Ultimate fallback

# Create a custom CSS file for calendar styling
logger.info("Creating custom CSS file...")
try:
    css_path = os.path.join(assets_path, 'custom_calendar.css')
    with open(css_path, 'w') as f:
        f.write('''
/* Calendar styling */
.SingleDatePickerInput {
    border: none !important;
    background-color: transparent !important;
}
.DateInput {
    background-color: white;
    border-radius: 8px;
    width: 130px !important;
}
.DateInput_input {
    border-radius: 8px;
    font-weight: bold;
    color: #2A3F5F;
    width: 100%;
    padding: 8px 12px;
    height: auto;
    border: 2px solid #007bff;
    transition: border-color 0.3s;
}
.DateInput_input:hover {
    border-color: #0056b3;
}
.DateInput_input:focus {
    border-color: #004085;
    box-shadow: 0 0 0 0.2rem rgba(0, 123, 255, 0.25);
}
.CalendarDay__selected {
    background: #007bff !important;
    border: 1px double #007bff !important;
    color: white !important;
}
.CalendarDay__selected:hover {
    background: #0056b3 !important;
    color: white !important;
}
.CalendarDay__today {
    background: #e6f2ff !important;
    border: 1px solid #007bff !important;
    color: #007bff !important;
    font-weight: bold !important;
}
.DayPickerKeyboardShortcuts_show {
    display: none;
}
.CalendarMonth_caption {
    padding-bottom: 50px !important;
    font-weight: bold !important;
    color: #2A3F5F !important;
}
''')
    logger.info(f"Custom CSS file created: {css_path}")
except Exception as e:
    logger.error(f"Warning: Could not create custom CSS file: {e}")
    logger.error(f"Traceback: {traceback.format_exc()}")

# Add email preview modal
email_preview_modal = dbc.Modal([
    dbc.ModalHeader("Email Preview"),
    dbc.ModalBody([
        html.Div(id="email-preview-content"),
        html.Iframe(id="email-preview-frame", style={"width": "100%", "height": "500px", "border": "none"})
    ]),
    dbc.ModalFooter([
        dbc.Button("Cancel", id="send-email-cancel", className="ml-auto", color="secondary"),
        dbc.Button("Send Email", id="send-email-confirm", color="primary")
    ])
], id="email-preview-modal", size="xl")

# Layout of the dashboard
app.layout = dbc.Container([
    dcc.Location(id='url', refresh=False),
    dbc.Row([
        dbc.Col(html.Img(src='data:image/png;base64,{}'.format(logo_base64), height='60px'), width='auto'),
        dbc.Col(html.H1("AspireVision Dashboard", className='text-center mb-4', style={'font-weight': 'bold', 'color': '#2A3F5F', 'border-bottom': '1px solid #2A3F5F'}), width=True, className='d-flex justify-content-center align-items-center'),
        dbc.Col([
            html.Div("Select Environment", className='text-center mb-2', style={'font-weight': 'bold'}),
            dcc.Dropdown(
                id='environment-selector',
                options=[
                    {'label': '🟢 Production', 'value': 'PROD'},
                    {'label': '🔵 IT Environment', 'value': 'IT'},
                    {'label': '🟡 QV Environment', 'value': 'QV'}
                ],
                value='PROD',  # Default to Production
                clearable=False,
                style={
                    'width': '180px',
                    'font-weight': 'bold',
                    'font-size': '14px'
                },
                persistence=True,
                persistence_type='session'
            ),
            dbc.Tooltip("Select Database Environment", target="environment-selector")
        ], width='auto', className='d-flex flex-column align-items-center'),
        dbc.Col([
            html.Div("Pick a date", className='text-center mb-2', style={'font-weight': 'bold'}),
            html.Div([
                dcc.DatePickerSingle(
                    id='date-picker-table',
                    display_format='YYYY-MM-DD',
                    date=default_date,  # Default date
                    style={
                        'font-weight': 'bold', 
                        'border-radius': '8px',
                        'border': '2px solid #007bff',
                        'font-family': 'Arial, sans-serif',
                        'box-shadow': '0 2px 10px rgba(0, 123, 255, 0.2)',
                        'width': '100%'
                    },
                    min_date_allowed='2020-01-01',
                    max_date_allowed='2030-12-31',
                    day_size=36,
                    first_day_of_week=1,  # Monday as first day
                    initial_visible_month=default_date,
                    clearable=False,
                    month_format='MMMM YYYY',
                    persistence=False
                ),
            ], style={'width': '100%', 'position': 'relative'}),
            html.I(className="fa fa-calendar", id="calendar-icon", style={"margin-left": "10px", "color": "#007bff"}),
            dbc.Tooltip("Select a date", target="calendar-icon")
        ], width='auto', className='d-flex justify-content-end align-items-center')
    ], className='border mb-3 align-items-center justify-content-center'),
    dbc.Tabs([
        dbc.Tab(label='Main Dashboard', tab_id='main-dashboard', children=[
            dbc.Row([
                dbc.Col([
                    dbc.Card(
                        dbc.CardBody([
                            html.H4("Aspire Unlock Online", className='card-title'),
                            dcc.Loading(
                                id="loading-unlock-online",
                                type="default",
                                children=html.Div(
                                    id='unlock-online-table',
                                    style={'width': '50%', 'font-size': '21px'}  # Removed overflow
                                )
                            )
                        ]),
                        className='mb-4 border'
                    )
                ], width=12)
            ], className='border mb-3'),
            # New Card for Failed Job Information (with Solution Input)
            dbc.Row([
                dbc.Col([
                    dcc.Loading(
                        id="loading-failed-jobs",
                        type="default",
                        children=html.Div(
                            id='failed-jobs-info',
                            className='fade-in'
                        )
                    )
                ], width=12)
            ], className='border mb-3', id='failed-jobs-row'),
            dbc.Row([
                dbc.Col([
                    dcc.Loading(
                        id="loading-job-table",
                        type="default",
                        children=html.Div(id='job-table-container')
                    )
                ], width=12)
            ], className='border'),
            dbc.Row([
                dbc.Col([
                    dcc.Loading(
                        id="loading-status-bar-graph",
                        type="default",
                        children=dcc.Graph(id='status-bar-graph')
                    )
                ], width=12)
            ], className='border'),
            dbc.Row([
                dbc.Col([
                    dcc.Loading(
                        id="loading-failure-trend-graph",
                        type="default",
                        children=dcc.Graph(id='failure-trend-graph')
                    )
                ], width=12)
            ], className='border'),
            # Time Difference between TRIAD and Benchmark Update jobs
            dbc.Row([
                dbc.Col([
                    dcc.Loading(
                        id="loading-time-difference-graph",
                        type="default",
                        children=dcc.Graph(id='time-difference-graph')
                    )
                ], width=9),
                dbc.Col([
                    dcc.Loading(
                        id="loading-time-difference-table",
                        type="default",
                        children=html.Div(id='time-difference-table', style={'font-size': '14px'})
                    )
                ], width=3)
            ], className='border'),
            dbc.Row([
                dbc.Col([
                    html.Button(
                        "Send Email", 
                        id="send-email-button", 
                        className="btn btn-primary mt-3", 
                        style={
                            'width': '200px',
                            'font-weight': 'bold',
                            'cursor': 'pointer',
                            'box-shadow': '0 2px 5px rgba(0, 0, 0, 0.2)'
                        },
                        n_clicks=0  # Initialize with 0 clicks
                    ),
                    dbc.Tooltip("Send Dashboard via Email", target="send-email-button")
                ], width=12, className='d-flex justify-content-center')
            ], className='border mt-3', id='send-email-row')
        ]),
        dbc.Tab(label='Job Duration Analysis', tab_id='job-duration', children=[
            dbc.Row([
                dbc.Col([
                    dcc.Loading(
                        id="loading-job-duration-graph",
                        type="default",
                        children=dcc.Graph(id='job-duration-graph')
                    )
                ], width=12)
            ], className='border mt-3')
        ]),
        dbc.Tab(label='Anomaly Detection', tab_id='anomaly-detection', children=[
            dbc.Row([
                dbc.Col([
                    dcc.Loading(
                        id="loading-anomaly-detection-graph",
                        type="default",
                        children=dcc.Graph(id='anomaly-detection-graph')
                    )
                ], width=12)
            ], className='border mt-3')
        ]),
        dbc.Tab(label='Time to Recovery', tab_id='time-to-recovery', children=[
            dbc.Row([
                dbc.Col([
                    dcc.Loading(
                        id="loading-time-to-recovery-graph",
                        type="default",
                        children=dcc.Graph(id='time-to-recovery-graph')
                    )
                ], width=12)
            ], className='border mt-3')
        ])
    ]),
    dcc.ConfirmDialog(
        id='confirm-dialog',
        message='Email sent successfully!',
    ),
    email_preview_modal,
], fluid=True, className='p-4 bg-light rounded-3 shadow')

# Callback to update the tables and graphs based on the selected date
@app.callback(
    [Output('unlock-online-table', 'children'),
     Output('failed-jobs-info', 'children'),
     Output('job-table-container', 'children'),
     Output('status-bar-graph', 'figure'),
     Output('failure-trend-graph', 'figure'),
     Output('time-difference-graph', 'figure'),
     Output('time-difference-table', 'children'),
     Output('job-duration-graph', 'figure'),
     Output('anomaly-detection-graph', 'figure'),
     Output('time-to-recovery-graph', 'figure')],
    [Input('date-picker-table', 'date'),
     Input('environment-selector', 'value'),
     Input('url', 'href')]
)
def update_dashboard(selected_date, environment, href):
    try:
        # Sync from URL only when URL triggers the callback (avoid overriding DatePicker changes)
        try:
            ctx = dash.callback_context
            if ctx and ctx.triggered:
                trigger_id = ctx.triggered[0]['prop_id'].split('.')[0]
            else:
                trigger_id = None
            if trigger_id == 'url' and href:
                parsed = urllib.parse.urlparse(href)
                q = urllib.parse.parse_qs(parsed.query)
                env_q = q.get('env', [None])[0]
                date_q = q.get('date', [None])[0]
                if env_q in DATABASE_CONFIG:
                    environment = env_q
                if date_q:
                    selected_date = date_q
        except Exception:
            pass

        # Defensive: selected_date may be None on initial render
        if not selected_date:
            logger.info("No selected_date provided; returning empty visuals")
            message = html.Div([html.H4("No Data Available", className='text-center text-danger')])
            empty_fig = px.bar()
            return message, None, message, empty_fig, empty_fig, empty_fig, html.Div(), empty_fig, empty_fig, empty_fig

        now = datetime.now()
        selected_date_obj = datetime.strptime(selected_date, '%Y-%m-%d')
        
        # Check if the selected date is a weekend, future date, or before 9 PM today
        if selected_date_obj.weekday() >= 5 or selected_date_obj > now or (selected_date == now.strftime('%Y-%m-%d') and now.hour < 21):
            if selected_date_obj.weekday() >= 5:
                message = html.Div([html.H4("No data available due to holidays or weekends", className='text-center text-danger')])
            elif selected_date_obj > now:
                message = html.Div([html.H4("Batch yet to start", className='text-center text-danger')])
            else:
                message = html.Div([html.H4("Batch yet to start", className='text-center text-danger')])

            empty_fig = px.bar()
            return message, None, message, empty_fig, empty_fig, empty_fig, html.Div(), empty_fig, empty_fig, empty_fig

        try:
            df, df_50_days, df_job_duration, df_unlock_online = fetch_data(selected_date, environment)
        except Exception as e:
            error_message = html.Div([
                html.H4("Database Connection Error", className='text-center text-danger'),
                html.P(f"Could not connect to database: {str(e)}", className='text-center')
            ])
            empty_fig = px.bar()
            return error_message, None, error_message, empty_fig, empty_fig, empty_fig, html.Div(), empty_fig, empty_fig, empty_fig

        # Defensive: handle None returns to avoid NoneType errors
        if df is None or df_50_days is None or df_job_duration is None or df_unlock_online is None:
            logger.warning(f"fetch_data returned None (env={environment}, date={selected_date}); returning empty visuals")
            message = html.Div([html.H4("No Data Available", className='text-center text-danger')])
            empty_fig = px.bar()
            return message, None, message, empty_fig, empty_fig, empty_fig, html.Div(), empty_fig, empty_fig, empty_fig

        # Enforce selected_date filter in-app as a safety net
        try:
            pre_rows = len(df)
            if 'ProcessingDate' in df.columns:
                df = df[df['ProcessingDate'] == selected_date].copy()
            post_rows = len(df)
            logger.info(f"Applied in-app date filter rows: {pre_rows} -> {post_rows} for {selected_date}")
        except Exception as e:
            logger.debug(f"In-app date filter skipped: {e}")

        if df.empty:
            logger.info(f"No data returned for env={environment}, date={selected_date}")
            message = html.Div([html.H4("No Data Available", className='text-center text-danger')])
            empty_fig = px.bar()
            return message, None, message, empty_fig, empty_fig, empty_fig, html.Div(), empty_fig, empty_fig, empty_fig
        
        # ... rest of function unchanged ...
        
        # Calculate job duration and format times for display - keep original datetime columns intact
        # Use direct assignment to avoid FutureWarning
        duration_mins = (pd.to_datetime(df['EndTime']) - pd.to_datetime(df['StartTime'])).dt.total_seconds() / 60
        df['Duration'] = duration_mins.round(2).astype(str) + ' mins'
        
        df['StartDate'] = pd.to_datetime(df['StartTime']).dt.strftime('%Y-%m-%d')
        df['StartTimeDisplay'] = pd.to_datetime(df['StartTime']).dt.strftime('%I:%M:%S %p')
        df['EndDate'] = pd.to_datetime(df['EndTime']).dt.strftime('%Y-%m-%d')
        df['EndTimeDisplay'] = pd.to_datetime(df['EndTime']).dt.strftime('%I:%M:%S %p')

        if not df_unlock_online.empty:
            df_unlock_online['CompletionTime'] = pd.to_datetime(df_unlock_online['CompletionTime']).dt.strftime('%I:%M:%S %p')

        filtered_df = df
        try:
            sample_dates = pd.to_datetime(filtered_df['StartTime']).dt.strftime('%Y-%m-%d').unique().tolist()[:5]
            logger.info(f"Final job table sample StartTime dates: {sample_dates}")
        except Exception:
            pass
    except Exception as e:
        logger.error(f"Unhandled error in update_dashboard: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        message = html.Div([html.H4("No Data Available", className='text-center text-danger')])
        empty_fig = px.bar()
        return message, None, message, empty_fig, empty_fig, empty_fig, html.Div(), empty_fig, empty_fig, empty_fig

    # Calculate job duration and format times for display - keep original datetime columns intact
    # Use direct assignment to avoid FutureWarning
    duration_mins = (pd.to_datetime(df['EndTime']) - pd.to_datetime(df['StartTime'])).dt.total_seconds() / 60
    df['Duration'] = duration_mins.round(2).astype(str) + ' mins'
    
    df['StartDate'] = pd.to_datetime(df['StartTime']).dt.strftime('%Y-%m-%d')
    df['StartTimeDisplay'] = pd.to_datetime(df['StartTime']).dt.strftime('%I:%M:%S %p')
    df['EndDate'] = pd.to_datetime(df['EndTime']).dt.strftime('%Y-%m-%d')
    df['EndTimeDisplay'] = pd.to_datetime(df['EndTime']).dt.strftime('%I:%M:%S %p')

    if not df_unlock_online.empty:
        df_unlock_online['CompletionTime'] = pd.to_datetime(df_unlock_online['CompletionTime']).dt.strftime('%I:%M:%S %p')

    filtered_df = df

    # Updated table headers to include Duration column
    job_table_header = [html.Thead(html.Tr([html.Th(col) for col in ['JobName', 'StartDate', 'StartTime', 'EndDate', 'EndTime', 'Duration', 'Status']], className='bg-primary text-white'))]
    job_table_body = [html.Tbody([html.Tr([html.Td(filtered_df.iloc[i][col]) for col in ['JobName', 'StartDate', 'StartTimeDisplay', 'EndDate', 'EndTimeDisplay', 'Duration', 'Status']]) for i in range(len(filtered_df))])]

    job_table = dbc.Table(job_table_header + job_table_body, striped=True, bordered=True, hover=True)

    if not df_unlock_online.empty:
        unlock_online_table_header = [html.Thead(html.Tr([html.Th(col) for col in ['JobName', 'CompletionTime', 'Status']], className='bg-primary text-white'))]
        unlock_online_table_body = [html.Tbody([html.Tr([html.Td(df_unlock_online.iloc[i][col]) for col in ['JobName', 'CompletionTime', 'Status']]) for i in range(len(df_unlock_online))])]
        unlock_online_table = dbc.Table(unlock_online_table_header + unlock_online_table_body, striped=True, bordered=True, hover=True, className='table-dark')
    else:
        unlock_online_table = html.Div([html.H4("No Unlock Online data available", className='text-center text-warning')])

    # MODIFICATION: Updated logic for failed jobs based on requirements
    failed_jobs = df[
        ((df['JobName'] != '20. Benchmark Update') & (df['Status'] == 'Failed')) |
        ((df['JobName'] == '20. Benchmark Update') & (df['Status'] == 'Succeeded with Exceptions'))
    ]
    
    if not failed_jobs.empty:
        # Create a styled card for failed jobs - smaller, left-aligned title, no warning icons
        failed_jobs_info = dbc.Card(
            dbc.CardBody([
                html.H4("Reason for Unlock Online Delay", 
                        className='card-title text-danger mb-3',
                        style={'font-weight': 'bold', 'border-bottom': '2px solid #dc3545', 'text-align': 'left', 'font-size': '18px'}),
                html.Div([
                    html.Div([
                        html.H5(f"{row['JobName']} - {row['Status']}", className='text-danger', style={'font-weight': 'bold', 'font-size': '16px'}),
                        html.P([
                            html.Strong("Error: "), 
                            html.Span(row['Message'] if pd.notna(row['Message']) else "No error message available", 
                                     style={'color': '#dc3545', 'font-size': '14px'})
                        ]),
                        html.P([
                            html.Strong("Failed at: "), 
                            html.Span(f"{row['EndDate']} {row['EndTime']}", style={'font-size': '14px'})
                        ]),
                    ], className='mb-2 p-2 border border-danger rounded', 
                       style={'background-color': 'rgba(220, 53, 69, 0.1)'})
                    for _, row in failed_jobs.iterrows()
                ]),
                # Add textbox for solution input
                html.Div([
                    html.H5("Solution/Fix Details:", className='mt-3', style={'font-size': '16px'}),
                    dbc.Textarea(
                        id='solution-textarea',
                        placeholder='Please enter the solution or fix that was applied...',
                        style={'width': '100%', 'height': '80px', 'margin-bottom': '10px', 'font-size': '14px'}
                    ),
                    html.Div([
                        dbc.Button("Save Solution", id="save-solution-button", color="primary", className="mr-2", size="sm")
                    ], className='d-flex justify-content-end')
                ])
            ]),
            className='mb-4 border border-danger',
            style={'box-shadow': '0 2px 4px rgba(220, 53, 69, 0.3)', 'background-color': '#fff9f9', 'max-width': '100%'}
        )
    else:
        # No failed jobs
        failed_jobs_info = None

    # MODIFICATION: Filter status data to exclude 20. Benchmark Update failed jobs and add hover information
    status_data = df.copy()
    # Remove 20. Benchmark Update with Failed status
    status_data = status_data[~((status_data['JobName'] == '20. Benchmark Update') & (status_data['Status'] == 'Failed'))]

    # Get grouped job names by status
    status_jobs = {}
    for status in status_data['Status'].unique():
        jobs_with_status = status_data[status_data['Status'] == status]['JobName'].unique().tolist()
        status_jobs[status] = ', '.join(jobs_with_status)

    # Create status counts
    status_counts = status_data['Status'].value_counts().reset_index()
    status_counts.columns = ['Status', 'Count']

    # Add the job names to the status counts dataframe
    status_counts['JobNames'] = status_counts['Status'].map(status_jobs)

    # Customize the bar graph for Job Status Counts with hover info
    fig_status = go.Figure(data=[
        go.Bar(
            x=status_counts['Count'],
            y=status_counts['Status'],
            orientation='h',
            marker=dict(
                color=status_counts['Status'].apply(lambda x: 'green' if x == 'Succeeded' else 'orange' if x == 'Succeeded with Exceptions' else 'red'),
                line=dict(color='black', width=1)  # Keep the border
            ),
            # Add custom hover template showing job names
            hovertemplate='<b>Status:</b> %{y}<br>' +
                        '<b>Count:</b> %{x}<br>' +
                        '<b>Jobs:</b> %{customdata}<extra></extra>',
            customdata=status_counts['JobNames'].tolist()
        )
    ])

    fig_status.update_layout(
        title='Job Status Counts',
        xaxis_title='Count',
        yaxis_title='Status',
        template='plotly_white',
        plot_bgcolor='rgba(229,236,246,1)',
        title_font=dict(size=21, family='Arial, bold', color='rgba(42, 63, 95, 1)'),
        xaxis=dict(
            showgrid=True,
            showline=False,
            linewidth=1,
            linecolor='black',
            mirror=True,
            gridcolor='lightgrey'
        ),
        yaxis=dict(
            showgrid=True,
            showline=False,
            linewidth=1,
            linecolor='black',
            mirror=True,
            gridcolor='lightgrey',
        ),
        font=dict(size=14),
        bargap=0.4,  # Adjust this value to reduce the height of the bars
        hoverlabel=dict(
            bgcolor="white",
            font_size=12,
            font_family="Arial"
        )
    )

    # Filter for "Succeeded with Exceptions" for Benchmark Update and "Failed" for other jobs
    if not df_50_days.empty:
        df_50_days['ProcessingDate'] = pd.to_datetime(df_50_days['ProcessingDate']).dt.strftime('%Y-%m-%d')
        df_50_days['DurationMinutes'] = (df_50_days['EndTime'] - df_50_days['StartTime']).dt.total_seconds() / 60.0

        # Apply criteria:
        # 1. For "20. Benchmark Update" job: Keep only "Succeeded with Exceptions".
        # 2. For all other jobs: Keep only "Failed".
        df_failed = df_50_days[
            ((df_50_days['JobName'] == '20. Benchmark Update') & (df_50_days['Status'] == 'Succeeded with Exceptions')) |
            ((df_50_days['JobName'] != '20. Benchmark Update') & (df_50_days['Status'] == 'Failed'))
        ]

        # Group the filtered data by relevant fields and calculate failure trend
        failure_trend = df_failed.groupby(['ProcessingDate', 'JobName', 'StartTime', 'Message']).size().reset_index(name='Count')

        # Plot Failure Trend graph with fixed bar width
        if not failure_trend.empty:
            fig_trend = px.bar(
                failure_trend,
                x='ProcessingDate',
                y='Count',
                color='JobName',
                title='Failure Trend Over the Last 50 Days',
                hover_data={'StartTime': True, 'JobName': True, 'Message': True}
            )
            
            # Fix for oversized bars in failure trend graph
            fig_trend.update_layout(
                bargap=0.2,           # Gap between bars of adjacent location coordinates
                bargroupgap=0.1,      # Gap between bars of the same location coordinates
                barmode='group',      # Group bars together
                xaxis=dict(
                    type='category',  # Treat x-axis as categorical
                    tickangle=-45     # Rotate x-axis labels for better readability
                ),
                uniformtext_minsize=8, 
                uniformtext_mode='hide'
            )
            
            # Set the width of bars to a reasonable value
            for trace in fig_trend.data:
                trace.width = 0.2     # Fixed width for all bars
        else:
            fig_trend = px.bar(title='No failure data available for the last 50 days')
    else:
        fig_trend = px.bar(title='No data available for failure trend analysis')

    # Time Difference between TRIAD and Benchmark Update jobs
    if not df_50_days.empty:
        triad_df = df_50_days[df_50_days['JobName'] == '18. TRIAD']
        benchmark_update_df = df_50_days[df_50_days['JobName'] == '20. Benchmark Update']

        if not triad_df.empty and not benchmark_update_df.empty:
            merged_df = pd.merge(triad_df, benchmark_update_df, on='ProcessingDate', suffixes=('_TRIAD', '_Benchmark'))
            merged_df['TimeDifference'] = (merged_df['EndTime_Benchmark'] - merged_df['EndTime_TRIAD']).dt.total_seconds() / 3600
            merged_df['ProcessingDate'] = pd.to_datetime(merged_df['StartTime_TRIAD']).dt.strftime('%Y-%m-%d')
            merged_df = merged_df.sort_values('ProcessingDate', ascending=True)  # Sort in ascending order

            last_10_days_df = merged_df.drop_duplicates(subset=['ProcessingDate']).tail(10)

            if selected_date not in last_10_days_df['ProcessingDate'].values:
                selected_date_row = merged_df[merged_df['ProcessingDate'] == selected_date].head(1)
                last_10_days_df = pd.concat([selected_date_row, last_10_days_df]).drop_duplicates(subset=['ProcessingDate']).tail(10)

            table_rows = []
            for index, row in last_10_days_df.iterrows():
                row_class = 'table-success' if row['ProcessingDate'] == selected_date else ''
                table_rows.append(html.Tr([
                    html.Td(row['ProcessingDate']),
                    html.Td(f"{row['TimeDifference']:.2f} hours")
                ], className=row_class))

            time_difference_table = dbc.Table([
                html.Thead(html.Tr([html.Th("Processing Date"), html.Th("Time Difference (hours)")]), className='bg-primary text-white'),
                html.Tbody(table_rows)
            ], bordered=True, striped=True, hover=True)

            fig_time_diff = go.Figure()
            fig_time_diff.add_trace(go.Scatter(
                x=merged_df['ProcessingDate'],
                y=merged_df['TimeDifference'],
                mode='lines+markers',
                name='Time Difference',
                line=dict(color='blue'),
                marker=dict(size=8)
            ))
            fig_time_diff.update_layout(
                title='Sourcing Job Runtime Over the Last 50 Days',
                xaxis_title='Processing Date',
                yaxis_title='Time Difference (hours)',
                hovermode='x unified',
                xaxis=dict(
                    type='category',
                    tickformat='%Y-%m-%d'
                ),
                yaxis=dict(
                    rangemode='tozero'
                ),
                legend=dict(title="Metrics", orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
            )
        else:
            time_difference_table = dbc.Table([
                html.Thead(html.Tr([html.Th("Processing Date"), html.Th("Time Difference (hours)")]), className='bg-primary text-white'),
                html.Tbody([
                    html.Tr([html.Td("No Data"), html.Td("No Data")])
                ])
            ], bordered=True, striped=True, hover=True)
            fig_time_diff = px.line(title='No data available for TRIAD or Benchmark Update jobs.')
    else:
        time_difference_table = dbc.Table([
            html.Thead(html.Tr([html.Th("Processing Date"), html.Th("Time Difference (hours)")]), className='bg-primary text-white'),
            html.Tbody([
                html.Tr([html.Td("No Data"), html.Td("No Data")])
            ])
        ], bordered=True, striped=True, hover=True)
        fig_time_diff = px.line(title='No data available for time difference analysis.')

    # Create Job Duration graph (only for the Job Duration Analysis tab)
    if not df_job_duration.empty:
        avg_duration = df_job_duration.groupby(['ProcessingDate', 'JobName'])['DurationMinutes'].mean().reset_index()
        fig_job_duration = px.line(avg_duration, x='ProcessingDate', y='DurationMinutes', color='JobName', title='Average Job Duration Over Time')
    else:
        fig_job_duration = px.line(title='No job duration data available')

    # Performance Metrics functionality removed

    # Create Anomaly Detection graph (only for the Anomaly Detection tab)
    if not df_50_days.empty:
        logger.debug("Creating enhanced anomaly detection with expected completion times")
            
        # Filter out "12. Aging Calculations" job from the anomaly detection data
        df_50_days_filtered = df_50_days[df_50_days['JobName'] != '12. Aging Calculations']
            
        if not df_50_days_filtered.empty and df_50_days_filtered['DurationMinutes'].std() > 0:
                # Calculate expected completion times (mean duration per job)
                job_expected_durations = df_50_days_filtered.groupby('JobName')['DurationMinutes'].agg([
                    ('ExpectedDuration', 'mean'),
                    ('MedianDuration', 'median'),
                    ('StdDuration', 'std'),
                    ('MinDuration', 'min'),
                    ('MaxDuration', 'max'),
                    ('JobCount', 'count')
                ]).reset_index()
                
                # Merge expected durations back to the main dataframe
                df_50_days_enhanced = df_50_days_filtered.merge(job_expected_durations, on='JobName', how='left')
                
                # Calculate Z-scores based on job-specific statistics
                df_50_days_enhanced['DurationZScore'] = (
                    df_50_days_enhanced['DurationMinutes'] - df_50_days_enhanced['ExpectedDuration']
                ) / df_50_days_enhanced['StdDuration'].fillna(1)  # Avoid division by zero
                
                # Identify anomalies (Z-score > 2 or < -2)
                anomalies = df_50_days_enhanced[df_50_days_enhanced['DurationZScore'].abs() > 2].copy()
                
                if not anomalies.empty:
                    # Add additional calculated fields for better insights
                    anomalies['DeviationMinutes'] = anomalies['DurationMinutes'] - anomalies['ExpectedDuration']
                    anomalies['DeviationPercent'] = (anomalies['DeviationMinutes'] / anomalies['ExpectedDuration'] * 100).round(1)
                    anomalies['AnomalyType'] = anomalies['DurationZScore'].apply(
                        lambda x: 'Much Slower' if x > 3 else 'Slower' if x > 2 else 'Much Faster' if x < -3 else 'Faster'
                    )
                    
                    # Format times for display
                    anomalies['StartTimeFormatted'] = pd.to_datetime(anomalies['StartTime']).dt.strftime('%Y-%m-%d %H:%M')
                    anomalies['ProcessingDateFormatted'] = anomalies['ProcessingDate'].astype(str)
                    
                    # Create enhanced scatter plot
                    fig_anomaly_detection = go.Figure()
                    
                    # Color mapping for anomaly types
                    anomaly_colors = {
                        'Much Slower': '#dc3545',    # Red
                        'Slower': '#fd7e14',         # Orange  
                        'Faster': '#17a2b8',        # Teal
                        'Much Faster': '#6f42c1'    # Purple
                    }
                    
                    # Add scatter points for each anomaly type
                    for anomaly_type in ['Much Slower', 'Slower', 'Faster', 'Much Faster']:
                        type_data = anomalies[anomalies['AnomalyType'] == anomaly_type]
                        if not type_data.empty:
                            fig_anomaly_detection.add_trace(go.Scatter(
                                x=type_data['StartTime'],
                                y=type_data['DurationMinutes'],
                                mode='markers',
                                name=f'{anomaly_type} ({len(type_data)})',
                                marker=dict(
                                    size=14,
                                    color=anomaly_colors[anomaly_type],
                                    symbol='circle',
                                    line=dict(width=2, color='white'),
                                    opacity=0.8
                                ),
                                hovertemplate=(
                                    '<b>%{customdata[0]}</b><br>'
                                    '<b>Date:</b> %{customdata[1]}<br>'
                                    '<b>Start Time:</b> %{customdata[2]}<br>'
                                    '<b>Actual Duration:</b> %{y:.1f} minutes<br>'
                                    '<b>Expected Duration:</b> %{customdata[3]:.1f} minutes<br>'
                                    '<b>Deviation:</b> %{customdata[4]:+.1f} minutes (%{customdata[5]:+.1f}%)<br>'
                                    '<b>Anomaly Type:</b> %{customdata[6]}<br>'
                                    '<b>Z-Score:</b> %{customdata[7]:.2f}<br>'
                                    '<b>Job Runs (50 days):</b> %{customdata[8]}<extra></extra>'
                                ),
                                customdata=type_data[[
                                    'JobName', 'ProcessingDateFormatted', 'StartTimeFormatted', 'ExpectedDuration',
                                    'DeviationMinutes', 'DeviationPercent', 'AnomalyType', 'DurationZScore', 'JobCount'
                                ]].values
                            ))
                    
                    # Add reference lines for expected durations (without job name annotations)
                    for job_name in anomalies['JobName'].unique():
                        job_data = anomalies[anomalies['JobName'] == job_name]
                        expected_duration = job_data['ExpectedDuration'].iloc[0]
                        
                        # Add horizontal line for expected duration (no text annotation)
                        fig_anomaly_detection.add_hline(
                            y=expected_duration,
                            line_dash="dot",
                            line_color="gray",
                            opacity=0.3
                        )
                    
                    # Enhanced layout
                    fig_anomaly_detection.update_layout(
                        title={
                            'text': 'Job Duration Anomaly Detection with Expected Completion Times',
                            'x': 0.5,
                            'xanchor': 'center',
                            'font': {'size': 16, 'color': '#2A3F5F'}
                        },
                        xaxis_title='Job Start Time',
                        yaxis_title='Duration (minutes)',
                        template="plotly_white",
                        hovermode='closest',
                        legend=dict(
                            orientation='v',
                            yanchor='top',
                            y=1,
                            xanchor='left',
                            x=1.02,
                            bgcolor='rgba(255,255,255,0.8)',
                            bordercolor='gray',
                            borderwidth=1
                        ),
                        margin=dict(l=60, r=150, t=80, b=60),
                        plot_bgcolor='rgba(248,249,250,1)'
                    )
                    
                    # Add summary annotation
                    total_anomalies = len(anomalies)
                    slower_count = len(anomalies[anomalies['DurationZScore'] > 2])
                    faster_count = len(anomalies[anomalies['DurationZScore'] < -2])
                    
                    fig_anomaly_detection.add_annotation(
                        text=(
                            f"<b>Anomaly Summary:</b><br>"
                            f"• Total Anomalies: {total_anomalies}<br>"
                            f"• Slower than Expected: {slower_count}<br>"
                            f"• Faster than Expected: {faster_count}<br>"
                            f"• Analysis Period: 50 days"
                        ),
                        xref="paper", yref="paper",
                        x=0.02, y=0.98,
                        xanchor='left', yanchor='top',
                        showarrow=False,
                        font=dict(size=10, color="#2A3F5F"),
                        bgcolor="rgba(255,255,255,0.9)",
                        bordercolor="gray",
                        borderwidth=1
                    )
                    
                    logger.info(f"Anomaly detection completed: {total_anomalies} anomalies found")
                    
                else:
                    fig_anomaly_detection = go.Figure()
                    fig_anomaly_detection.add_annotation(
                        text="No anomalies detected in job durations",
                        xref="paper", yref="paper",
                        x=0.5, y=0.5, xanchor='center', yanchor='middle',
                        showarrow=False,
                        font=dict(size=16, color="green")
                    )
                    fig_anomaly_detection.update_layout(
                        title="Job Duration Anomaly Detection - No Anomalies Found",
                        template="plotly_white"
                    )
                    
        
    else:
        fig_anomaly_detection = go.Figure()
        fig_anomaly_detection.add_annotation(
            text="No data available for anomaly detection",
            xref="paper", yref="paper",
            x=0.5, y=0.5, xanchor='center', yanchor='middle',
            showarrow=False,
            font=dict(size=16, color="gray")
        )
        fig_anomaly_detection.update_layout(
            title="Anomaly Detection - No Data Available",
            template="plotly_white"
        )
    
    # IMPROVED Time to Recovery Calculation
    if not df_50_days.empty:
        try:
            logger.debug("Starting time to recovery calculation")
            
            # Prepare data for recovery analysis
            df_recovery = df_50_days.copy()
            df_recovery = df_recovery.sort_values(['ProcessingDate', 'StartTime'])
            
            # Add next job information using vectorized operations
            df_recovery['NextJobStartTime'] = df_recovery.groupby('ProcessingDate')['StartTime'].shift(-1)
            df_recovery['NextJobName'] = df_recovery.groupby('ProcessingDate')['JobName'].shift(-1)
            df_recovery['NextJobEndTime'] = df_recovery.groupby('ProcessingDate')['EndTime'].shift(-1)
            
            # Calculate time gaps in minutes
            df_recovery['TimeGapMinutes'] = (
                df_recovery['NextJobStartTime'] - df_recovery['EndTime']
            ).dt.total_seconds() / 60.0
            
            # Define recovery scenarios with improved logic
            recovery_conditions = (
                # Scenario 1: Job explicitly failed (but exclude 20. Benchmark Update failures - they are valid)
                ((df_recovery['Status'] == 'Failed') & 
                 (df_recovery['JobName'] != '20. Benchmark Update')) |
                # Scenario 2: Succeeded with Exceptions for Benchmark Update (treat as failure)
                ((df_recovery['JobName'] == '20. Benchmark Update') & 
                 (df_recovery['Status'] == 'Succeeded with Exceptions')) |
                # Scenario 3: Unusual gap (>5 minutes) between successful jobs
                ((df_recovery['Status'] == 'Succeeded') & 
                 (df_recovery['TimeGapMinutes'] > 5) & 
                 (df_recovery['TimeGapMinutes'] < 1440))  # Less than 24 hours to avoid day boundaries
            )
            
            # Filter for recovery events
            recovery_events = df_recovery[
                recovery_conditions & 
                df_recovery['NextJobStartTime'].notna() &
                (~df_recovery['JobName'].isin(['13. Cleanup DB', '18. TRIAD'])) &  # Exclude cleanup jobs and TRIAD
                (~((df_recovery['JobName'] == '18. TRIAD') & (df_recovery['NextJobName'] == '20. Benchmark Update')))  # Exclude TRIAD->Benchmark gaps
            ].copy()
            
            if not recovery_events.empty:
                # Add additional calculated fields
                recovery_events['FailureType'] = recovery_events.apply(lambda row: 
                    'Explicit Failure' if (row['Status'] == 'Failed' and row['JobName'] != '20. Benchmark Update')
                    else 'Benchmark Exception' if (row['JobName'] == '20. Benchmark Update' and row['Status'] == 'Succeeded with Exceptions')
                    else 'Unusual Gap', axis=1
                )
                
                recovery_events['Severity'] = recovery_events['TimeGapMinutes'].apply(lambda x:
                    'Critical' if x > 60 else 'High' if x > 30 else 'Medium' if x > 10 else 'Low'
                )
                
                # Format datetime fields for display
                recovery_events['FailedJobEndTimeFormatted'] = recovery_events['EndTime'].dt.strftime('%Y-%m-%d %H:%M:%S')
                recovery_events['NextJobStartTimeFormatted'] = recovery_events['NextJobStartTime'].dt.strftime('%Y-%m-%d %H:%M:%S')
                recovery_events['ProcessingDateFormatted'] = recovery_events['ProcessingDate'].astype(str)
                
                # Create enhanced visualization
                fig_time_recovery = go.Figure()

                # Color mapping for severity
                severity_colors = {
                    'Critical': '#dc3545',  # Red
                    'High': '#fd7e14',      # Orange
                    'Medium': '#ffc107',    # Yellow
                    'Low': '#28a745'        # Green
                }
                
                # Add main scatter plot with color coding by severity
                for severity in ['Critical', 'High', 'Medium', 'Low']:
                    severity_data = recovery_events[recovery_events['Severity'] == severity]
                    if not severity_data.empty:
                        fig_time_recovery.add_trace(go.Scatter(
                            x=severity_data['EndTime'],
                            y=severity_data['TimeGapMinutes'],
                            mode='markers',
                            name=f'{severity} Recovery',
                            marker=dict(
                                size=12,
                                color=severity_colors[severity],
                                symbol='circle',
                                line=dict(width=2, color='white')
                            ),
                            hovertemplate=(
                                '<b>Job:</b> %{customdata[0]}<br>'
                                '<b>Status:</b> %{customdata[1]}<br>'
                                '<b>Failure Type:</b> %{customdata[2]}<br>'
                                '<b>End Time:</b> %{customdata[3]}<br>'
                                '<b>Next Job:</b> %{customdata[4]}<br>'
                                '<b>Next Start:</b> %{customdata[5]}<br>'
                                '<b>Recovery Time:</b> %{y:.1f} minutes<br>'
                                '<b>Severity:</b> %{customdata[6]}<br>'
                                '<b>Date:</b> %{customdata[7]}<extra></extra>'
                            ),
                            customdata=severity_data[[
                                'JobName', 'Status', 'FailureType', 'FailedJobEndTimeFormatted',
                                'NextJobName', 'NextJobStartTimeFormatted', 'Severity', 'ProcessingDateFormatted'
                            ]].values
                        ))
                
                # Trend line removed - was connecting different job types and creating confusion
                
                # Add threshold lines for reference
                fig_time_recovery.add_hline(
                    y=5, line_dash="dot", line_color="gray",
                    annotation_text="Normal Threshold (5 min)",
                    annotation_position="bottom right"
                )
                
                fig_time_recovery.add_hline(
                    y=30, line_dash="dot", line_color="orange",
                    annotation_text="High Impact (30 min)",
                    annotation_position="top right"
                )
                
                # Enhanced layout
                fig_time_recovery.update_layout(
                    title={
                        'text': 'Job Recovery Time Analysis - Last 50 Days',
                        'x': 0.5,
                        'xanchor': 'center',
                        'font': {'size': 18, 'color': '#2A3F5F'}
                    },
                    xaxis_title='Job End Time',
                    yaxis_title='Recovery Time (minutes)',
                    template="plotly_white",
                    hovermode='closest',
                    xaxis=dict(
                        type='date',
                        tickformat='%m/%d %H:%M',
                        showgrid=True,
                        gridcolor='lightgray',
                        tickangle=-45,
                        title_standoff=25
                    ),
                    yaxis=dict(
                        showgrid=True,
                        gridcolor='lightgray',
                        rangemode='tozero',
                        title_standoff=15
                    ),
                    legend=dict(
                        orientation='v',
                        yanchor='top',
                        y=1,
                        xanchor='left',
                        x=1.02,
                        bgcolor='rgba(255,255,255,0.8)',
                        bordercolor='gray',
                        borderwidth=1
                    ),
                    margin=dict(l=60, r=120, t=80, b=100),
                    hoverlabel=dict(
                        bgcolor="white",
                        font_size=11,
                        font_family="Arial",
                        bordercolor='gray'
                    ),
                    plot_bgcolor='rgba(248,249,250,1)'
                )
                
                logger.info(f"Recovery analysis completed: {len(recovery_events)} recovery events found")
                
            else:
                fig_time_recovery = go.Figure()
                fig_time_recovery.add_annotation(
                    text="No recovery events detected in the last 50 days",
                    xref="paper", yref="paper",
                    x=0.5, y=0.5, xanchor='center', yanchor='middle',
                    showarrow=False,
                    font=dict(size=16, color="gray")
                )
                fig_time_recovery.update_layout(
                    title="Job Recovery Time Analysis - No Data",
                    xaxis=dict(showgrid=False, showticklabels=False),
                    yaxis=dict(showgrid=False, showticklabels=False),
                    template="plotly_white"
                )
                
        except Exception as e:
            logger.error(f"Error in recovery time calculation: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            fig_time_recovery = go.Figure()
            fig_time_recovery.add_annotation(
                text=f"Error calculating recovery times: {str(e)}",
                xref="paper", yref="paper",
                x=0.5, y=0.5, xanchor='center', yanchor='middle',
                showarrow=False,
                font=dict(size=14, color="red")
            )
            fig_time_recovery.update_layout(
                title="Job Recovery Time Analysis - Error",
                template="plotly_white"
            )
    else:
        fig_time_recovery = go.Figure()
        fig_time_recovery.add_annotation(
            text="No data available for recovery time analysis",
            xref="paper", yref="paper",
            x=0.5, y=0.5, xanchor='center', yanchor='middle',
            showarrow=False,
            font=dict(size=16, color="gray")
        )
        fig_time_recovery.update_layout(
            title="Job Recovery Time Analysis - No Data Available",
            template="plotly_white"
        )

    return (unlock_online_table, failed_jobs_info, job_table, fig_status, fig_trend, fig_time_diff, time_difference_table, 
            fig_job_duration, fig_anomaly_detection, fig_time_recovery)

# Store solution text and email data
app.solution_text = ""
app.email_data = {}

# Callback for saving solution text
@app.callback(
    Output('save-solution-button', 'children'),
    [Input('save-solution-button', 'n_clicks')],
    [State('solution-textarea', 'value')]
)
def save_solution(n_clicks, solution_text):
    if n_clicks and solution_text:
        app.solution_text = solution_text
        return "✓ Saved"
    return "Save Solution"

# FIXED VERSION: Email callback that doesn't rely on solution-textarea
@app.callback(
    [Output('send-email-button', 'n_clicks'), 
     Output('confirm-dialog', 'displayed'),
     Output('email-preview-modal', 'is_open')],
    [Input('send-email-button', 'n_clicks'),
     Input('send-email-confirm', 'n_clicks'),
     Input('send-email-cancel', 'n_clicks')],
    [State('date-picker-table', 'date'),
     State('environment-selector', 'value')]
)
def handle_send_email(n_clicks, confirm_clicks, cancel_clicks, selected_date, environment):
    # Identify which button triggered the callback
    ctx = dash.callback_context
    
    if not ctx.triggered:
        return dash.no_update, False, False
    
    button_id = ctx.triggered[0]['prop_id'].split('.')[0]
    
    if button_id == 'send-email-button' and n_clicks and n_clicks > 0:
        try:
            # Fetch current data for the selected date to get failed jobs
            df, _, _, _ = fetch_data(selected_date, environment)
            if df is None:
                logger.warning("Email preparation: fetch_data returned None; aborting email preview")
                return n_clicks, False, False
            
            # Format date and time for display - FIXED DataFrame warnings
            # Use direct assignment to avoid FutureWarning
            duration_mins = (pd.to_datetime(df['EndTime']) - pd.to_datetime(df['StartTime'])).dt.total_seconds() / 60
            df['Duration'] = duration_mins.round(2).astype(str) + ' mins'
            
            df['StartDate'] = pd.to_datetime(df['StartTime']).dt.strftime('%Y-%m-%d')
            df['StartTime'] = pd.to_datetime(df['StartTime']).dt.strftime('%I:%M:%S %p')
            df['EndDate'] = pd.to_datetime(df['EndTime']).dt.strftime('%Y-%m-%d')
            df['EndTime'] = pd.to_datetime(df['EndTime']).dt.strftime('%I:%M:%S %p')
            
            # Get failed jobs with updated criteria
            failed_jobs = df[
                ((df['JobName'] != '20. Benchmark Update') & (df['Status'] == 'Failed')) |
                ((df['JobName'] == '20. Benchmark Update') & (df['Status'] == 'Succeeded with Exceptions'))
            ]
            
            # Get the solution text if available (using app.solution_text instead of component)
            solution_text = app.solution_text if hasattr(app, 'solution_text') else ""
            
            # Capture screenshot of just the main dashboard tab
            logger.info(f"Preparing email preview for date={selected_date}, env={environment}")
            image_path = capture_main_dashboard(selected_date, environment)
            
            # Get the benchmark end time
            benchmark_end_time = df[df['JobName'] == '20. Benchmark Update']['EndTime'].max()
            
            # Format the benchmark end time
            if pd.notnull(benchmark_end_time):
                benchmark_end_time_formatted = pd.to_datetime(benchmark_end_time).strftime('%I:%M %p')
            else:
                benchmark_end_time_formatted = "N/A"
            
            # Store data for email sending
            app.email_data = {
                'image_path': image_path,
                'processing_date': selected_date,
                'environment': environment,
                'benchmark_end_time_formatted': benchmark_end_time_formatted,
                'failed_jobs': failed_jobs,
                'solution_text': solution_text
            }
            
            # Open email preview modal
            return n_clicks, False, True
            
        except Exception as e:
            print(f"Error preparing email: {str(e)}")
            return n_clicks, False, False
    
    elif button_id == 'send-email-confirm' and confirm_clicks and confirm_clicks > 0:
        try:
            # Get stored email data
            data = app.email_data
            if data:
                # Prepare Outlook email object
                mail = send_email_with_screenshot(
                    data['image_path'], 
                    data['processing_date'],
                    data.get('environment', 'PROD'), 
                    data['benchmark_end_time_formatted'], 
                    data['failed_jobs'],
                    data.get('solution_text', "")
                )
                
                # Send the email
                mail.Send()
                
                # Clean up
                app.email_data = {}
                
                return None, True, False
            return n_clicks, False, False
        except Exception as e:
            print(f"Error sending email: {str(e)}")
            return n_clicks, False, False
    
    elif button_id == 'send-email-cancel' and cancel_clicks and cancel_clicks > 0:
        # Clean up if cancel is clicked
        app.email_data = {}
        return n_clicks, False, False
            
    return dash.no_update, False, False

# Simplified function to run the Dash app - avoiding multiprocessing issues
def run_dash_server_directly():
    """Run Dash app directly in the main process to avoid multiprocessing issues"""
    try:
        logger.info("Starting Dash server directly...")
        
        # Check if port is available
        if not check_port_available(8050):
            logger.error("Port 8050 is already in use")
            return False
        
        logger.info("Port 8050 is available")
        logger.info("Starting Dash server...")
        
        # Start the server in a separate thread to avoid blocking
        def start_server():
            try:
                app.run(
                    debug=False, 
                    port=8050, 
                    use_reloader=False,
                    host='127.0.0.1',
                    dev_tools_ui=False,
                    dev_tools_props_check=False,
                    threaded=True
                )
            except Exception as e:
                logger.error(f"Error starting server: {e}")
        
        # Start server in background thread
        server_thread = threading.Thread(target=start_server, daemon=True)
        server_thread.start()
        
        logger.info("Server thread started")
        return True
        
    except Exception as e:
        logger.error(f"Error in run_dash_server_directly: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return False

# Function to capture main dashboard screenshot using Selenium
def capture_main_dashboard(selected_date, environment='PROD', output_path=None):
    """
    Minimalist approach to capture the dashboard without the empty space
    
    Parameters:
    - selected_date: Date to use for the dashboard
    - output_path: Path to save the screenshot (default: user directory)
    
    Returns:
    - Path to the saved screenshot
    """
    if output_path is None:
        output_path = os.path.join(get_output_directory(), "dashboard.png")
    
    # Create directory if it doesn't exist
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    # Configure Edge options
    edge_options = EdgeOptions()
    edge_options.add_argument("--headless=new")
    edge_options.add_argument("--disable-gpu")
    edge_options.add_argument("--no-sandbox")
    edge_options.add_argument("--disable-dev-shm-usage")
    edge_options.add_argument("--disable-software-rasterizer")
    edge_options.add_argument("--disable-extensions")
    edge_options.add_argument("--disable-logging")
    edge_options.add_argument("--log-level=3")
    edge_options.add_argument("--window-size=1920,1080")  # Standard HD viewport
    # Suppress GPU errors
    edge_options.add_experimental_option('excludeSwitches', ['enable-logging'])
    
    # Initialize the driver using Selenium Manager (automatic driver management)
    # No need to specify executable_path - Selenium Manager handles it automatically
    try:
        driver = webdriver.Edge(options=edge_options)
        print("Edge WebDriver initialized successfully using Selenium Manager")
    except Exception as e:
        print(f"Error initializing Edge WebDriver: {str(e)}")
        raise
    
    try:
        # Open the dashboard with env and date via query params to drive state
        query = urllib.parse.urlencode({
            'env': environment,
            'date': selected_date
        })
        driver.get(f"http://127.0.0.1:8050/?{query}")
        
        # Wait for the page to load completely
        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.ID, "date-picker-table"))
        )
        
        # Clear any prior Dash persistence to avoid PROD default overriding query
        try:
            driver.execute_script("try{ window.sessionStorage.removeItem('_dash_persistence'); }catch(e){}")
        except Exception:
            pass

        # Click on main dashboard tab
        WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.ID, "tab-main-dashboard"))
        ).click()
        
        # Wait for data to load
        time.sleep(12)
        
        # Remove the send email button row before screenshot
        driver.execute_script("""
            var sendBtn = document.getElementById('send-email-row');
            if (sendBtn) sendBtn.remove();
        """)
        
        # Wait for changes to apply
        time.sleep(1)
        
        # METHOD 1: Capture only the main dashboard tab content (RECOMMENDED)
        try:
            # Find the main dashboard tab content
            dashboard_element = driver.find_element(By.ID, "tab-main-dashboard")
            
            # Screenshot only this element
            dashboard_element.screenshot(output_path)
            print(f"Dashboard screenshot saved to {output_path} (element capture)")
            return output_path
            
        except Exception as e:
            print(f"Element screenshot failed: {str(e)}, falling back to full page")
            # Fallback to full page screenshot
            driver.save_screenshot(output_path)
            print(f"Dashboard screenshot saved to {output_path} (full page fallback)")
            return output_path
        
    except Exception as e:
        print(f"Error capturing screenshot: {str(e)}")
        # Simple fallback
        try:
            driver.save_screenshot(output_path)
            return output_path
        except:
            print("Could not save screenshot even with fallback")
            return None
    finally:
        driver.quit()

def capture_dashboard_html(selected_date, environment='PROD'):
    """
    Capture the dashboard HTML content for embedding in email
    
    Parameters:
    - selected_date: Date to use for the dashboard
    - environment: Environment to use (PROD, IT, QV)
    
    Returns:
    - HTML string with inlined styles
    """
    # Configure Edge options
    edge_options = EdgeOptions()
    edge_options.add_argument("--headless=new")
    edge_options.add_argument("--disable-gpu")
    edge_options.add_argument("--no-sandbox")
    edge_options.add_argument("--disable-dev-shm-usage")
    edge_options.add_argument("--disable-software-rasterizer")
    edge_options.add_argument("--disable-extensions")
    edge_options.add_argument("--disable-logging")
    edge_options.add_argument("--log-level=3")
    edge_options.add_argument("--window-size=1920,1080")
    # Suppress GPU errors
    edge_options.add_experimental_option('excludeSwitches', ['enable-logging'])
    
    # Initialize the driver using Selenium Manager (automatic driver management)
    # No need to specify executable_path - Selenium Manager handles it automatically
    try:
        driver = webdriver.Edge(options=edge_options)
        print("Edge WebDriver initialized successfully using Selenium Manager")
    except Exception as e:
        print(f"Error initializing Edge WebDriver: {str(e)}")
        return None
    
    try:
        # Open the dashboard
        query = urllib.parse.urlencode({
            'env': environment,
            'date': selected_date
        })
        url = f"http://127.0.0.1:8050/?{query}"
        print(f"Opening dashboard URL: {url}")
        driver.get(url)
        print("Page load initiated")
        
        # Wait for the page to load completely
        print("Waiting for date picker element...")
        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.ID, "date-picker-table"))
        )
        print("Date picker found - page loaded")
        
        # Wait a bit more for Dash to fully initialize
        print("Waiting 3 seconds for Dash to initialize...")
        time.sleep(3)
        print("Dash initialization wait complete")
        
        # Click on main dashboard tab using JavaScript (more reliable than Selenium click)
        try:
            print("Attempting to click main dashboard tab...")
            # Find the tab by text content
            tab_element = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, "//a[contains(text(), 'Main Dashboard')]"))
            )
            tab_element.click()
            print("Main dashboard tab clicked via Selenium")
            
            # Also try JS click to be sure
            driver.execute_script("arguments[0].click();", tab_element)
            print("Main dashboard tab clicked via JS")
            
        except Exception as tab_error:
            print(f"Warning: Could not click tab: {str(tab_error)}")
            # Try finding it via class if text fails
            try:
                driver.execute_script("""
                    var tabs = document.querySelectorAll('.nav-link');
                    for (var i = 0; i < tabs.length; i++) {
                        if (tabs[i].innerText.includes('Main Dashboard')) {
                            tabs[i].click();
                            console.log('Clicked tab via JS loop');
                            break;
                        }
                    }
                """)
            except:
                pass
            # Continue anyway - the content might still be visible
        
        # Wait for data to load (increased from 12 to 15 seconds)
        print("Waiting 15 seconds for dashboard data to load...")
        time.sleep(15)
        print("Data load wait complete")
        
        # Wait for actual dashboard content to be present (graphs, tables, etc.)
        try:
            print("Waiting for dashboard content to render (status-bar-graph)...")
            # Wait for a specific element inside the Main Dashboard tab
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.ID, "status-bar-graph"))
            )
            print("Dashboard content detected - status-bar-graph found")
        except Exception as content_wait_error:
            print(f"Warning: Timeout waiting for dashboard content: {str(content_wait_error)}")
            print("Checking if any content exists anyway...")
        
        # Additional wait to ensure everything is rendered
        print("Waiting 5 more seconds for full render...")
        time.sleep(5)
        print("Full render wait complete")
        
        # Remove unwanted elements
        print("Removing unwanted elements...")
        driver.execute_script("""
            // Remove send email button
            var sendBtn = document.getElementById('send-email-row');
            if (sendBtn) {
                sendBtn.remove();
                console.log('Send button removed');
            }
            
            // Remove other tabs (keep only main dashboard)
            // We can't easily remove other tabs if we don't know their IDs, 
            // but we can hide the nav bar itself
            var navTabs = document.querySelector('.nav-tabs');
            if (navTabs) {
                navTabs.style.display = 'none';
            }
            
            // Remove date picker and environment selector container
            // It's usually the first row
            var firstRow = document.querySelector('.container-fluid > .row:first-child');
            if (firstRow) {
                firstRow.style.display = 'none';
            }
        """)
        print("Unwanted elements removed")
        
        time.sleep(1)
        
        # Get the HTML content of the main dashboard
        try:
            print("Attempting to capture dashboard HTML...")
            # Capture the tab-content div which contains the active tab pane
            dashboard_html = driver.execute_script("""
                var content = document.querySelector('.tab-content');
                if (!content) {
                    console.error('Tab content container not found');
                    // Fallback to main container
                    var container = document.querySelector('.container-fluid');
                    return container ? container.outerHTML : '';
                }
                
                // Check if it has content
                if (content.innerHTML.trim() === '') {
                    console.error('Tab content is empty');
                    // Try to return the whole body for debugging if empty
                    return document.body.outerHTML;
                }
                
                return content.outerHTML;
            """)
            
            print(f"JavaScript execution complete. HTML length: {len(dashboard_html) if dashboard_html else 0}")
            
            if not dashboard_html or dashboard_html.strip() == '':
                print("WARNING: Dashboard HTML is empty")
                # Try to get page source for debugging
                page_source = driver.page_source
                print(f"Page source length: {len(page_source)}")
                return page_source # Return full page source as fallback
            
            return dashboard_html
            
        except Exception as script_error:
            print(f"Error executing JavaScript to capture HTML: {str(script_error)}")
            import traceback
            print(traceback.format_exc())
            return None
        
    except Exception as e:
        print(f"Error capturing dashboard HTML: {str(e)}")
        import traceback
        print(traceback.format_exc())
        return None
    finally:
        try:
            driver.quit()
        except Exception:
            pass


def send_email_with_screenshot(image_path, processing_date, environment, benchmark_end_time_formatted, failed_jobs=None, solution_text=None):
    """
    Send an email with the dashboard HTML content embedded
    
    Parameters:
    - image_path: (UNUSED - kept for backward compatibility)
    - processing_date: Date string for the email
    - environment: Environment (PROD, IT, QV)
    - benchmark_end_time_formatted: Formatted time string for the email
    - failed_jobs: DataFrame containing information about failed jobs (optional)
    - solution_text: Text describing the solution/fix applied (optional)
    
    Note: This function now only uses HTML capture. Screenshot functionality has been removed.
    """
    # Create Outlook email
    outlook = win32.Dispatch('outlook.application')
    mail = outlook.CreateItem(0)
    # Use recipients from CONFIG
    try:
        recipients = CONFIG.get('email', {}).get('to', [])
        cc_list = CONFIG.get('email', {}).get('cc', [])
        if isinstance(recipients, list):
            mail.To = ";".join(recipients)
        else:
            mail.To = str(recipients)
        if cc_list:
            mail.CC = ";".join(cc_list) if isinstance(cc_list, list) else str(cc_list)
    except Exception:
        mail.To = 'Pratik_Bhongade@Keybank.com;karen.a.tiemann-wozniak@key.com'
    mail.Subject = f'AspireVision Dashboard - {processing_date} - {environment}'
    
    # Create highlights section with failed job information if available
    highlights_html = (
        f"<li><strong>Environment:</strong> {environment}</li>"
        f"<li>Aspire Online Availability at <strong>{benchmark_end_time_formatted}</strong></li>"
    )
    
    # Add Reason for Unlock Online Delay in highlights if there are failed jobs
    if failed_jobs is not None and not failed_jobs.empty:
        for index, job in failed_jobs.iterrows():
            error_msg = job['Message'] if pd.notna(job['Message']) else "No error message available"
            status_text = "failed" if job['Status'] == 'Failed' else "succeeded with exceptions"
            highlights_html += f"""
            <li>
                <strong style='color:#dc3545;'>Reason for Unlock Online Delay:</strong> 
                {job['JobName']} {status_text} at {job['EndDate']} {job['EndTime']} - {error_msg}
            </li>
            """
    
    # Add solution/fix information if provided
    solution_html = ""
    if solution_text and solution_text.strip():
        replaced_text = solution_text.replace('\n', '<br>')
        solution_html = f"""
        <p><strong>Solution/Fix Applied:</strong></p>
        <div style='background-color:#e8f5e9; padding:10px; border-left:4px solid #28a745; border-radius:5px; margin-bottom:15px;'>
            {replaced_text}
        </div>
        """
    
    # Capture the dashboard HTML content
    print(f"Capturing dashboard HTML for {processing_date}...")
    dashboard_html_content = capture_dashboard_html(processing_date, environment)
    
    # Build email body with embedded dashboard HTML
    if dashboard_html_content:
        # Successfully captured HTML - embed it
        mail.HTMLBody = f'''
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; }}
                .email-header {{ margin-bottom: 20px; }}
                .dashboard-container {{ 
                    border: 1px solid #ddd; 
                    padding: 15px; 
                    margin: 20px 0;
                    background-color: #f9f9f9;
                    border-radius: 5px;
                }}
            </style>
        </head>
        <body>
            <div class="email-header">
                <p>Hi All,</p>
                <p>Please find the status of Aspire Nightly Batch - <strong>{processing_date}</strong> - <strong>{environment}</strong></p>
                <p><strong>Highlight:</strong></p>
                <ul>
                    {highlights_html}
                </ul>
                {solution_html}
            </div>
            
            <p><u><strong>AspireVision Dashboard</strong></u>:</p>
            <div class="dashboard-container">
                {dashboard_html_content}
            </div>
            
            <p>Thanks &amp; Regards,</p>
            <table cellpadding="0" cellspacing="0" border="0" style="font-family: Arial, sans-serif; font-size: 14px; line-height: 1.4; border-top: 1px solid #eeeeee; padding-top: 10px; margin-top: 10px;">
                <tr>
                    <td style="vertical-align: top;">
                        <strong style="color: #086C49;">Pratik Bhongade</strong><br>
                        <span style="color: #666666;">Software Engineer</span><br>
                        <span style="color: #666666;">KTO CBTO Equipment Finance | Pune, India</span><br>
                        <a href="mailto:Pratik_Bhongade@key.com" style="color: #086C49; text-decoration: none;">Pratik_Bhongade@key.com</a><br>
                    </td>
                </tr>
            </table>
        </body>
        </html>
        '''
        print("Email body created with embedded dashboard HTML")
    else:
        # HTML capture failed - show error message
        print("ERROR: HTML capture failed")
        mail.HTMLBody = f'''
        <html>
        <body>
            <p>Hi All,</p>
            <p>Please find the status of Aspire Nightly Batch - <strong>{processing_date}</strong> - <strong>{environment}</strong></p>
            <p><strong>Highlight:</strong></p>
            <ul>
                {highlights_html}
            </ul>
            {solution_html}
            
            <p style="color: red;"><strong>Error:</strong> Unable to capture dashboard content. Please check the application logs.</p>
            
            <p>Thanks &amp; Regards,</p>
            <table cellpadding="0" cellspacing="0" border="0" style="font-family: Arial, sans-serif; font-size: 14px; line-height: 1.4; border-top: 1px solid #eeeeee; padding-top: 10px; margin-top: 10px;">
                <tr>
                    <td style="vertical-align: top;">
                        <strong style="color: #086C49;">Pratik Bhongade</strong><br>
                        <span style="color: #666666;">Software Engineer</span><br>
                        <span style="color: #666666;">KTO CBTO Equipment Finance | Pune, India</span><br>
                        <a href="mailto:Pratik_Bhongade@key.com" style="color: #086C49; text-decoration: none;">Pratik_Bhongade@key.com</a><br>
                    </td>
                </tr>
            </table>
        </body>
        </html>
        '''
    
    # Return the mail object instead of sending it
    # This allows us to preview it before sending
    return mail

# Callback to update email preview content
@app.callback(
    Output("email-preview-frame", "srcDoc"),
    [Input("email-preview-modal", "is_open")]
)
def update_email_preview(is_open):
    if is_open and hasattr(app, 'email_data') and app.email_data:
        data = app.email_data
        
        # Get all the fields needed to generate the email
        processing_date = data.get('processing_date', '')
        environment = data.get('environment', 'PROD')
        benchmark_end_time_formatted = data.get('benchmark_end_time_formatted', '')
        failed_jobs = data.get('failed_jobs', pd.DataFrame())
        solution_text = data.get('solution_text', '')
        
        # Create highlights HTML
        highlights_html = (
            f"<li><strong>Environment:</strong> {environment}</li>"
            f"<li>Aspire Online Availability at <strong>{benchmark_end_time_formatted}</strong></li>"
        )
        
        # Add Reason for Unlock Online Delay in highlights if there are failed jobs
        if failed_jobs is not None and not failed_jobs.empty:
            for index, job in failed_jobs.iterrows():
                error_msg = job['Message'] if pd.notna(job['Message']) else "No error message available"
                status_text = "failed" if job['Status'] == 'Failed' else "succeeded with exceptions"
                highlights_html += f"""
                <li>
                    <strong style='color:#dc3545;'>Reason for Unlock Online Delay:</strong> 
                    {job['JobName']} {status_text} at {job['EndDate']} {job['EndTime']} - {error_msg}
                </li>
                """
        
        # Add solution/fix information if provided
        solution_html = ""
        if solution_text and solution_text.strip():
            replaced_text = solution_text.replace('\n', '<br>')
            solution_html = f"""
            <p><strong>Solution/Fix Applied:</strong></p>
            <div style='background-color:#e8f5e9; padding:10px; border-left:4px solid #28a745; border-radius:5px; margin-bottom:15px;'>
                {replaced_text}
            </div>
            """
        
        # MODIFICATION: Updated Email Footer in Preview - removed image and disclaimer line
        html_content = f'''
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; }}
                .highlight {{ background-color: #f8f9fa; padding: 10px; border-radius: 5px; }}
            </style>
        </head>
        <body>
            <p>Hi All,</p>
            <p>Please find the status of Aspire Nightly Batch - <strong>{processing_date}</strong> - <strong>{environment}</strong></p>
            <p><strong>Highlight:</strong></p>
            <ul>
                {highlights_html}
            </ul>
            {solution_html}
            <p><u><strong>AspireVision Dashboard</strong></u>:</p>
            <div style="border: 1px solid #ddd; padding: 5px; text-align: center; background-color: #f5f5f5;">
                [Dashboard Image Will Appear Here]
            </div>
            <p>Thanks & Regards,</p>
            <table cellpadding="0" cellspacing="0" border="0" style="font-family: Arial, sans-serif; font-size: 14px; line-height: 1.4; border-top: 1px solid #eeeeee; padding-top: 10px; margin-top: 10px;">
                <tr>
                    <td style="vertical-align: top;">
                        <strong style="color: #086C49;">Pratik Bhongade</strong><br>
                        <span style="color: #666666;">Software Engineer</span><br>
                        <span style="color: #666666;">KTO CBTO Equipment Finance | Pune, India</span><br>
                        <a href="mailto:Pratik_Bhongade@key.com" style="color: #086C49; text-decoration: none;">Pratik_Bhongade@key.com</a><br>
                    
                    </td>
                </tr>
            </table>
        </body>
        </html>
        '''
        
        return html_content
    
    return "<html><body><p>Email preview will appear here...</p></body></html>"

# Chatbot callbacks removed

# Enhanced browser opening with multiple fallback methods
def open_browser_with_fallbacks(url):
    """Try multiple methods to open the browser with comprehensive error handling"""
    browser_opened = False
    methods_tried = []
    
    logger.info(f"Attempting to open browser at: {url}")
    
    # Preferred method on Windows: os.startfile (doesn't spawn a cmd window)
    try:
        if os.name == 'nt':
            logger.debug("Trying os.startfile() on Windows...")
            os.startfile(url)
            logger.info("Browser opened using os.startfile()")
            browser_opened = True
            methods_tried.append("os.startfile() - Success")
    except Exception as e:
        logger.debug(f"os.startfile() failed: {e}")
        methods_tried.append(f"os.startfile() - Failed: {e}")

    # Next try webbrowser module (cross-platform)
    if not browser_opened:
        try:
            logger.debug("Trying webbrowser.open()...")
            webbrowser.open(url, new=1, autoraise=True)
            logger.info("Browser opened using webbrowser module")
            browser_opened = True
            methods_tried.append("webbrowser.open() - Success")
        except Exception as e:
            logger.warning(f"webbrowser.open() failed: {e}")
            methods_tried.append(f"webbrowser.open() - Failed: {e}")

    # For remaining fallbacks use subprocess but hide any console window on Windows
    if not browser_opened:
        CREATE_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)

        # Try explorer (shouldn't create a console)
        try:
            logger.debug("Trying explorer method...")
            subprocess.Popen(['explorer', url], creationflags=CREATE_NO_WINDOW)
            logger.info("Browser opened using explorer")
            browser_opened = True
            methods_tried.append("Explorer - Success")
        except Exception as e:
            logger.warning(f"Explorer method failed: {e}")
            methods_tried.append(f"Explorer - Failed: {e}")

    # Try direct browser executables (hidden)
    if not browser_opened:
        browser_paths = [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files\Mozilla Firefox\firefox.exe",
            r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe"
        ]
        for browser_path in browser_paths:
            if os.path.exists(browser_path):
                try:
                    logger.debug(f"Trying direct browser: {browser_path}")
                    subprocess.Popen([browser_path, url], creationflags=CREATE_NO_WINDOW)
                    browser_name = os.path.basename(browser_path)
                    logger.info(f"Browser opened using direct path: {browser_name}")
                    browser_opened = True
                    methods_tried.append(f"Direct {browser_name} - Success")
                    break
                except Exception as e:
                    logger.debug(f"Direct browser {browser_path} failed: {e}")
                    methods_tried.append(f"Direct {os.path.basename(browser_path)} - Failed: {e}")

    # PowerShell fallback (use hidden window style)
    if not browser_opened and os.name == 'nt':
        try:
            logger.debug("Trying PowerShell hidden Start-Process method...")
            ps_cmd = ['powershell', '-NoProfile', '-WindowStyle', 'Hidden', '-Command', f'Start-Process "{url}"']
            subprocess.Popen(ps_cmd, creationflags=CREATE_NO_WINDOW)
            logger.info("Browser opened using PowerShell Start-Process")
            browser_opened = True
            methods_tried.append("PowerShell - Success")
        except Exception as e:
            logger.warning(f"PowerShell method failed: {e}")
            methods_tried.append(f"PowerShell - Failed: {e}")
    
    logger.info(f"Browser opening attempts: {methods_tried}")
    
    if not browser_opened:
        logger.error("All browser opening methods failed")
        logger.info(f"Please manually open your browser and navigate to: {url}")
    
    return browser_opened

# ============================================================================
# DAILY EMAIL SCHEDULER (2 AM local time)
# ============================================================================
def schedule_daily_email():
    """Run a background thread that sends the dashboard email daily at 2:00 AM local time."""
    def runner():
        while True:
            try:
                now = datetime.now()
                next_run = now.replace(hour=2, minute=0, second=0, microsecond=0)
                if next_run <= now:
                    next_run += timedelta(days=1)
                sleep_seconds = max(1, int((next_run - now).total_seconds()))
                logger.info(f"Scheduler sleeping {sleep_seconds}s until next 2 AM run")
                time.sleep(sleep_seconds)

                processing_date = get_last_business_day().strftime('%Y-%m-%d')
                environment = 'PROD'
                logger.info(f"Scheduler: preparing email for date={processing_date}, env={environment}")

                df_sched, _, _, _ = fetch_data(processing_date, environment)
                if df_sched is None or df_sched.empty:
                    logger.warning("Scheduler: No data returned; skipping send")
                    continue

                image_path = capture_main_dashboard(processing_date, environment)
                benchmark_end_time = df_sched[df_sched['JobName'] == '20. Benchmark Update']['EndTime'].max()
                bench_fmt = pd.to_datetime(benchmark_end_time).strftime('%I:%M %p') if pd.notnull(benchmark_end_time) else "N/A"

                failed_jobs = df_sched[
                    ((df_sched['JobName'] != '20. Benchmark Update') & (df_sched['Status'] == 'Failed')) |
                    ((df_sched['JobName'] == '20. Benchmark Update') & (df_sched['Status'] == 'Succeeded with Exceptions'))
                ]

                mail = send_email_with_screenshot(
                    image_path,
                    processing_date,
                    environment,
                    bench_fmt,
                    failed_jobs,
                    getattr(app, 'solution_text', "")
                )
                mail.Send()
                logger.info("Scheduler: Email sent successfully")
            except Exception as e:
                logger.error(f"Scheduler error: {e}")
                logger.error(traceback.format_exc())

    threading.Thread(target=runner, daemon=True).start()

def main():
    """Enhanced main function with comprehensive error handling and logging"""
    logger.info("="*60)
    logger.info(" ASPIRE DASHBOARD MAIN FUNCTION STARTED")
    logger.info("="*60)
    
    logger.info("%s", "="*60)
    logger.info("AspireVision Dashboard Starting...")
    logger.info("%s", "="*60)
    
    # Check if we're running from PyInstaller
    if hasattr(sys, '_MEIPASS'):
        logger.info("Running from PyInstaller executable")
    else:
        logger.info("Running from Python script")
    
    # Log system information
    logger.info(f"Current working directory: {os.getcwd()}")
    logger.info(f"Python executable: {sys.executable}")
    logger.info(f"Python version: {sys.version}")
    
    # Check dependencies
    logger.info("Checking critical dependencies...")
    critical_dependencies = ['pyodbc', 'pandas', 'dash', 'selenium', 'win32com.client']
    missing_deps = []
    
    for dep in critical_dependencies:
        try:
            __import__(dep)
            logger.debug(f"{dep} - Available")
        except ImportError:
            logger.error(f"{dep} - Missing")
            missing_deps.append(dep)
    
    if missing_deps:
        logger.error(f"Critical dependencies missing: {missing_deps}")
        # Do not prompt for input when running headless; exit main
        return
    
    # Check for required files
    edge_driver_path = get_edge_driver_path()
    if not os.path.exists(edge_driver_path):
        logger.error(f"Edge driver not found at: {edge_driver_path}")
        logger.warning("Warning: Edge driver not found. Email functionality may not work.")
    else:
        logger.info(f"Edge driver found at: {edge_driver_path}")
    
    # Start the dashboard server directly (avoiding multiprocessing issues with PyInstaller)
    logger.info("Starting dashboard server...")
    
    server_started = run_dash_server_directly()
    
    if not server_started:
        logger.error("Failed to start dashboard server")
        logger.error("Troubleshooting: Check if another application is using port 8050; try running as administrator; check Windows Firewall settings")
        if log_file_path:
            logger.error(f"Check the log file: {log_file_path}")
        # Exit main without waiting for console input
        return
    
    # Give the server a moment to start up
    logger.info("Dash server started, waiting briefly for initialization...")
    time.sleep(2)
    
    # Optionally open browser (without polling)
    dashboard_url = 'http://127.0.0.1:8050/'
    logger.info(f"Opening dashboard at: {dashboard_url}")
    
    # Use our safer browser opener which avoids spawning a visible cmd window
    browser_opened = open_browser_with_fallbacks(dashboard_url)
    
    logger.info("%s", "="*60)
    logger.info("Dashboard Status: URL=%s, Server=Running, Browser=%s, Log File=%s", dashboard_url, ('Opened' if browser_opened else 'Manual required'), (log_file_path if log_file_path else 'Not available'))
    logger.info("%s", "="*60)
    logger.info("Dashboard is now running. If it is not visible, manually navigate to %s", dashboard_url)
    
    logger.info("Dashboard startup completed")
    # Start background 2 AM scheduler
    try:
        schedule_daily_email()
        logger.info("2 AM daily email scheduler started")
    except Exception as e:
        logger.error(f"Failed to start scheduler: {e}")

    try:
        # Run indefinitely until interrupted
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        logger.info("Shutdown requested by user")
    finally:
        logger.info("Dashboard stopped successfully")

        # Final log entry
        logger.info("%s", "="*60)
        logger.info(" ASPIRE DASHBOARD SESSION ENDED")
        logger.info("%s", "="*60)

# Prevent recursion in PyInstaller
if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        logger.error(f"Fatal error in main: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        logger.error(f"Fatal error: {e}")
        # Exit without waiting for console input
    except KeyboardInterrupt:
        logger.info("Shutdown requested.")
    finally:
        logger.info("Application ended.")
