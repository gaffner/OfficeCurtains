import json
import logging
import os
from datetime import datetime
from functools import wraps

import requests
from dotenv import load_dotenv
from fastapi import Request, HTTPException
from fastapi.responses import RedirectResponse

load_dotenv()
ALLOWED_ISP = os.getenv('ALLOWED_ISP')


def setup_logging():
    """Setup logging to both stdout and a timestamped log file"""
    # Create formatter
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    
    # Get root logger
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    # Remove existing handlers to avoid duplicates
    logger.handlers.clear()
    
    # Console handler (stdout) - always add this first
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # Try to setup file logging
    try:
        # Use logs folder in the project directory
        project_root = os.path.dirname(os.path.abspath(__file__))
        log_dir = os.path.join(project_root, 'logs')
        
        # Create log directory if it doesn't exist
        os.makedirs(log_dir, exist_ok=True)
        
        # Find the next incremental number for the log file
        next_number = 1
        if os.path.exists(log_dir):
            existing_files = os.listdir(log_dir)
            # Extract numbers from filenames that match pattern: NNN_*.log
            numbers = []
            for filename in existing_files:
                if filename.endswith('_run.log'):
                    # Try to extract the number prefix
                    parts = filename.split('_', 1)
                    if len(parts) == 2:
                        try:
                            num = int(parts[0])
                            numbers.append(num)
                        except ValueError:
                            pass
            if numbers:
                next_number = max(numbers) + 1
        
        # Create timestamped log filename with incremental prefix
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        log_file = os.path.join(log_dir, f'{next_number:03d}_{timestamp}_run.log')
        
        # File handler
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        
        logging.info(f"Logging initialized. Log file: {log_file}")
    except Exception as e:
        # If file logging fails, at least we have console logging
        logging.warning(f"Failed to setup file logging: {e}. Continuing with console logging only.")


def is_allowed_isp(ip: str):
    try:
        result = json.loads(requests.get(f'http://ip-api.com/json/{ip}?fields=isp').text)
        logging.info(f'IP-API result: {result}, allowed isp is {ALLOWED_ISP}')
        return ip == '127.0.0.1' or result['isp'] == ALLOWED_ISP
    except KeyError:
        logging.error(f'Client disallowed IP {ip}')
        return False


def get_client_ip(request: Request) -> str:
    if request.client:
        user_ip = request.client.host  # local run (direct access)
    else:
        user_ip = request.headers.get("X-Real-IP")  # support for reverse proxy (nginx)

    return user_ip


def validate_isp():
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            request: Request = kwargs.get("request")
            if not request:
                raise HTTPException(status_code=400, detail="Request object is missing.")

            try:
                user_ip = get_client_ip(request)
                if not is_allowed_isp(user_ip):
                    return RedirectResponse(url="/Frontend/blocked.html")
            except Exception as e:
                logging.info(f"bad request: {request}, {request.client}, {request.headers}")
                raise HTTPException(status_code=500, detail=str(e))

            return func(*args, **kwargs)

        return wrapper

    return decorator
