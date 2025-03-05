import json
import logging
from datetime import datetime
from functools import lru_cache

import requests
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from starlette.staticfiles import StaticFiles

from config import *
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

    with open(REPORTS_FILE, "a") as file:
        file.write(report_entry)

    return {"message": "Report submitted successfully"}


@app.get("/submit-tshirt-request/{content}")
def submit_report(request: Request, content: str):
    user_ip = get_client_ip(request)
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    report_entry = f"{current_time} - {user_ip} - {content}\n"

    with open(TSHIRT_REQUESTS_FILE, "a") as file:
        file.write(report_entry)

    return {"message": "Report submitted successfully"}


@app.get("/")
@validate_isp()
def root(request: Request):
    return RedirectResponse(url="/Frontend/index.html")


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


@app.get("/register/{room_name}")
@validate_isp()
def register(request: Request, room_name: str):
    states = get_room_states(room_name.upper())
    directions = [state['name'] for state in states]

    return directions


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
    return {"data": stats_manager.get_daily_stats()}


@app.get("/stats/all")
def get_all_stats(request: Request):
    """Get statistics for all days"""
    return {"data": stats_manager.get_all_stats()}


def main():
    uvicorn.run(app, host='0.0.0.0', port=8080)


# Running the FastAPI app (you can use `uvicorn` to run this in your terminal)
if __name__ == '__main__':
    main()
