import logging
from datetime import datetime

import requests
import uvicorn
from fastapi import FastAPI, HTTPException, Request

from fastapi.responses import JSONResponse, HTMLResponse
from starlette.middleware.sessions import SessionMiddleware
from starlette.staticfiles import StaticFiles

from AuthMiddleware import CurtainsAuthMiddleware
from auth import get_auth_app
from config import *
from helper import get_suffix, get_username, get_states_by_direction, send_message, get_room_states
from statistics import StatisticsManager

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Setup the FastAPI app
load_dotenv()

app = FastAPI(redirect_slashes=False)

# Order matters: session middleware should be last to wrap everything
app.add_middleware(CurtainsAuthMiddleware)
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SESSION_SECRET_KEY", os.urandom(24)))

# Constants for the server and authentication


# Mount static files after middleware setup - Do not change the order!!!
app.mount("/Frontend", StaticFiles(directory="Frontend"), name="Frontend")

stats_manager = StatisticsManager()


@app.get("/submit-report/{report}")
async def submit_report(request: Request, report: str):
    try:
        user_name = request.session.get("user_name")
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        report_entry = f"{current_time} - {user_name} - {report}\n"

        with open(REPORTS_FILE, "a") as file:
            file.write(report_entry)

        response = JSONResponse(
            content={"message": "Report submitted successfully"},
            status_code=200
        )
        return response
    except Exception as e:
        logging.error(f"Error submitting report: {str(e)}")
        raise HTTPException(status_code=500, detail="Error submitting report")


@app.get("/submit-tshirt-request/{content}")
async def submit_tshirt_request(request: Request, content: str):
    try:
        user_name = request.session.get("user_name")
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        report_entry = f"{current_time} - {user_name} - {content}\n"

        with open(TSHIRT_REQUESTS_FILE, "a") as file:
            file.write(report_entry)

        response = JSONResponse(
            content={"message": "Report submitted successfully"},
            status_code=200
        )

        return response
    except Exception as e:
        logging.error(f"Error submitting t-shirt request: {str(e)}")
        raise HTTPException(status_code=500, detail="Error submitting request")


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
        # Instead of redirecting, render index.html directly with username
        with open('Frontend/index.html', 'r') as f:
            content = f.read()

        username = request.session.get("user_name", "User")
        content = content.replace(
            '<div id="welcome-message" class="welcome-message"></div>',
            f'<div id="welcome-message" class="welcome-message">Hello {username}!</div>'
        )
        return HTMLResponse(content=content)

    except Exception as e:
        logging.error(f"Unexpected error in auth callback: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Authentication error: {str(e)}")


@app.get("/")
async def root(request: Request):
    """Root handler that injects username and redirects to index.html"""
    with open('Frontend/index.html', 'r') as f:
        content = f.read()

    username = request.session.get("user_name", "User")
    content = content.replace(
        '<div id="welcome-message" class="welcome-message"></div>',
        f'<div id="welcome-message" class="welcome-message">Hello {username}!</div>'
    )
    return HTMLResponse(content=content)


@app.get("/register/{room_name}")
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


@app.get("/control/{room_name}/{action}")
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
            content = {"status": "success",
                       "message": f"Curtain in room {room_name} {action} command sent successfully."}
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
async def get_stats(request: Request):
    """Get statistics for the current day"""
    try:
        logging.info(f"Handling daily stats request from origin: {request.headers.get('origin', 'unknown')}")
        response = JSONResponse(content={
            "data": stats_manager.get_daily_stats(),
            "room_count": stats_manager.get_room_count()
        })

        return response
    except Exception as e:
        logging.error(f"Error getting daily statistics: {str(e)}")
        raise HTTPException(status_code=500, detail="Error retrieving daily statistics")


@app.get("/stats/all")
async def get_all_stats(request: Request):
    """Get statistics for all days"""
    try:
        data = stats_manager.get_all_stats()
        total_rooms = stats_manager.get_total_unique_rooms_count()

        response = JSONResponse(
            content={
                "data": data,
                "total_unique_rooms": total_rooms
            },
            status_code=200
        )

        return response

    except Exception as e:
        logging.error(f"Error getting statistics: {str(e)}")
        raise HTTPException(status_code=500, detail="Error retrieving statistics")


def main():
    uvicorn.run(app, host='0.0.0.0', port=8000)


# Running the FastAPI app (you can use `uvicorn` to run this in your terminal)
if __name__ == '__main__':
    main()
