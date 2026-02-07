import os
import logging
from dotenv import load_dotenv

# Load .env file, or .env.example if .env doesn't exist
if os.path.exists('.env'):
    load_dotenv('.env')
else:
    load_dotenv('.env.example')
    logging.warning("No .env file found - using .env.example (for development only, not for production!)")

# Check test mode first
IS_TEST = os.getenv('IS_TEST', 'false').lower() == 'true'

# In test mode, use defaults so developers don't need real config
if IS_TEST:
    SERVER_IP = 'localhost'
    CURTAINS_USERNAME = 'test'
    MD5_VALUE = 'test'
    CURTAINS_PASSWORD = 'test'
    REPORTS_FILE = 'reports.txt'
    STATISTICS_FILE = 'statistics.txt'
    COOKIES_KEY = 'test-secret-key-for-development'
else:
    SERVER_IP = os.getenv('SERVER_IP')
    CURTAINS_USERNAME = os.getenv('CURTAINS_USERNAME')
    MD5_VALUE = os.getenv('MD5_VALUE')
    CURTAINS_PASSWORD = os.getenv('CURTAINS_PASSWORD')
    REPORTS_FILE = os.getenv('REPORTS_FILE')
    STATISTICS_FILE = os.getenv('STATISTICS_FILE')
    COOKIES_KEY = os.getenv('COOKIES_KEY')

# Admin users (parsed from comma-separated list)
ADMIN_USERS = [user.strip() for user in os.getenv('ADMIN_USERS', 'developer').split(',') if user.strip()]

STATISTICS_FOLDER = "csv/"
CSV_FORMAT = "Room,Up,Down"


def get_server_port(suffix):
    return os.getenv('SERVER_PORT_' + suffix)
