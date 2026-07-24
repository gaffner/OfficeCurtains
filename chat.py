"""
Chat module - stores a simple, anonymous public chat.

There are no user accounts: each message carries a display name that the sender
types in per message. Backed by SQLite. Only the most recent messages are kept.
"""

import os
import logging
import sqlite3
from datetime import datetime
from contextlib import contextmanager

DB_FILE = os.getenv('CHAT_DB', 'chat.db')

# Maximum number of messages retained in the database.
MAX_MESSAGES = 100

# Length limits (also enforced on the server before calling into this module).
MAX_NAME_LENGTH = 40
MAX_MESSAGE_LENGTH = 500


@contextmanager
def _get_db():
    """Context manager for database connections."""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Initialize the database schema."""
    with _get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                message TEXT NOT NULL,
                timestamp TEXT NOT NULL
            );
        """)
    logging.info("Chat database initialized")


# Initialize DB on module import
init_db()


def add_chat_message(name: str, message: str):
    """Add a chat message from an anonymous sender who supplied a display name."""
    name = (name or "Anonymous").strip()[:MAX_NAME_LENGTH] or "Anonymous"
    message = (message or "").strip()[:MAX_MESSAGE_LENGTH]

    timestamp = datetime.now().isoformat()
    with _get_db() as conn:
        conn.execute(
            "INSERT INTO chat_messages (name, message, timestamp) VALUES (?, ?, ?)",
            (name, message, timestamp)
        )
        # Keep only the most recent MAX_MESSAGES messages.
        conn.execute(
            """
            DELETE FROM chat_messages WHERE id NOT IN (
                SELECT id FROM chat_messages ORDER BY id DESC LIMIT ?
            )
            """,
            (MAX_MESSAGES,)
        )
    logging.info(f"Added chat message from {name}")


def get_chat_messages() -> list:
    """Return all chat messages in chronological order."""
    with _get_db() as conn:
        rows = conn.execute(
            "SELECT name, message, timestamp FROM chat_messages ORDER BY id ASC"
        ).fetchall()
    return [dict(row) for row in rows]
