import logging
from datetime import datetime

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from starlette.staticfiles import StaticFiles

from config import *
from helper import get_suffix, get_username, get_states_by_direction, send_message, get_room_states
from statistics import StatisticsManager
from utils import validate_isp, get_client_ip

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Setup the FastAPI app
load_dotenv()
app = FastAPI(redirect_slashes=False)

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
def submit_report(request: Request, content: str):
    user_ip = get_client_ip(request)
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    report_entry = f"{current_time} - {user_ip} - {content}\n"

    os.makedirs(os.path.dirname(TSHIRT_REQUESTS_FILE), exist_ok=True)
    with open(TSHIRT_REQUESTS_FILE, "a") as file:
        file.write(report_entry)

    return {"message": "Report submitted successfully"}


@app.get("/")
@validate_isp()
def root(request: Request):
    return RedirectResponse(url="/Frontend/index.html")


@app.get("/register/{room_name}")
@validate_isp()
def register(request: Request, room_name: str):
    states = get_room_states(room_name.upper())
    directions = [state['name'] for state in states]

    return directions


@app.get("/control/{room_name}/{action}")
@validate_isp()
def control_curtain(request: Request, room_name: str, action: str, direction: str = None):
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
