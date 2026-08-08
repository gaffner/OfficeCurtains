"""Advertising slot management.

Anyone can upload a banner, point it at a URL and choose how long it runs, up
to a day. Campaigns are shown one at a time and queue up behind each other,
so a new advertiser starts the moment the one in front of them finishes
rather than competing for the same slot.

Confirmation codes are still supported (see `python ads.py new-codes`) but are
off by default; set AD_REQUIRE_CODE=1 to make campaigns wait for one. They are
treated like secrets either way: stored only as hashes and guarded by a per-IP
attempt limit.

Backed by SQLite, like the rest of the app's small stores.
"""

import hashlib
import io
import json
import logging
import os
import re
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from urllib.parse import urlparse

from PIL import Image, ImageOps, UnidentifiedImageError

DB_FILE = os.getenv('ADS_DB', 'ads.db')

# Banners live under the Frontend mount so they are served as static files.
BANNER_DIR = os.getenv('AD_BANNER_DIR', os.path.join('Frontend', 'ads'))
BANNER_URL_PREFIX = '/Frontend/ads/'

# An ad runs for at most a day. Short slots keep the queue moving while we
# find out whether anyone wants to advertise here at all.
MAX_HOURS = 24
DEFAULT_HOURS = 24
MAX_UPLOAD_BYTES = 5 * 1024 * 1024

# The slot renders at 600x90 CSS pixels; store at 2x so it stays sharp on
# high-density screens. Uploads are scaled to fit, never cropped or stretched.
RECOMMENDED_SIZE = (600, 90)
STORED_SIZE = (1200, 180)

ALLOWED_FORMATS = {'PNG', 'JPEG', 'GIF', 'WEBP'}

def _env_flag(name: str, default: bool = False) -> bool:
    """Read a boolean setting. "false"/"0"/"no"/"off"/"" all mean off.

    A plain truthiness check would read the string "false" as True, which is
    exactly the sort of setting that quietly does the opposite of what the
    .env file says.
    """
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {'1', 'true', 'yes', 'on'}


# Uploading is open to everyone. Setting AD_REQUIRE_CODE=1 puts campaigns
# behind a confirmation code again without any other change.
REQUIRE_CODE = _env_flag('AD_REQUIRE_CODE', False)

SUPPORT_WHATSAPP = os.getenv('AD_SUPPORT_WHATSAPP', '94764194876')

# Redemption codes: 16 characters from a 32 character alphabet is 80 bits of
# entropy, so guessing is hopeless even without the rate limit below.
CODE_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'  # no I, O, 0, 1
CODE_LENGTH = 16
CODE_GROUP = 4

# Brute force protection for code entry. The codes themselves carry 80 bits
# of entropy, so this only has to stop someone hammering the endpoint - it can
# be generous enough that an advertiser mistyping their code never trips it.
MAX_FAILED_ATTEMPTS = 100
ATTEMPT_WINDOW = timedelta(minutes=15)

# Only start warning about the lockout when it is actually close, otherwise
# every typo reports "96 attempts left" and reads like a threat.
ATTEMPTS_WARNING_THRESHOLD = 10

# Drafts that were never published are cleaned up so uploads do not pile up.
DRAFT_RETENTION = timedelta(days=7)

# Clicks are appended here as one JSON object per line, so the raw record
# survives independently of the database.
CLICK_LOG = os.getenv('AD_CLICK_LOG', 'ad_clicks.log')

# Admin sign-in. Never hard-coded: with no password set the page stays off.
ADMIN_USERNAME = os.getenv('ADMIN_USERNAME', '')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', '')

# A password is far weaker than an 80 bit code, so its allowance is far
# tighter than MAX_FAILED_ATTEMPTS.
MAX_ADMIN_ATTEMPTS = 10


class AdError(Exception):
    """Raised for problems that should be reported back to the advertiser."""


class RateLimited(AdError):
    """Raised when too many wrong attempts have come from one address."""

    def __init__(self, retry_after_seconds: int, subject: str = 'codes'):
        self.retry_after_seconds = retry_after_seconds
        minutes = max(1, round(retry_after_seconds / 60))
        super().__init__(
            f"Too many incorrect {subject}. Try again in about {minutes} minute(s)."
        )


@contextmanager
def _get_db():
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
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
        finally:
            conn.close()
    except sqlite3.OperationalError as e:
        logging.warning(f"Could not set WAL journal mode for ads DB: {e}")


def init_db():
    """Create the schema and the banner directory."""
    os.makedirs(BANNER_DIR, exist_ok=True)
    _enable_wal()

    with _get_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ad_campaigns (
                id TEXT PRIMARY KEY,
                banner_file TEXT NOT NULL,
                target_url TEXT NOT NULL,
                days INTEGER NOT NULL,
                price REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'draft',
                created_at TEXT NOT NULL,
                activated_at TEXT,
                starts_at TEXT,
                ends_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ad_codes (
                code_hash TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                used_at TEXT,
                campaign_id TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS redeem_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ip TEXT NOT NULL,
                attempted_at TEXT NOT NULL,
                success INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_attempts_ip_time "
            "ON redeem_attempts(ip, attempted_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_campaigns_live "
            "ON ad_campaigns(status, ends_at)"
        )

        _migrate(conn)


def _add_column(conn, table: str, column: str, definition: str):
    """Add a column unless it is already there.

    Guarded rather than checked first, because all four gunicorn workers run
    this at once and any of them may win the race.
    """
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    except sqlite3.OperationalError as e:
        if 'duplicate column name' not in str(e).lower():
            raise


def _migrate(conn):
    """Bring an older ads.db up to the current schema."""
    # Campaigns were measured in days before the slot was capped at 24 hours.
    _add_column(conn, 'ad_campaigns', 'hours', 'INTEGER')
    conn.execute(
        "UPDATE ad_campaigns SET hours = days * 24 WHERE hours IS NULL"
    )

    _add_column(conn, 'ad_campaigns', 'clicks', 'INTEGER NOT NULL DEFAULT 0')
    _add_column(conn, 'ad_campaigns', 'impressions', 'INTEGER NOT NULL DEFAULT 0')

    # Code entry and admin sign-in share the attempt table.
    _add_column(conn, 'redeem_attempts', 'scope', "TEXT NOT NULL DEFAULT 'code'")

    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_attempts_scope "
        "ON redeem_attempts(scope, ip, attempted_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_campaigns_schedule "
        "ON ad_campaigns(status, starts_at, ends_at)"
    )


# ---------------------------------------------------------------- codes

def _normalise_code(code: str) -> str:
    """Accept the code however it was typed: spaces, dashes, any case."""
    return re.sub(r'[^A-Z0-9]', '', (code or '').upper())


def _hash_code(code: str) -> str:
    return hashlib.sha256(_normalise_code(code).encode()).hexdigest()


def _format_code(raw: str) -> str:
    return '-'.join(raw[i:i + CODE_GROUP] for i in range(0, len(raw), CODE_GROUP))


def generate_codes(count: int = 1) -> list:
    """Mint new redemption codes, returning the plain text exactly once.

    Only the hash is stored, so a code that is not written down here cannot be
    recovered later.
    """
    codes = []
    with _get_db() as conn:
        for _ in range(count):
            raw = ''.join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
            conn.execute(
                "INSERT INTO ad_codes (code_hash, created_at) VALUES (?, ?)",
                (_hash_code(raw), datetime.now().isoformat())
            )
            codes.append(_format_code(raw))
    return codes


def _check_rate_limit(conn, ip: str, scope: str = 'code', limit: int = None,
                      subject: str = 'codes'):
    limit = MAX_FAILED_ATTEMPTS if limit is None else limit
    window_start = (datetime.now() - ATTEMPT_WINDOW).isoformat()
    rows = conn.execute(
        """
        SELECT attempted_at FROM redeem_attempts
        WHERE scope = ? AND ip = ? AND success = 0 AND attempted_at > ?
        ORDER BY attempted_at ASC
        """,
        (scope, ip, window_start)
    ).fetchall()

    if len(rows) < limit:
        return

    # Locked out until the oldest failure in the window ages out.
    oldest = datetime.fromisoformat(rows[0]['attempted_at'])
    retry_at = oldest + ATTEMPT_WINDOW
    raise RateLimited(
        max(1, int((retry_at - datetime.now()).total_seconds())), subject
    )


def _record_attempt(conn, ip: str, success: bool, scope: str = 'code'):
    conn.execute(
        "INSERT INTO redeem_attempts (ip, attempted_at, success, scope) "
        "VALUES (?, ?, ?, ?)",
        (ip, datetime.now().isoformat(), 1 if success else 0, scope)
    )


# ---------------------------------------------------------------- banners

def store_banner(raw: bytes, filename: str = '') -> str:
    """Validate, normalise and save an uploaded banner.

    The upload is re-encoded rather than stored as sent: it guarantees the file
    really is an image (so nothing dressed up as one can be served back), drops
    any metadata, and scales it to the slot without stretching or cropping.
    """
    if not raw:
        raise AdError("Please choose a banner image.")

    if len(raw) > MAX_UPLOAD_BYTES:
        limit = MAX_UPLOAD_BYTES // (1024 * 1024)
        raise AdError(f"That image is larger than {limit} MB. Please upload a smaller file.")

    try:
        with Image.open(io.BytesIO(raw)) as probe:
            image_format = probe.format
            probe.verify()
    except (UnidentifiedImageError, OSError, ValueError):
        raise AdError("That file does not look like an image. Use PNG, JPEG, GIF or WebP.")

    if image_format not in ALLOWED_FORMATS:
        raise AdError(f"{image_format} images are not supported. Use PNG, JPEG, GIF or WebP.")

    # verify() leaves the file object unusable, so open it again to work with.
    try:
        image = Image.open(io.BytesIO(raw))
        image = ImageOps.exif_transpose(image)
        image = ImageOps.contain(image, STORED_SIZE, Image.LANCZOS)
    except (OSError, ValueError) as e:
        raise AdError("That image could not be processed. Try a different file.") from e

    has_alpha = image.mode in ('RGBA', 'LA') or (
        image.mode == 'P' and 'transparency' in image.info
    )

    os.makedirs(BANNER_DIR, exist_ok=True)
    name = secrets.token_hex(16)

    if has_alpha:
        image = image.convert('RGBA')
        name += '.png'
        save_args = {'format': 'PNG', 'optimize': True}
    else:
        image = image.convert('RGB')
        name += '.jpg'
        save_args = {'format': 'JPEG', 'quality': 85, 'optimize': True}

    image.save(os.path.join(BANNER_DIR, name), **save_args)
    logging.info(f"Stored ad banner {name} from upload {filename!r}")
    return name


def _delete_banner(banner_file: str):
    try:
        os.remove(os.path.join(BANNER_DIR, banner_file))
    except OSError:
        pass


# ---------------------------------------------------------------- campaigns

SCHEME_RE = re.compile(r'^[a-zA-Z][a-zA-Z0-9+.\-]*:')


def _validate_target_url(url: str) -> str:
    url = (url or '').strip()
    if not url:
        raise AdError("Please add the link the banner should open.")

    if len(url) > 2000:
        raise AdError("That link is too long.")

    if any(ch.isspace() for ch in url):
        raise AdError("That link contains spaces. Please check it and try again.")

    # Only assume https for a bare host. Testing for '://' instead would let
    # "javascript:alert(1)" through, since it has a scheme but no slashes.
    if SCHEME_RE.match(url):
        if urlparse(url).scheme.lower() not in ('http', 'https'):
            raise AdError("The link must be a normal http:// or https:// address.")
    else:
        url = 'https://' + url

    try:
        host = urlparse(url).hostname
    except ValueError:
        host = None

    if not host or ('.' not in host and host != 'localhost'):
        raise AdError("Enter a full website address, for example https://example.com")

    return url


def _validate_hours(hours) -> int:
    try:
        hours = int(hours)
    except (TypeError, ValueError):
        raise AdError("Choose how long the ad should run.")

    if hours < 1 or hours > MAX_HOURS:
        raise AdError(f"Choose between 1 and {MAX_HOURS} hours.")

    return hours


def create_draft(raw_image: bytes, filename: str, target_url: str, hours) -> dict:
    """Store an uploaded banner and hold it as an unpublished draft."""
    target_url = _validate_target_url(target_url)
    hours = _validate_hours(hours)
    banner_file = store_banner(raw_image, filename)

    campaign_id = secrets.token_urlsafe(12)

    with _get_db() as conn:
        conn.execute(
            """
            INSERT INTO ad_campaigns
                (id, banner_file, target_url, days, hours, price, status, created_at)
            VALUES (?, ?, ?, ?, ?, 0, 'draft', ?)
            """,
            (campaign_id, banner_file, target_url,
             max(1, round(hours / 24)), hours, datetime.now().isoformat())
        )

    _cleanup_stale_drafts()
    return get_campaign(campaign_id)


def _queue_tail(conn, now: datetime) -> datetime:
    """When the last campaign already in the queue finishes.

    Ads run one at a time, so a new campaign starts where the queue ends
    rather than fighting the current one for the slot.
    """
    tail = conn.execute(
        "SELECT MAX(ends_at) FROM ad_campaigns WHERE status = 'active' AND ends_at > ?",
        (now.isoformat(),)
    ).fetchone()[0]

    if not tail:
        return now

    try:
        return max(now, datetime.fromisoformat(tail))
    except ValueError:
        return now


def publish_campaign(campaign_id: str) -> dict:
    """Put a draft into the queue.

    Scheduling happens inside one IMMEDIATE transaction so two uploads landing
    together cannot both claim the same slot.
    """
    conn = sqlite3.connect(DB_FILE, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.isolation_level = None
    try:
        conn.execute("BEGIN IMMEDIATE")

        campaign = conn.execute(
            "SELECT * FROM ad_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()

        if campaign is None:
            conn.execute("COMMIT")
            raise AdError("That campaign could not be found. Please start again.")

        if campaign['status'] == 'active':
            conn.execute("COMMIT")
            return get_campaign(campaign_id)

        now = datetime.now()
        starts_at = _queue_tail(conn, now)
        ends_at = starts_at + timedelta(hours=campaign['hours'])

        conn.execute(
            """
            UPDATE ad_campaigns
            SET status = 'active', activated_at = ?, starts_at = ?, ends_at = ?
            WHERE id = ?
            """,
            (now.isoformat(), starts_at.isoformat(), ends_at.isoformat(), campaign_id)
        )
        conn.execute("COMMIT")
    except (AdError, sqlite3.Error):
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise
    finally:
        conn.close()

    logging.info(
        f"Ad campaign {campaign_id} queued for {campaign['hours']}h "
        f"from {starts_at.isoformat()}"
    )
    return get_campaign(campaign_id)


def redeem_code(campaign_id: str, code: str, ip: str) -> dict:
    """Activate a draft campaign with a valid, unused code.

    The lookup and the update share one IMMEDIATE transaction so a code cannot
    be spent twice by two requests arriving together.
    """
    ip = ip or 'unknown'

    conn = sqlite3.connect(DB_FILE, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.isolation_level = None
    try:
        conn.execute("BEGIN IMMEDIATE")

        _check_rate_limit(conn, ip)

        campaign = conn.execute(
            "SELECT * FROM ad_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()

        if campaign is None:
            _record_attempt(conn, ip, False)
            conn.execute("COMMIT")
            raise AdError("That campaign could not be found. Please start again.")

        if campaign['status'] == 'active':
            conn.execute("COMMIT")
            return get_campaign(campaign_id)

        matched = conn.execute(
            "SELECT code_hash FROM ad_codes WHERE code_hash = ? AND used_at IS NULL",
            (_hash_code(code),)
        ).fetchone()

        if matched is None:
            _record_attempt(conn, ip, False)
            remaining = _remaining_attempts(conn, ip)
            conn.execute("COMMIT")
            message = "That code is not valid or has already been used."
            if 0 < remaining <= ATTEMPTS_WARNING_THRESHOLD:
                message += f" {remaining} attempt(s) left before a short lockout."
            raise AdError(message)

        now = datetime.now()
        starts_at = _queue_tail(conn, now)
        ends_at = starts_at + timedelta(hours=campaign['hours'])

        conn.execute(
            "UPDATE ad_codes SET used_at = ?, campaign_id = ? WHERE code_hash = ?",
            (now.isoformat(), campaign_id, matched['code_hash'])
        )
        conn.execute(
            """
            UPDATE ad_campaigns
            SET status = 'active', activated_at = ?, starts_at = ?, ends_at = ?
            WHERE id = ?
            """,
            (now.isoformat(), starts_at.isoformat(), ends_at.isoformat(), campaign_id)
        )
        _record_attempt(conn, ip, True)
        conn.execute("COMMIT")
    except (AdError, sqlite3.Error):
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise
    finally:
        conn.close()

    logging.info(f"Ad campaign {campaign_id} activated for {campaign['hours']}h")
    return get_campaign(campaign_id)


def _remaining_attempts(conn, ip: str, scope: str = 'code', limit: int = None) -> int:
    limit = MAX_FAILED_ATTEMPTS if limit is None else limit
    window_start = (datetime.now() - ATTEMPT_WINDOW).isoformat()
    used = conn.execute(
        """
        SELECT COUNT(*) FROM redeem_attempts
        WHERE scope = ? AND ip = ? AND success = 0 AND attempted_at > ?
        """,
        (scope, ip, window_start)
    ).fetchone()[0]
    return max(0, limit - used)


def check_admin_login(username: str, password: str, ip: str) -> bool:
    """Verify admin credentials, refusing to answer a hammering client.

    The attempt is recorded before the answer is returned so a lockout still
    applies when the caller simply retries in a loop.
    """
    if not ADMIN_PASSWORD:
        raise AdError("The admin page is not configured.")

    ip = ip or 'unknown'

    with _get_db() as conn:
        _check_rate_limit(conn, ip, scope='admin', limit=MAX_ADMIN_ATTEMPTS,
                          subject='sign-in attempts')

        # compare_digest on both halves, so neither the username nor the
        # password can be recovered by timing the response.
        ok = (secrets.compare_digest(username or '', ADMIN_USERNAME)
              & secrets.compare_digest(password or '', ADMIN_PASSWORD))

        _record_attempt(conn, ip, ok, scope='admin')

    if not ok:
        logging.warning(f"Failed admin sign-in from {ip}")

    return ok


def get_campaign(campaign_id: str) -> dict:
    with _get_db() as conn:
        row = conn.execute(
            "SELECT * FROM ad_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()

    if row is None:
        raise AdError("That campaign could not be found.")

    return _campaign_payload(row)


def _campaign_payload(row) -> dict:
    return {
        'id': row['id'],
        'banner_url': BANNER_URL_PREFIX + row['banner_file'],
        'target_url': row['target_url'],
        'hours': row['hours'],
        'max_hours': MAX_HOURS,
        'recommended_size': list(RECOMMENDED_SIZE),
        'status': row['status'],
        'starts_at': row['starts_at'],
        'ends_at': row['ends_at'],
        'clicks': row['clicks'],
        'impressions': row['impressions'],
        'support_whatsapp': SUPPORT_WHATSAPP,
    }


def get_config() -> dict:
    """Everything the wizard needs to describe the slot to an advertiser."""
    return {
        'max_hours': MAX_HOURS,
        'default_hours': DEFAULT_HOURS,
        'recommended_width': RECOMMENDED_SIZE[0],
        'recommended_height': RECOMMENDED_SIZE[1],
        'max_upload_mb': MAX_UPLOAD_BYTES // (1024 * 1024),
        'allowed_formats': sorted(ALLOWED_FORMATS),
        'require_code': REQUIRE_CODE,
        'support_whatsapp': SUPPORT_WHATSAPP,
    }


def get_active_ad() -> dict:
    """The campaign holding the slot right now, or None when it is free.

    Only one ad runs at a time; the rest wait their turn, so this is a lookup
    rather than a choice.
    """
    now = datetime.now().isoformat()
    with _get_db() as conn:
        row = conn.execute(
            """
            SELECT * FROM ad_campaigns
            WHERE status = 'active' AND starts_at <= ? AND ends_at > ?
            ORDER BY starts_at ASC LIMIT 1
            """,
            (now, now)
        ).fetchone()

        if row is None:
            return None

        conn.execute(
            "UPDATE ad_campaigns SET impressions = impressions + 1 WHERE id = ?",
            (row['id'],)
        )

    return {
        'id': row['id'],
        'banner_url': BANNER_URL_PREFIX + row['banner_file'],
        'click_url': f"/ad/click/{row['id']}",
        'target_url': row['target_url'],
        'ends_at': row['ends_at'],
    }


def get_queue(limit: int = 20) -> dict:
    """The ad on air now and the ones waiting behind it."""
    now = datetime.now()
    now_iso = now.isoformat()

    with _get_db() as conn:
        current = conn.execute(
            """
            SELECT * FROM ad_campaigns
            WHERE status = 'active' AND starts_at <= ? AND ends_at > ?
            ORDER BY starts_at ASC LIMIT 1
            """,
            (now_iso, now_iso)
        ).fetchone()

        upcoming = conn.execute(
            """
            SELECT * FROM ad_campaigns
            WHERE status = 'active' AND starts_at > ?
            ORDER BY starts_at ASC LIMIT ?
            """,
            (now_iso, limit)
        ).fetchall()

    def slot(row):
        return {
            'id': row['id'],
            'banner_url': BANNER_URL_PREFIX + row['banner_file'],
            'target_url': row['target_url'],
            'hours': row['hours'],
            'starts_at': row['starts_at'],
            'ends_at': row['ends_at'],
        }

    return {
        'now': now_iso,
        'current': slot(current) if current else None,
        'upcoming': [slot(r) for r in upcoming],
        'free_from': _queue_tail_readonly(now),
        'max_hours': MAX_HOURS,
    }


def _queue_tail_readonly(now: datetime) -> str:
    with _get_db() as conn:
        return _queue_tail(conn, now).isoformat()


def record_click(campaign_id: str) -> str:
    """Count a click and return where the visitor should be sent.

    The click is appended to a plain log file as well as counted, so the raw
    record survives even if the database is ever rebuilt.
    """
    with _get_db() as conn:
        row = conn.execute(
            "SELECT target_url FROM ad_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()

        if row is None:
            raise AdError("That advert is no longer available.")

        conn.execute(
            "UPDATE ad_campaigns SET clicks = clicks + 1 WHERE id = ?", (campaign_id,)
        )

    _append_click_log(campaign_id, row['target_url'])
    return row['target_url']


def _append_click_log(campaign_id: str, target_url: str):
    """Append one JSON line per click.

    Nothing identifying about the visitor is written down: the site has no
    accounts and this only needs to answer "how many".
    """
    entry = json.dumps({
        'at': datetime.now().isoformat(timespec='seconds'),
        'campaign_id': campaign_id,
        'target_url': target_url,
    })

    try:
        # One short line opened in append mode, so concurrent workers cannot
        # interleave halves of a record.
        with open(CLICK_LOG, 'a', encoding='utf-8') as handle:
            handle.write(entry + '\n')
    except OSError as e:
        logging.error(f"Could not write to the ad click log: {e}")


def read_click_log(limit: int = 200) -> list:
    """The most recent clicks, newest first."""
    try:
        with open(CLICK_LOG, encoding='utf-8') as handle:
            lines = handle.readlines()[-limit:]
    except FileNotFoundError:
        return []
    except OSError as e:
        logging.error(f"Could not read the ad click log: {e}")
        return []

    entries = []
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except ValueError:
            continue

    return entries


def get_admin_stats() -> dict:
    """Every campaign with its impressions, clicks and click-through rate."""
    now = datetime.now().isoformat()

    with _get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM ad_campaigns ORDER BY created_at DESC"
        ).fetchall()

    campaigns = []
    for row in rows:
        if row['status'] != 'active':
            state = 'draft'
        elif row['ends_at'] and row['ends_at'] <= now:
            state = 'finished'
        elif row['starts_at'] and row['starts_at'] > now:
            state = 'queued'
        else:
            state = 'on air'

        impressions = row['impressions'] or 0
        clicks = row['clicks'] or 0

        campaigns.append({
            'id': row['id'],
            'state': state,
            'banner_url': BANNER_URL_PREFIX + row['banner_file'],
            'target_url': row['target_url'],
            'hours': row['hours'],
            'created_at': row['created_at'],
            'starts_at': row['starts_at'],
            'ends_at': row['ends_at'],
            'impressions': impressions,
            'clicks': clicks,
            'ctr': (clicks / impressions * 100) if impressions else 0.0,
        })

    totals = {
        'campaigns': len(campaigns),
        'impressions': sum(c['impressions'] for c in campaigns),
        'clicks': sum(c['clicks'] for c in campaigns),
    }
    totals['ctr'] = (
        totals['clicks'] / totals['impressions'] * 100 if totals['impressions'] else 0.0
    )

    return {
        'campaigns': campaigns,
        'totals': totals,
        'recent_clicks': read_click_log(50),
        'click_log': os.path.abspath(CLICK_LOG),
    }


def cancel_campaign(campaign_id: str) -> bool:
    """Take a campaign off air and delete its banner.

    Needed to pull an ad that turns out to be unsuitable, and to clear out
    test campaigns.
    """
    with _get_db() as conn:
        row = conn.execute(
            "SELECT banner_file FROM ad_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()

        if row is None:
            return False

        conn.execute("DELETE FROM ad_campaigns WHERE id = ?", (campaign_id,))

    _delete_banner(row['banner_file'])
    logging.info(f"Ad campaign {campaign_id} cancelled")
    return True


def _cleanup_stale_drafts():
    """Drop unpaid drafts and their uploads after the retention window."""
    cutoff = (datetime.now() - DRAFT_RETENTION).isoformat()
    try:
        with _get_db() as conn:
            stale = conn.execute(
                "SELECT id, banner_file FROM ad_campaigns "
                "WHERE status = 'draft' AND created_at < ?",
                (cutoff,)
            ).fetchall()

            for row in stale:
                _delete_banner(row['banner_file'])
                conn.execute("DELETE FROM ad_campaigns WHERE id = ?", (row['id'],))

        if stale:
            logging.info(f"Removed {len(stale)} unpaid ad draft(s)")
    except sqlite3.Error as e:
        logging.error(f"Could not clean up ad drafts: {e}")


init_db()


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description="Manage advertising codes.")
    sub = parser.add_subparsers(dest='command', required=True)

    new_codes = sub.add_parser('new-codes', help="Mint redemption codes.")
    new_codes.add_argument('count', nargs='?', type=int, default=1)

    sub.add_parser('list', help="Show campaigns.")

    cancel = sub.add_parser('cancel', help="Take a campaign off air.")
    cancel.add_argument('campaign_id')

    args = parser.parse_args()

    if args.command == 'new-codes':
        print("Write these down now - only their hashes are stored:\n")
        for code in generate_codes(args.count):
            print(f"  {code}")
    elif args.command == 'cancel':
        if cancel_campaign(args.campaign_id):
            print(f"Campaign {args.campaign_id} cancelled and its banner deleted.")
        else:
            print(f"No campaign with id {args.campaign_id}.")
            raise SystemExit(1)
    else:
        with _get_db() as conn:
            campaigns = conn.execute(
                "SELECT id, status, hours, clicks, impressions, starts_at, ends_at, "
                "target_url FROM ad_campaigns ORDER BY created_at DESC"
            ).fetchall()

        if not campaigns:
            print("No campaigns yet.")
        for row in campaigns:
            window = f"{(row['starts_at'] or '-')[:16]} -> {(row['ends_at'] or '-')[:16]}"
            print(f"{row['id']}  {row['status']:<7} {row['hours']:>3}h  "
                  f"{row['impressions']:>6} views {row['clicks']:>5} clicks  "
                  f"{window}  {row['target_url']}")
