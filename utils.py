import json
import logging
import os
from functools import wraps

import requests
from dotenv import load_dotenv
from fastapi import Request, HTTPException
from fastapi.responses import RedirectResponse

load_dotenv()
ALLOWED_ISP = os.getenv('ALLOWED_ISP')

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def is_allowed_isp(ip: str):
    try:
        result = json.loads(requests.get(f'http://ip-api.com/json/{ip}?fields=isp').text)
        logging.info(f'IP-API result: {result}, allowed isp is {ALLOWED_ISP}')
        return ip == '127.0.0.1' or result['isp'] == ALLOWED_ISP
    except KeyError:
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
