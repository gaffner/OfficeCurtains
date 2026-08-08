"""
Statistics module - tracks curtain usage per room.

Counts are stored per room per day so that history is preserved, but the
reporting API aggregates across the whole history ("all statistics") rather
than exposing a single day.

Backed by SQLite. Usage recorded by earlier versions of the app lives in
`stats/stats_<date>.csv` files; those are imported once on startup so the
history survives the move away from CSV.
"""

import csv
import glob
import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime

DB_FILE = os.getenv('STATS_DB', 'stats.db')

# Legacy CSV files written by the pre-SQLite version.
LEGACY_STATS_DIR = os.getenv('STATS_DIR', 'stats')

ACTIONS = ('up', 'down', 'stop')


@contextmanager
def _get_db():
    """Context manager for database connections."""
    # Every gunicorn worker uses this database, so allow waiting for the lock
    # instead of failing immediately under concurrent access.
    conn = sqlite3.connect(DB_FILE, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _enable_wal():
    """Put the database in WAL mode (a persistent, one-off property)."""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
        finally:
            conn.close()
    except sqlite3.OperationalError as e:
        # Another worker may hold the lock; WAL only needs to be set once.
        logging.warning(f"Could not set WAL journal mode for statistics DB: {e}")


def init_db():
    """Initialize the database schema and import any legacy CSV history."""
    _enable_wal()

    with _get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS room_daily_stats (
                room_number TEXT NOT NULL,
                date TEXT NOT NULL,
                up INTEGER NOT NULL DEFAULT 0,
                down INTEGER NOT NULL DEFAULT 0,
                stop INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (room_number, date)
            );
        """)
        # Tracks which CSV files were already imported, so startup is idempotent.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS imported_csv_files (
                filename TEXT PRIMARY KEY,
                imported_at TEXT NOT NULL
            );
        """)

    _import_legacy_csv_files()
    logging.info("Statistics database initialized")


def _import_legacy_csv_files():
    """Import `stats/stats_<date>.csv` files that have not been imported yet.

    Safe to run concurrently: every worker process runs this at startup, so each
    file is claimed inside an IMMEDIATE transaction and only the worker that
    wins the claim imports it. Without this, parallel workers would double-count
    the historical numbers.
    """
    if not os.path.isdir(LEGACY_STATS_DIR):
        return

    pattern = os.path.join(LEGACY_STATS_DIR, 'stats_*.csv')
    imported = 0

    for filepath in sorted(glob.glob(pattern)):
        filename = os.path.basename(filepath)
        date = filename[len('stats_'):-len('.csv')]

        try:
            datetime.strptime(date, '%Y-%m-%d')
        except ValueError:
            logging.warning(f"Skipping stats file with unexpected name: {filename}")
            continue

        try:
            rows = _read_legacy_csv(filepath)
        except OSError as e:
            logging.error(f"Could not read legacy stats file {filename}: {e}")
            continue

        conn = sqlite3.connect(DB_FILE, timeout=30)
        conn.isolation_level = None  # manage the transaction explicitly
        try:
            conn.execute("BEGIN IMMEDIATE")

            claimed = conn.execute(
                "INSERT OR IGNORE INTO imported_csv_files (filename, imported_at) VALUES (?, ?)",
                (filename, datetime.now().isoformat())
            ).rowcount

            if not claimed:
                # Already imported, by a previous run or another worker.
                conn.execute("ROLLBACK")
                continue

            for room, counts in rows:
                conn.execute(
                    """
                    INSERT INTO room_daily_stats (room_number, date, up, down, stop)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(room_number, date) DO UPDATE SET
                        up = up + excluded.up,
                        down = down + excluded.down,
                        stop = stop + excluded.stop
                    """,
                    (room, date, counts['up'], counts['down'], counts['stop'])
                )

            conn.execute("COMMIT")
            imported += 1
        except sqlite3.Error as e:
            logging.error(f"Failed to import legacy stats file {filename}: {e}")
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
        finally:
            conn.close()

    if imported:
        logging.info(f"Imported {imported} legacy statistics file(s) from {LEGACY_STATS_DIR}")


def _read_legacy_csv(filepath):
    """Parse a legacy CSV into [(room_number, {up, down, stop}), ...]."""
    rows = []
    with open(filepath, newline='', encoding='utf-8') as handle:
        for row in csv.DictReader(handle):
            room = (row.get('room_number') or '').strip().upper()
            if not room:
                continue

            counts = {}
            for action in ACTIONS:
                try:
                    counts[action] = int(row.get(action) or 0)
                except (TypeError, ValueError):
                    counts[action] = 0

            rows.append((room, counts))
    return rows


# Initialize DB on module import
init_db()


def record_action(room_number: str, action: str):
    """Increment the counter for a room/action on today's date."""
    if action not in ACTIONS:
        return

    room_number = (room_number or '').strip().upper()
    if not room_number:
        return

    date = datetime.now().strftime('%Y-%m-%d')

    try:
        with _get_db() as conn:
            # `action` is validated against ACTIONS above, so it is safe to inline.
            conn.execute(
                f"""
                INSERT INTO room_daily_stats (room_number, date, {action})
                VALUES (?, ?, 1)
                ON CONFLICT(room_number, date) DO UPDATE SET {action} = {action} + 1
                """,
                (room_number, date)
            )
    except sqlite3.Error as e:
        # Never let statistics bookkeeping break curtain control.
        logging.error(f"Failed to record statistics for {room_number}/{action}: {e}")


def get_all_statistics() -> dict:
    """Usage for every recorded day, newest first.

    Keeps the response shape the original CSV-backed version used, so the
    statistics page stays the plain per-day table listing it has always been.
    """
    with _get_db() as conn:
        rows = conn.execute(
            """
            SELECT date, room_number, up, down, stop
            FROM room_daily_stats
            ORDER BY date DESC, room_number ASC
            """
        ).fetchall()

        unique_rooms = conn.execute(
            "SELECT COUNT(DISTINCT room_number) FROM room_daily_stats"
        ).fetchone()[0]

    days = []
    for row in rows:
        if not days or days[-1]['raw_date'] != row['date']:
            days.append({
                'date': _format_date(row['date']),
                'raw_date': row['date'],
                'stats': [],
                'room_count': 0,
            })

        days[-1]['stats'].append({
            'room_number': row['room_number'],
            'up': row['up'],
            'down': row['down'],
            'stop': row['stop'],
        })
        days[-1]['room_count'] += 1

    return {
        'data': days,
        'total_unique_rooms': unique_rooms,
    }


def _format_date(date: str) -> str:
    """Render an ISO date the way the page has always displayed it."""
    try:
        return datetime.strptime(date, '%Y-%m-%d').strftime('%A, %B %d, %Y')
    except ValueError:
        return date
