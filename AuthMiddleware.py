import logging
import os

from fastapi import HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import RedirectResponse, HTMLResponse

from auth import get_auth_app


class CurtainsAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/auth/callback":
            return await call_next(request)

        if request.url.path.startswith("/Frontend/"):
            # If it's an HTML file under Frontend
            if request.url.path.endswith('.html'):
                # Check authentication first
                if not request.session.get("user"):
                    auth_app = get_auth_app()
                    auth_url = auth_app.get_authorization_request_url(
                        scopes=['User.Read'],
                        redirect_uri=os.getenv('AZURE_REDIRECT_URI')
                    )
                    return RedirectResponse(url=auth_url, status_code=302)

                # For index.html, intercept and inject username
                if request.url.path == "/Frontend/index.html":
                    with open('Frontend/index.html', 'r') as f:
                        content = f.read()

                    username = request.session.get("user_name", "User")
                    content = content.replace(
                        '<div id="welcome-message" class="welcome-message"></div>',
                        f'<div id="welcome-message" class="welcome-message">Hello {username}!</div>'
                    )
                    return HTMLResponse(content=content)

            # Allow all other static files
            return await call_next(request)

        try:
            # Check for authentication
            if not request.session.get("user"):
                logging.debug(f"User not authenticated, redirecting from {request.url.path}")
                # For API endpoints or XHR requests, return 401 instead of redirect
                headers = dict(request.headers)
                is_xhr = headers.get('accept') == 'application/json' or headers.get(
                    'x-requested-with') == 'XMLHttpRequest'
                if is_xhr or request.url.path.startswith('/stats/'):
                    raise HTTPException(
                        status_code=401,
                        detail="Authentication required"
                    )
                auth_app = get_auth_app()
                auth_url = auth_app.get_authorization_request_url(
                    scopes=['User.Read'],
                    redirect_uri=os.getenv('AZURE_REDIRECT_URI')
                )
                return RedirectResponse(url=auth_url, status_code=302)

            # User is authenticated, proceed
            return await call_next(request)

        except Exception as e:
            logging.error(f"Error in auth middleware: {str(e)}")
            auth_app = get_auth_app()
            auth_url = auth_app.get_authorization_request_url(
                scopes=['User.Read'],
                redirect_uri=os.getenv('AZURE_REDIRECT_URI')
            )
            return RedirectResponse(url=auth_url, status_code=302)
