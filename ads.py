"""Advertising slot management.

Advertisers upload a banner, point it at a URL and choose how many days it
should run. Payment is not implemented yet, so a campaign only goes live once
a redemption code is entered. Codes are minted by the site owner (see
`python ads.py new-codes`) and handed out after payment is arranged manually,
which is why they are treated like secrets: stored only as hashes and guarded
by a per-IP attempt limit.

Backed by SQLite, like the rest of the app's small stores.
"""

import hashlib
import io
import logging
import os
import random
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

MAX_DAYS = 14
MAX_UPLOAD_BYTES = 5 * 1024 * 1024

# The slot renders at 600x90 CSS pixels; store at 2x so it stays sharp on
# high-density screens. Uploads are scaled to fit, never cropped or stretched.
RECOMMENDED_SIZE = (600, 90)
STORED_SIZE = (1200, 180)

ALLOWED_FORMATS = {'PNG', 'JPEG', 'GIF', 'WEBP'}

# The site is running as a pilot, so ad slots are not charged for yet. The
# rate below is what they are expected to cost once payment is supported, and
# is shown to advertisers as a heads-up rather than as a bill.
PILOT_MODE = os.getenv('AD_PILOT', '1') != '0'
PRICE_PER_DAY = float(os.getenv('AD_PRICE_PER_DAY', '10'))
CURRENCY = os.getenv('AD_CURRENCY', 'ILS')

SUPPORT_WHATSAPP = os.getenv('AD_SUPPORT_WHATSAPP', '94764194876')

# Redemption codes: 16 characters from a 32 character alphabet is 80 bits of
# entropy, so guessing is hopeless even without the rate limit below.
CODE_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'  # no I, O, 0, 1
CODE_LENGTH = 16
CODE_GROUP = 4

# Brute force protection for code entry.
MAX_FAILED_ATTEMPTS = 5
ATTEMPT_WINDOW = timedelta(minutes=15)

# Drafts that were never paid for are cleaned up so uploads do not pile up.
DRAFT_RETENTION = timedelta(days=7)


class AdError(Exception):
    """Raised for problems that should be reported back to the advertiser."""


class RateLimited(AdError):
    """Raised when too many wrong codes have been entered from one address."""

    def __init__(self, retry_after_seconds: int):
        self.retry_after_seconds = retry_after_seconds
        minutes = max(1, round(retry_after_seconds / 60))
        super().__init__(
            f"Too many incorrect codes. Try again in about {minutes} minute(s)."
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


def _check_rate_limit(conn, ip: str):
    window_start = (datetime.now() - ATTEMPT_WINDOW).isoformat()
    rows = conn.execute(
        """
        SELECT attempted_at FROM redeem_attempts
        WHERE ip = ? AND success = 0 AND attempted_at > ?
        ORDER BY attempted_at ASC
        """,
        (ip, window_start)
    ).fetchall()

    if len(rows) < MAX_FAILED_ATTEMPTS:
        return

    # Locked out until the oldest failure in the window ages out.
    oldest = datetime.fromisoformat(rows[0]['attempted_at'])
    retry_at = oldest + ATTEMPT_WINDOW
    raise RateLimited(max(1, int((retry_at - datetime.now()).total_seconds())))


def _record_attempt(conn, ip: str, success: bool):
    conn.execute(
        "INSERT INTO redeem_attempts (ip, attempted_at, success) VALUES (?, ?, ?)",
        (ip, datetime.now().isoformat(), 1 if success else 0)
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


def _validate_days(days) -> int:
    try:
        days = int(days)
    except (TypeError, ValueError):
        raise AdError("Choose how many days the ad should run.")

    if days < 1 or days > MAX_DAYS:
        raise AdError(f"Choose between 1 and {MAX_DAYS} days.")

    return days


def create_draft(raw_image: bytes, filename: str, target_url: str, days) -> dict:
    """Store an uploaded banner and hold it as an unpaid draft campaign."""
    target_url = _validate_target_url(target_url)
    days = _validate_days(days)
    banner_file = store_banner(raw_image, filename)

    campaign_id = secrets.token_urlsafe(12)
    price = 0.0 if PILOT_MODE else round(days * PRICE_PER_DAY, 2)

    with _get_db() as conn:
        conn.execute(
            """
            INSERT INTO ad_campaigns
                (id, banner_file, target_url, days, price, status, created_at)
            VALUES (?, ?, ?, ?, ?, 'draft', ?)
            """,
            (campaign_id, banner_file, target_url, days, price,
             datetime.now().isoformat())
        )

    _cleanup_stale_drafts()
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
            raise AdError(
                "That code is not valid or has already been used."
                + (f" {remaining} attempt(s) left before a short lockout."
                   if remaining else "")
            )

        now = datetime.now()
        ends_at = now + timedelta(days=campaign['days'])

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
            (now.isoformat(), now.isoformat(), ends_at.isoformat(), campaign_id)
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

    logging.info(f"Ad campaign {campaign_id} activated for {campaign['days']} day(s)")
    return get_campaign(campaign_id)


def _remaining_attempts(conn, ip: str) -> int:
    window_start = (datetime.now() - ATTEMPT_WINDOW).isoformat()
    used = conn.execute(
        """
        SELECT COUNT(*) FROM redeem_attempts
        WHERE ip = ? AND success = 0 AND attempted_at > ?
        """,
        (ip, window_start)
    ).fetchone()[0]
    return max(0, MAX_FAILED_ATTEMPTS - used)


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
        'days': row['days'],
        'price': row['price'],
        'currency': CURRENCY,
        'pilot': PILOT_MODE,
        'future_price_per_day': PRICE_PER_DAY,
        'max_days': MAX_DAYS,
        'recommended_size': list(RECOMMENDED_SIZE),
        'status': row['status'],
        'starts_at': _as_date(row['starts_at']),
        'ends_at': _as_date(row['ends_at']),
        'support_whatsapp': SUPPORT_WHATSAPP,
    }


def _as_date(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).strftime('%Y-%m-%d')
    except ValueError:
        return value


def get_config() -> dict:
    """Everything the wizard needs to describe the slot to an advertiser."""
    return {
        'max_days': MAX_DAYS,
        'recommended_width': RECOMMENDED_SIZE[0],
        'recommended_height': RECOMMENDED_SIZE[1],
        'max_upload_mb': MAX_UPLOAD_BYTES // (1024 * 1024),
        'allowed_formats': sorted(ALLOWED_FORMATS),
        'pilot': PILOT_MODE,
        'price_per_day': 0.0 if PILOT_MODE else PRICE_PER_DAY,
        'future_price_per_day': PRICE_PER_DAY,
        'currency': CURRENCY,
        'support_whatsapp': SUPPORT_WHATSAPP,
    }


def get_active_ad() -> dict:
    """Pick a live campaign to display, or None when the slot is free.

    Live campaigns are rotated at random so every advertiser paying for the
    same period gets a share of the impressions.
    """
    now = datetime.now().isoformat()
    with _get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM ad_campaigns WHERE status = 'active' AND ends_at > ?",
            (now,)
        ).fetchall()

    if not rows:
        return None

    row = random.choice(rows)
    return {
        'banner_url': BANNER_URL_PREFIX + row['banner_file'],
        'target_url': row['target_url'],
        'ends_at': _as_date(row['ends_at']),
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
                "SELECT id, status, days, price, starts_at, ends_at, target_url "
                "FROM ad_campaigns ORDER BY created_at DESC"
            ).fetchall()

        if not campaigns:
            print("No campaigns yet.")
        for row in campaigns:
            window = f"{row['starts_at'] or '-'} -> {row['ends_at'] or '-'}"
            print(f"{row['id']}  {row['status']:<7} {row['days']:>2}d  "
                  f"{row['price']:>7.2f}  {window}  {row['target_url']}")
