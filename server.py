import logging
from datetime import datetime

import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
from starlette.staticfiles import StaticFiles

from auth import get_auth_app
from config import *
from helper import get_suffix, get_username, get_states_by_direction, send_message, get_room_states
from statistics import StatisticsManager
from utils import get_client_ip

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Setup the FastAPI app
load_dotenv()
app = FastAPI(redirect_slashes=False)

# Add session middleware with a secret key
app.add_middleware(SessionMiddleware, secret_key=COOKIES_KEY, max_age=7 * 24 * 60 * 60)

# Constants for the server and authentication

app.mount("/Frontend", StaticFiles(directory="Frontend"), name="Frontend")

stats_manager = StatisticsManager()


@app.get("/submit-report/{report}")
def submit_report(request: Request, report: str):
    user_ip = get_client_ip(request)
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    report_entry = f"{current_time} - {user_ip} - {report}\n"

    os.makedirs(os.path.dirname(REPORTS_FILE), exist_ok=True)
    with open(REPORTS_FILE, "a") as file:
        file.write(report_entry)

    return {"message": "Report submitted successfully"}


@app.get("/submit-tshirt-request/{content}")
def submit_tshirt_request(request: Request, content: str):
    user_ip = get_client_ip(request)
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    report_entry = f"{current_time} - {user_ip} - {content}\n"

    os.makedirs(os.path.dirname(TSHIRT_REQUESTS_FILE), exist_ok=True)
    with open(TSHIRT_REQUESTS_FILE, "a") as file:
        file.write(report_entry)

    return {"message": "Report submitted successfully"}


@app.get("/login")
def login(request: Request):
    """Initiate AAD login flow"""
    username = request.session.get('user_name')
    if username:
        # User already logged in, redirect to home
        return RedirectResponse(url="/Frontend/index.html")

    request.session['user_name'] = 'gefen'
    # return {'status': 'success'}

    # Generate authorization URL and redirect user to AAD login
    auth_url = get_auth_app().get_authorization_request_url(
        scopes=['User.Read'],
        redirect_uri=os.getenv('AZURE_REDIRECT_URI')
    )
    return RedirectResponse(url=auth_url)


@app.get("/check-auth")
def check_auth(request: Request):
    """Check if user is authenticated and return user info"""
    username = request.session.get('user_name')
    if not username:
        return {
            'authenticated': False,
            'username': None
        }

    return {
        'authenticated': True,
        'username': username
    }


@app.get("/logout")
def logout(request: Request):
    """Clear user session"""
    request.session.clear()
    return RedirectResponse(url="/Frontend/index.html")


@app.get("/")
def root(request: Request):
    return RedirectResponse(url="/Frontend/index.html")


@app.get("/register/{room_name}")
def register(request: Request, room_name: str):
    # Check if user is authenticated
    username = request.session.get('user_name')
    if not username:
        raise HTTPException(status_code=401, detail="You need to authenticate")
    
    states = get_room_states(room_name.upper())
    directions = [state['name'] for state in states]
    return directions


@app.get("/control/{room_name}/{action}")
def control_curtain(request: Request, room_name: str, action: str, direction: str = None):
    # Check if user is authenticated
    username = request.session.get('user_name')
    if not username:
        raise HTTPException(status_code=401, detail="You need to authenticate")
    
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
        return {"status": "success", "message": f"Curtain in room {room_name} {action} command sent successfully."}
    else:
        raise HTTPException(status_code=res.status_code, detail=f"Failed to send command {res.text}")


@app.get("/stats")
def get_stats(request: Request):
    """Get statistics for the current day"""
    return {
        "data": stats_manager.get_daily_stats(),
        "room_count": stats_manager.get_room_count()
    }


@app.get("/stats/all")
def get_all_stats(request: Request):
    """Get statistics for all days"""
    return {
        "data": stats_manager.get_all_stats(),
        "total_unique_rooms": stats_manager.get_total_unique_rooms_count()
    }


@app.get("/auth/callback")
def auth_callback(request: Request, code: str = None, state: str = None, error: str = None):
    """Handle AAD authentication callback"""
    logging.info("Received auth callback")
    logging.debug(f"Code: {code[:10] if code else 'None'}... State: {state}")

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

        # Store access token in session
        request.session["access_token"] = result["access_token"]

        # Get user info from Microsoft Graph
        graph_data = requests.get(
            'https://graph.microsoft.com/v1.0/me',
            headers={'Authorization': f'Bearer {result["access_token"]}'}
        ).json()

        # Store username in session
        username = graph_data.get("displayName", "Unknown User")
        logging.info(f'Graph result: {graph_data}')
        logging.info(f'Setting username to {username}')
        request.session['user_name'] = username
        logging.info(f"Successfully authenticated user: {request.session['user_name']}")

        # Redirect to home page after successful login
        return RedirectResponse(url="/Frontend/index.html")

    except Exception as e:
        logging.error(f"Unexpected error in auth callback: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Authentication error: {str(e)}")