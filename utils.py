import json
import os
from functools import wraps

import requests
from fastapi import Request, HTTPException
from fastapi.responses import RedirectResponse

ALLOWED_ISP = os.getenv('ALLOWED_ISP')



def is_allowed_isp(ip: str):
    try:
        result = json.loads(requests.get(f'http://ip-api.com/json/{ip}?fields=isp').text)
        return result['isp'] == ALLOWED_ISP
    except KeyError:
        return False


def validate_isp():
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            request: Request = kwargs.get("request")
            if not request:
                raise HTTPException(status_code=400, detail="Request object is missing.")

            user_ip = request.client.host
            if not is_allowed_isp(user_ip):
                return RedirectResponse(url="/Frontend/blocked.html")

            return func(*args, **kwargs)

        return wrapper

    return decorator
