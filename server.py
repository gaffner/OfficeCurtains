import json
import logging
from datetime import datetime
from functools import lru_cache

import requests
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import RedirectResponse

from config import *
from statistics import StatisticsManager
from auth import require_auth, get_auth_app
import requests

class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/auth/callback":
            return await call_next(request)
            
        if request.url.path.startswith("/Frontend/"):
            # If it's an HTML file under Frontend, check auth
            if request.url.path.endswith('.html'):
                if not request.session.get("user"):
                    auth_app = get_auth_app()
                    auth_url = auth_app.get_authorization_request_url(
                        scopes=['User.Read'],
                        redirect_uri=os.getenv('AZURE_REDIRECT_URI')
                    )
                    return RedirectResponse(url=auth_url, status_code=302)
            # Allow other static files
            return await call_next(request)

        try:
            # Check for authentication
            if not request.session.get("user"):
                logging.debug(f"User not authenticated, redirecting from {request.url.path}")
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

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Setup the FastAPI app
load_dotenv()
app = FastAPI(redirect_slashes=False)

# Order matters: session middleware should be last to wrap everything
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(AuthMiddleware)
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SESSION_SECRET_KEY", os.urandom(24)))

# Constants for the server and authentication


# Mount static files
app.mount("/Frontend", StaticFiles(directory="Frontend"), name="Frontend")

stats_manager = StatisticsManager()


@app.get("/submit-report/{report}")
@require_auth()
def submit_report(request: Request, report: str):
    user_name = request.session.get("user")
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    report_entry = f"{current_time} - {user_name} - {report}\n"

    with open(REPORTS_FILE, "a") as file:
        file.write(report_entry)

    return {"message": "Report submitted successfully"}


@app.get("/submit-tshirt-request/{content}")
@require_auth()
def submit_report(request: Request, content: str):
    user_name = request.session.get("user")
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    report_entry = f"{current_time} - {user_name} - {content}\n"

    with open(TSHIRT_REQUESTS_FILE, "a") as file:
        file.write(report_entry)

    return {"message": "Report submitted successfully"}


@app.get("/auth/callback")
async def auth_callback(request: Request, code: str = None, state: str = None, error: str = None):
    import logging
    
    logging.info("Received auth callback")
    logging.debug(f"Code: {code[:10]}... State: {state}")
    
    if error:
        logging.error(f"Auth callback error: {error}")
        raise HTTPException(status_code=400, detail=f"Authentication failed: {error}")
    if not code:
        logging.error("No authorization code received")
        raise HTTPException(status_code=400, detail="No code received")

    try:
        auth_app = get_auth_app()
        logging.info("Attempting to acquire token with authorization code")
        result = auth_app.acquire_token_by_authorization_code(
            code,
            scopes=["User.Read"],
            redirect_uri=os.getenv("AZURE_REDIRECT_URI")
        )
        
        logging.debug(f"Token result keys: {result.keys()}")
        
        if "error" in result:
            logging.error(f"Token acquisition failed: {result.get('error_description', 'Unknown error')}")
            raise HTTPException(status_code=401, detail=result.get("error_description", "Authentication failed"))

        if "access_token" not in result:
            logging.error("No access token in response")
            raise HTTPException(status_code=401, detail="No access token received")

        request.session["user"] = result["access_token"]
        
        # Get user info from Microsoft Graph
        graph_data = requests.get(
            'https://graph.microsoft.com/v1.0/me',
            headers={'Authorization': f'Bearer {result["access_token"]}'}
        ).json()
        
        # Store user name in session
        request.session["user_name"] = graph_data.get("displayName", "User")
        
        logging.info(f"Successfully authenticated user: {request.session['user_name']}")
        return RedirectResponse(url="/Frontend/index.html", status_code=302)
        
    except Exception as e:
        logging.error(f"Unexpected error in auth callback: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Authentication error: {str(e)}")

@app.get("/")
@require_auth()
def root(request: Request):
    return RedirectResponse(url="/Frontend/index.html", status_code=302)


# Function to load room data from 'rooms.json' file
@lru_cache(maxsize=None)
def load_rooms_data():
    try:
        with open('rooms.json', 'r', encoding='utf-8') as file:
            return json.load(file)
    except Exception as e:
        logging.error(f"Error loading rooms.json: {e}")
        return {}


# Function to send POST requests to the server
def send_message(group, command, creds, address):
    url = f"https://{address[0]}:{address[1]}/iphone/send"
    data = f"username={creds[0]}\r\npassword={creds[1]}\r\nsk=\r\nversion=2\r\nmd5={MD5_VALUE}\r\ngroup={group}\r\neis=1.001\r\nvalue={command}\r\n"
    logging.info(f'Posting to: {url} with data: {data}')

    res = requests.post(url, data=data, headers={'User-Agent': 'XXter/1.0'}, verify=False)
    return res


def get_room_states(room_name: str):
    rooms = load_rooms_data()

    if room_name not in rooms:
        raise HTTPException(status_code=404, detail="Room not found")

    return rooms[room_name]


from fastapi.responses import JSONResponse

@app.get("/register/{room_name}")
@require_auth()
async def register(request: Request, room_name: str):
    try:
        logging.info(f"Register request for room: {room_name}")
        states = get_room_states(room_name.upper())
        directions = [state['name'] for state in states]
        logging.info(f"Found directions for {room_name}: {directions}")
        
        response = JSONResponse(content=directions)
        # Ensure the session cookie is included
        response.set_cookie(
            key="session",
            value=request.cookies.get("session", ""),
            httponly=True,
            samesite='strict'
        )
        return response
    except Exception as e:
        logging.error(f"Error in register endpoint: {str(e)}")
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))


def get_suffix(room_name):
    suffix = room_name[1]
    if suffix not in ('A', 'B', 'C'):
        raise HTTPException(status_code=404, detail=f"incorrect building {suffix}")

    return suffix


def get_username(room_name):
    suffix = get_suffix(room_name)
    username = CURTAINS_USERNAME + suffix
    logging.info(f'username is {username}')

    return username


def get_states_by_direction(room_name, direction):
    states = get_room_states(room_name)
    # if this room have multiple directions, get the correct one
    if direction and len(states) > 1:
        for state in states:
            if state['name'] == direction:
                return state

    # if not, return the only direction exists
    return states[0]


@app.get("/control/{room_name}/{action}")
@require_auth()
async def control_curtain(request: Request, room_name: str, action: str, direction: str = None):
    try:
        room_name = room_name.upper()
        suffix = get_suffix(room_name)
        creds = (get_username(room_name), CURTAINS_PASSWORD)
        address = (SERVER_IP, get_server_port(suffix))
        states = get_states_by_direction(room_name, direction)
        lift_direction = None
        operation_type = states['start']

        if action == 'up':
            logging.info(f"Curtain in room {room_name} is going up...")
            lift_direction = 0
        elif action == 'down':
            logging.info(f"Curtain in room {room_name} is going down...")
            lift_direction = 1
        elif action == 'stop':
            logging.info(f"Curtain in room {room_name} is stopping...")
            operation_type = states['stop']
        else:
            raise HTTPException(status_code=400, detail="Invalid action. Choose 'up', 'down', or 'stop'.")

        # Send the message to the server
        res = send_message(operation_type, lift_direction, creds, address)
        if res.status_code == 200 or res.status_code == 202:
            stats_manager.update_stats(room_name, action)
            content = {"status": "success", "message": f"Curtain in room {room_name} {action} command sent successfully."}
            response = JSONResponse(content=content)
            response.set_cookie(
                key="session",
                value=request.cookies.get("session", ""),
                httponly=True,
                samesite='strict'
            )
            return response
        else:
            raise HTTPException(status_code=res.status_code, detail=f"Failed to send command {res.text}")
    except Exception as e:
        logging.error(f"Error in control endpoint: {str(e)}")
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/stats")
@require_auth()
def get_stats(request: Request):
    """Get statistics for the current day"""
    return {
        "data": stats_manager.get_daily_stats(),
        "room_count": stats_manager.get_room_count()
    }


@app.get("/stats/all")
@require_auth()
def get_all_stats(request: Request):
    """Get statistics for all days"""
    return {
        "data": stats_manager.get_all_stats(),
        "total_unique_rooms": stats_manager.get_total_unique_rooms_count()
    }


def main():
    uvicorn.run(app, host='0.0.0.0', port=8080)


# Running the FastAPI app (you can use `uvicorn` to run this in your terminal)
if __name__ == '__main__':
    main()
