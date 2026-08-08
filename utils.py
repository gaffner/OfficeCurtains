import logging
import os
from datetime import datetime
from functools import wraps
from inspect import iscoroutinefunction

import requests
from dotenv import load_dotenv
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse

load_dotenv()
ALLOWED_ISP = os.getenv('ALLOWED_ISP')

BLOCKED_MESSAGE = (
    "Access denied: your network provider is not on the allow list for this service."
)

# Always allowed: local development and reverse-proxy health checks.
LOCALHOST_ADDRESSES = ('127.0.0.1', 'localhost', '::1')


def get_allowed_isps():
    """Configured ISP names, normalised for case-insensitive comparison.

    Providers are matched by exact name (never substring), but casing varies
    between lookups, so compare case-insensitively.
    """
    return {
        isp.strip().casefold()
        for isp in (ALLOWED_ISP or '').split(',')
        if isp.strip()
    }


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


def lookup_isp(ip: str):
    """Return the ISP name reported for `ip`, or None if it cannot be determined.

    None means "unknown" (lookup failed / rate limited), which is deliberately
    distinct from "known but not allowed" so callers can tell the difference.
    """
    try:
        response = requests.get(
            f'http://ip-api.com/json/{ip}?fields=isp',
            timeout=5,
        )
        response.raise_for_status()
        result = response.json()
    except (requests.RequestException, ValueError):
        logging.exception(f'Failed to look up ISP for client IP {ip}')
        return None

    isp = (result.get('isp') or '').strip()
    logging.info(f'IP-API result: {result}, allowed ISPs are {sorted(get_allowed_isps())}')

    return isp or None


def is_allowed_isp(ip: str):
    # Localhost is always allowed (local development / reverse-proxy health checks)
    # and short-circuits before any external lookup.
    if ip in LOCALHOST_ADDRESSES:
        return True

    isp = lookup_isp(ip)
    if isp is None:
        return False

    return isp.casefold() in get_allowed_isps()


def get_client_ip(request: Request) -> str:
    if request.client:
        user_ip = request.client.host  # local run (direct access)
    else:
        user_ip = request.headers.get("X-Real-IP")  # support for reverse proxy (nginx)

    return user_ip


def wants_json(request: Request) -> bool:
    """Whether the caller expects a machine-readable body rather than a web page.

    Browser navigation should keep getting the friendly `blocked.html` page, but
    `fetch`/XHR callers must get JSON so they can show an indicative message
    instead of trying to parse HTML.
    """
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return True
    if "application/json" in request.headers.get("accept", "").lower():
        return True
    return request.url.path.startswith("/api/")


def _deny_response(request: Request):
    """The response for a blocked caller, or None when access is allowed."""
    if not request:
        raise HTTPException(status_code=400, detail="Request object is missing.")

    try:
        user_ip = get_client_ip(request)
        allowed = is_allowed_isp(user_ip)
    except Exception:
        logging.exception(f"Failed to evaluate access for request to {request.url.path}")
        raise HTTPException(
            status_code=503,
            detail="Could not verify network access right now. Please try again shortly.",
        )

    if allowed:
        return None

    if wants_json(request):
        return JSONResponse(status_code=403, content={"detail": BLOCKED_MESSAGE})

    return RedirectResponse(url="/Frontend/blocked.html")


def validate_isp():
    def decorator(func):
        # Async endpoints need an async wrapper. A sync wrapper would hand
        # FastAPI an un-awaited coroutine, because inspect.iscoroutinefunction
        # looks at the wrapper rather than the function it wraps.
        if iscoroutinefunction(func):
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                denied = _deny_response(kwargs.get("request"))
                if denied is not None:
                    return denied
                return await func(*args, **kwargs)

            return async_wrapper

        @wraps(func)
        def wrapper(*args, **kwargs):
            denied = _deny_response(kwargs.get("request"))
            if denied is not None:
                return denied
            return func(*args, **kwargs)

        return wrapper

    return decorator
