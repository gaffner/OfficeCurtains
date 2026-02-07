import logging
from datetime import datetime
from functools import wraps

import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse, PlainTextResponse, JSONResponse
from starlette.middleware.sessions import SessionMiddleware
from starlette.staticfiles import StaticFiles

from auth import get_auth_app
from config import *
from helper import get_suffix, get_username, get_states_by_direction, send_message, get_room_states
from statistics import StatisticsManager
from utils import get_client_ip, setup_logging
import users

# Setup logging before anything else
setup_logging()

# Setup the FastAPI app
load_dotenv()
app = FastAPI(redirect_slashes=False)

# Add session middleware with a secret key
# In test mode, use session cookies (expire when browser closes)
# In production, persist for 7 days
session_max_age = None if IS_TEST else 7 * 24 * 60 * 60
app.add_middleware(SessionMiddleware, secret_key=COOKIES_KEY, max_age=session_max_age)

# Constants for the server and authentication

app.mount("/Frontend", StaticFiles(directory="Frontend"), name="Frontend")

stats_manager = StatisticsManager()


# Authentication decorator
def require_auth(func):
    """Decorator to require authentication for endpoints"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        # Get request from kwargs
        request = kwargs.get('request')
        if not request:
            # Try to find request in args
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break
        
        if not request:
            raise HTTPException(status_code=500, detail="Request object not found")
        
        # Check if user is authenticated
        username = request.session.get('user_name')
        if not username:
            raise HTTPException(status_code=401, detail="You need to authenticate")
        
        # Call the original function
        return func(*args, **kwargs)
    
    return wrapper


# Admin decorator
def require_admin(func):
    """Decorator to require admin authentication for endpoints"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        # Get request from kwargs
        request = kwargs.get('request')
        if not request:
            # Try to find request in args
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break
        
        if not request:
            raise HTTPException(status_code=500, detail="Request object not found")
        
        # Check if user is authenticated
        username = request.session.get('user_name')
        if not username:
            raise HTTPException(status_code=401, detail="You need to authenticate")
        
        # Check if user is admin (case-insensitive)
        if username.lower() not in ADMIN_USERS:
            raise HTTPException(status_code=403, detail="Admin access required")
        
        # Call the original function
        return func(*args, **kwargs)
    
    return wrapper


@app.get("/submit-report/{report}")
@require_auth
def submit_report(request: Request, report: str):
    user_ip = get_client_ip(request)
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    report_entry = f"{current_time} - {user_ip} - {report}\n"

    os.makedirs(os.path.dirname(REPORTS_FILE), exist_ok=True)
    with open(REPORTS_FILE, "a") as file:
        file.write(report_entry)

    return {"message": "Report submitted successfully"}


@app.get("/whats-new")
def get_whats_new():
    """Serve the what's new markdown content"""
    whats_new_file = "whats_new.md"
    
    if not os.path.exists(whats_new_file):
        raise HTTPException(status_code=404, detail="What's new file not found")
    
    try:
        with open(whats_new_file, "r", encoding="utf-8") as file:
            content = file.read()
        return PlainTextResponse(content=content, media_type="text/plain; charset=utf-8")
    except Exception as e:
        logging.error(f"Error reading what's new file: {e}")
        raise HTTPException(status_code=500, detail="Failed to read what's new content")


@app.get("/version")
def get_version():
    """Serve the current version from .version file"""
    version_file = ".version"
    
    if not os.path.exists(version_file):
        return {"version": "1.0"}
    
    try:
        with open(version_file, "r", encoding="utf-8") as file:
            version = file.read().strip()
        return {"version": version}
    except Exception as e:
        logging.error(f"Error reading version file: {e}")
        return {"version": "1.0"}


@app.get("/login")
def login(request: Request):
    """Initiate AAD login flow"""
    # Test mode - always show login popup (don't check existing session)
    if IS_TEST:
        return RedirectResponse(url="/Frontend/index.html?showTestLogin=true")
    
    username = request.session.get('user_name')
    if username:
        # User already logged in, redirect to home
        return RedirectResponse(url="/Frontend/index.html")

    # Generate authorization URL and redirect user to AAD login
    auth_url = get_auth_app().get_authorization_request_url(
        scopes=['User.Read'],
        redirect_uri=os.getenv('AZURE_REDIRECT_URI')
    )
    return RedirectResponse(url=auth_url)


@app.get("/login/test")
def test_login(request: Request, username: str):
    """Test mode login with custom username"""
    if not IS_TEST:
        raise HTTPException(status_code=403, detail="Test login only available in test mode")
    
    # Save pending referral BEFORE clearing session
    pending_referral = request.session.get('pending_referral')
    logging.info(f"Test login: Saved pending_referral from session: {pending_referral}")
    
    # Clear any existing session
    request.session.clear()
    
    if not username or username.strip() == '':
        username = 'Developer'
    
    request.session['user_name'] = username
    
    # Check if user is NEW before creating
    is_new_user = not users.user_exists(username)
    logging.info(f"Test mode login: username={username}, is_new_user={is_new_user}")
    
    users.get_or_create_user(username)
    logging.info(f"Test mode: logged in as {username} (new: {is_new_user})")
    
    # Process pending referral ONLY if this is a new user
    logging.info(f"Pending referral: {pending_referral}, is_new_user: {is_new_user}")
    if pending_referral and pending_referral != username and is_new_user:
        logging.info(f"Processing referral for {pending_referral} from NEW user {username}")
        users.process_referral(pending_referral, username)
        users.add_points(pending_referral, 20)  # Grant 20 points for referral
        
        # Add success messages to both users
        users.add_message(
            pending_referral,
            "success",
            "Congratulations!",
            f"{username} just signed up using your referral link! You got 20 points (you need 60 points to get Premium)! ✨"
        )
        users.add_message(
            username,
            "success",
            "Thank You!",
            f"{pending_referral} shared their referral link with you. They just earned 20 points thanks to you! 🎉"
        )
        
        logging.info(f"Processed referral for {pending_referral} from NEW user {username}")
    
    return RedirectResponse(url="/Frontend/index.html")


@app.get("/check-auth")
def check_auth(request: Request):
    """Check if user is authenticated and return user info including premium status"""
    username = request.session.get('user_name')
    if not username:
        return {
            'authenticated': False,
            'username': None,
            'is_premium': False,
            'is_admin': False
        }

    return {
        'authenticated': True,
        'username': username,
        'is_premium': users.is_premium(username),
        'points': users.get_points(username),
        'is_admin': username.lower() in ADMIN_USERS
    }


@app.get("/api/messages")
@require_auth
def get_messages(request: Request):
    """Get all pending messages for the current user and clear them."""
    username = request.session.get('user_name')
    if not username:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    messages = users.get_and_clear_messages(username)
    logging.info(f"API /api/messages - Retrieved {len(messages)} messages for {username}")
    if messages:
        for msg in messages:
            logging.info(f"  Message: {msg['type']} - {msg['title']}")
    return {"messages": messages}


@app.get("/logout")
def logout(request: Request):
    """Clear user session"""
    request.session.clear()
    return RedirectResponse(url="/Frontend/index.html")


@app.get("/")
def root(request: Request):
    return RedirectResponse(url="/Frontend/index.html")


@app.get("/register/{room_name}")
@require_auth
def register(request: Request, room_name: str):
    # In test mode, don't check if room exists
    if IS_TEST:
        return ['up', 'down', 'stop']
    states = get_room_states(room_name.upper())
    directions = [state['name'] for state in states]
    return directions


@app.get("/control/{room_name}/{action}")
@require_auth
def control_curtain(request: Request, room_name: str, action: str, direction: str = None):
    room_name = room_name.upper()
    
    # In test mode, just return success
    if IS_TEST:
        username = request.session.get('user_name')
        if username:
            users.add_room(username, room_name)
        return {"status": "success", "message": f"Curtain in room {room_name} {action} command sent."}
    
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
        
        # Track room for user
        username = request.session.get('user_name')
        if username:
            try:
                users.add_room(username, room_name)
            except Exception as e:
                logging.error(f"Failed to track room: {e}")
        
        return {"status": "success", "message": f"Curtain in room {room_name} {action} command sent successfully."}
    else:
        raise HTTPException(status_code=res.status_code, detail=f"Failed to send command {res.text}")


@app.get("/stats/all")
@require_auth
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
        
        # Check if user is NEW before creating
        is_new_user = not users.user_exists(username)
        
        # Save user to premium service
        users.get_or_create_user(username)
        
        # Process pending referral ONLY if this is a new user
        pending_referral = request.session.get('pending_referral')
        if pending_referral and pending_referral != username and is_new_user:
            users.process_referral(pending_referral, username)
            users.add_points(pending_referral, 20)  # Grant 20 points for referral
            
            # Add success messages to both users
            users.add_message(
                pending_referral,
                "success",
                "Congratulations!",
                f"{username} just signed up using your referral link! You got 20 points (you need 60 points to get Premium)! ✨"
            )
            users.add_message(
                username,
                "success",
                "Thank You!",
                f"{pending_referral} shared their referral link with you. They just earned 20 points thanks to you! 🎉"
            )
            
            logging.info(f"Processed referral for {pending_referral} from NEW user {username}")
            request.session.pop('pending_referral', None)
        
        logging.info(f"Successfully authenticated user: {username}")

        # Redirect to home page after successful login
        return RedirectResponse(url="/Frontend/index.html")

    except Exception as e:
        logging.error(f"Unexpected error in auth callback: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Authentication error: {str(e)}")


# ============== Premium Endpoints ==============

@app.get("/api/user/profile")
@require_auth
def get_user_profile(request: Request):
    """Get the current user's profile including premium status."""
    username = request.session.get('user_name')
    
    if not username:
        raise HTTPException(status_code=401, detail="User not found in session")
    
    user = users.get_user(username)
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    return {
        "username": username,
        "is_premium": user['is_premium'],
        "rooms": user['rooms']
    }


@app.get("/api/premium/status")
@require_auth
def get_premium_status(request: Request):
    """Check if the current user has premium status."""
    username = request.session.get('user_name')
    
    if not username:
        raise HTTPException(status_code=401, detail="User not found in session")
    
    return {
        "is_premium": users.is_premium(username),
        "rooms": users.get_rooms(username)
    }


@app.get("/api/user/rooms")
@require_auth
def get_user_rooms(request: Request):
    """Get list of rooms the user has controlled."""
    username = request.session.get('user_name')
    
    if not username:
        raise HTTPException(status_code=401, detail="User not found in session")
    
    return {
        "rooms": users.get_rooms(username)
    }


@app.get("/api/user/referral")
@require_auth
def get_referral_link(request: Request):
    """Get the user's unique referral link."""
    username = request.session.get('user_name')
    
    if not username:
        raise HTTPException(status_code=401, detail="User not found in session")
    
    referral_code = users.get_referral_code(username)
    
    return {
        "referral_code": referral_code,
        "referral_link": f"/referral/{referral_code}"
    }


@app.get("/referral/{code}")
def handle_referral(request: Request, code: str):
    """Handle referral link - grant premium to referrer when a new user signs up."""
    referrer_username = users.get_username_from_referral(code)
    
    if not referrer_username:
        logging.warning(f"Invalid referral code: {code}")
        return RedirectResponse(url="/Frontend/index.html")
    
    # Check if current user is already logged in
    current_user = request.session.get('user_name')
    
    if current_user:
        # User is logged in - if they're different from referrer and NEW, grant premium to referrer
        if current_user != referrer_username:
            is_new_user = not users.user_exists(current_user)
            logging.info(f"Referral check: current_user={current_user}, referrer={referrer_username}, is_new={is_new_user}")
            if is_new_user:
                users.process_referral(referrer_username, current_user)
                users.add_points(referrer_username, 20)  # Grant 20 points for referral
                
                # Add success messages to both users
                users.add_message(
                    referrer_username,
                    "success",
                    "Congratulations!",
                    f"{current_user} just signed up using your referral link! You got 20 points (you need 60 points to get Premium)! ✨"
                )
                users.add_message(
                    current_user,
                    "success",
                    "Thank You!",
                    f"{referrer_username} shared their referral link with you. They just earned 20 points thanks to you! 🎉"
                )
                
                logging.info(f"NEW user {current_user} used referral from {referrer_username}")
            else:
                # Existing user tried to use referral - send warning message
                logging.info(f"Adding warning message to {current_user} about {referrer_username}")
                users.add_message(
                    current_user,
                    "warning",
                    "Already Registered",
                    f"You can't give premium to {referrer_username} because you are not a new user. Referral links only work for first-time sign-ups. 🙏"
                )
                logging.info(f"Existing user {current_user} tried to use referral from {referrer_username} - warning message added")
        return RedirectResponse(url="/Frontend/index.html")
    
    # User not logged in - store referral and show message on home page
    request.session['pending_referral'] = referrer_username
    return RedirectResponse(url=f"/Frontend/index.html?pendingReferral={referrer_username}")


# ============== Chat Endpoints ==============

@app.get("/api/chat/messages")
@require_auth
def get_chat_messages(request: Request):
    """Get all chat messages."""
    messages = users.get_chat_messages()
    return {"messages": messages}


@app.post("/api/chat/send")
@require_auth
def send_chat_message(request: Request, message: dict):
    """Send a chat message."""
    username = request.session.get('user_name')
    
    if not username:
        raise HTTPException(status_code=401, detail="User not found in session")
    
    message_text = message.get('message', '').strip()
    
    if not message_text:
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    
    if len(message_text) > 500:
        raise HTTPException(status_code=400, detail="Message too long (max 500 characters)")
    
    is_premium = users.is_premium(username)
    users.add_chat_message(username, message_text, is_premium)
    
    return {"status": "success", "message": "Message sent"}


# ============== Admin Endpoints ==============

@app.get("/api/admin/users")
@require_admin
def get_all_users_admin(request: Request):
    """Get all users data (admin only)."""
    all_users = users.get_all_users()
    return {"users": all_users}


@app.get("/api/admin/grant-points/{username}/{points}")
@require_admin
def grant_points_admin(request: Request, username: str, points: int):
    """Grant points to a user (admin only)."""
    if points < 0:
        raise HTTPException(status_code=400, detail="Points must be positive")
    
    if not users.user_exists(username):
        raise HTTPException(status_code=404, detail=f"User {username} not found")
    
    users.add_points(username, points)
    
    return {
        "status": "success",
        "message": f"Granted {points} points to {username}",
        "new_total": users.get_points(username)
    }


@app.post("/api/admin/send-message")
@require_admin
def send_message_admin(request: Request, message_data: dict):
    """Send a message to a user (admin only)."""
    username = message_data.get('username', '').strip()
    message_type = message_data.get('type', 'success')
    title = message_data.get('title', '').strip()
    text = message_data.get('text', '').strip()
    
    if not username:
        raise HTTPException(status_code=400, detail="Username is required")
    
    if not users.user_exists(username):
        raise HTTPException(status_code=404, detail=f"User {username} not found")
    
    if message_type not in ['success', 'warning', 'failure']:
        raise HTTPException(status_code=400, detail="Message type must be 'success', 'warning', or 'failure'")
    
    if not title or not text:
        raise HTTPException(status_code=400, detail="Title and text are required")
    
    users.add_message(username, message_type, title, text)
    
    return {
        "status": "success",
        "message": f"Message sent to {username}"
    }
