"""
Users module - manages user preferences, premium status, and favorite rooms.
Uses a JSON file for storage.
"""

import json
import os
import logging
from typing import Optional, List

USERS_FILE = os.getenv('USERS_FILE', 'users.json')


def _load_users() -> dict:
    """Load users from JSON file."""
    if not os.path.exists(USERS_FILE):
        return {}
    try:
        with open(USERS_FILE, 'r') as f:
            users = json.load(f)
            # Migrate old users to have messages field
            needs_save = False
            for username, user_data in users.items():
                if 'messages' not in user_data:
                    user_data['messages'] = []
                    needs_save = True
                # Remove old notification fields
                if 'pending_premium_from' in user_data:
                    del user_data['pending_premium_from']
                    needs_save = True
                if 'referred_by' in user_data:
                    del user_data['referred_by']
                    needs_save = True
            if needs_save:
                with open(USERS_FILE, 'w') as f:
                    json.dump(users, f, indent=2)
                logging.info("Migrated users to message queue system")
            return users
    except (json.JSONDecodeError, IOError):
        return {}


def _save_users(users: dict):
    """Save users to JSON file."""
    with open(USERS_FILE, 'w') as f:
        json.dump(users, f, indent=2)


def get_or_create_user(username: str) -> dict:
    """Get existing user or create a new one. Returns user dict."""
    users = _load_users()
    
    if username not in users:
        users[username] = {
            "is_premium": False,
            "rooms": [],
            "messages": []
        }
        _save_users(users)
        logging.info(f"Created new user: {username}")
    
    return {"username": username, **users[username]}


def get_user(username: str) -> Optional[dict]:
    """Get user by username. Returns None if not found."""
    users = _load_users()
    if username in users:
        return {"username": username, **users[username]}
    return None


def user_exists(username: str) -> bool:
    """Check if user exists in the system."""
    users = _load_users()
    return username in users


def is_premium(username: str) -> bool:
    """Check if user has premium status."""
    users = _load_users()
    return users.get(username, {}).get("is_premium", False)


def set_premium(username: str, value: bool = True):
    """Set user's premium status."""
    users = _load_users()
    if username in users:
        users[username]["is_premium"] = value
        _save_users(users)
        logging.info(f"Set premium={value} for user: {username}")


def add_room(username: str, room: str):
    """Add a room to user's controlled rooms list (if not already there)."""
    users = _load_users()
    if username not in users:
        users[username] = {"is_premium": False, "rooms": []}
    
    room = room.upper()
    if room not in users[username]["rooms"]:
        users[username]["rooms"].append(room)
        _save_users(users)
        logging.info(f"Added room {room} to user {username}")


def get_rooms(username: str) -> List[str]:
    """Get list of rooms user has controlled."""
    users = _load_users()
    return users.get(username, {}).get("rooms", [])


def get_all_users() -> dict:
    """Get all users (for admin purposes)."""
    return _load_users()


def get_referral_code(username: str) -> str:
    """Generate a simple referral code from username (base64 encoded)."""
    import base64
    return base64.urlsafe_b64encode(username.encode()).decode().rstrip('=')


def get_username_from_referral(code: str) -> Optional[str]:
    """Decode a referral code back to username."""
    import base64
    try:
        # Add padding back
        padding = 4 - len(code) % 4
        if padding != 4:
            code += '=' * padding
        return base64.urlsafe_b64decode(code.encode()).decode()
    except Exception:
        return None


def process_referral(referrer_username: str, new_user: str) -> bool:
    """Grant premium to the referrer. Returns True if successful."""
    users = _load_users()
    if referrer_username in users:
        users[referrer_username]["is_premium"] = True
        _save_users(users)
        logging.info(f"Granted premium to {referrer_username} via referral from {new_user}")
        return True
    return False


def add_message(username: str, message_type: str, title: str, text: str):
    """Add a message to user's message queue.
    
    Args:
        username: The user to send the message to
        message_type: 'success', 'failure', or 'warning'
        title: Message title
        text: Message body text
    """
    users = _load_users()
    if username not in users:
        users[username] = {"is_premium": False, "rooms": [], "messages": []}
        logging.info(f"Created new user {username} while adding message")
    
    message = {
        "type": message_type,
        "title": title,
        "text": text
    }
    
    users[username]["messages"].append(message)
    _save_users(users)
    logging.info(f"Added {message_type} message to {username}: '{title}' - Total messages for user: {len(users[username]['messages'])}")


def get_and_clear_messages(username: str) -> list:
    """Get all pending messages for user and clear them."""
    users = _load_users()
    if username in users:
        messages = users[username].get("messages", [])
        logging.info(f"get_and_clear_messages for {username}: Found {len(messages)} messages")
        if messages:
            logging.info(f"Messages for {username}: {messages}")
            users[username]["messages"] = []
            _save_users(users)
            logging.info(f"Cleared {len(messages)} messages for {username}")
        return messages
    logging.info(f"get_and_clear_messages: User {username} not found")
    return []
