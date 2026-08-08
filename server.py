import base64
import html
import logging
from datetime import datetime

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
)
from starlette.staticfiles import StaticFiles

from config import *
from helper import get_suffix, get_username, get_states_by_direction, send_message, get_room_states
from utils import (
    get_allowed_isps,
    get_client_ip,
    lookup_isp,
    setup_logging,
    validate_isp,
    wants_json,
    LOCALHOST_ADDRESSES,
)
import ads
import chat
import stats_store

# Setup logging before anything else
setup_logging()

# Setup the FastAPI app
load_dotenv()
app = FastAPI(redirect_slashes=False)

# Access is controlled purely by IP whitelisting (see utils.validate_isp):
# only clients whose ISP is listed in ALLOWED_ISP are allowed. There are
# no user accounts or SSO. Localhost is always allowed for local development.


class RevalidatingStaticFiles(StaticFiles):
    """StaticFiles that asks browsers to revalidate instead of guessing.

    StaticFiles sends ETag and Last-Modified but no Cache-Control, which lets
    browsers fall back to heuristic freshness (roughly 10% of the file's age).
    For files that had not changed in months that meant a deployed fix could be
    ignored for days, because the browser reused its copy without ever asking
    the server. `no-cache` still allows caching, it just requires revalidation,
    so the ETag turns the check into a cheap 304.
    """

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers.setdefault("Cache-Control", "no-cache")
        return response

app.mount("/Frontend", RevalidatingStaticFiles(directory="Frontend"), name="Frontend")


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Return a JSON error to API callers instead of an HTML/plain error page.

    Without this, `fetch` callers receive HTML and fail with an opaque
    "Unexpected token '<'" JSON parse error instead of a usable message.
    """
    logging.exception(f"Unhandled error while handling {request.method} {request.url.path}")

    if wants_json(request):
        return JSONResponse(
            status_code=500,
            content={"detail": "The server hit an unexpected error. Please try again shortly."},
        )

    return PlainTextResponse("Internal Server Error", status_code=500)


@app.get("/submit-report/{report}")
@validate_isp()
def submit_report(request: Request, report: str):
    user_ip = get_client_ip(request)
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    report_entry = f"{current_time} - {user_ip} - {report}\n"

    os.makedirs(os.path.dirname(REPORTS_FILE), exist_ok=True) if os.path.dirname(REPORTS_FILE) else None
    with open(REPORTS_FILE, "a") as file:
        file.write(report_entry)

    return {"message": "Report submitted successfully"}


@app.get("/whats-new")
@validate_isp()
def get_whats_new(request: Request):
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
@validate_isp()
def get_version(request: Request):
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


@app.get("/")
def root(request: Request):
    return RedirectResponse(url="/Frontend/index.html")


@app.get("/api/access")
def get_access_status(request: Request):
    """Report whether the caller's ISP is on the allow list.

    Intentionally NOT ISP-gated: Frontend/index.html is served as a static file
    and therefore loads for everyone, so the page needs a way to find out that
    the controls will not work and explain why.
    """
    user_ip = get_client_ip(request)

    if user_ip in LOCALHOST_ADDRESSES:
        return {"allowed": True, "isp": None}

    isp = lookup_isp(user_ip)
    if isp is None:
        # Unknown (lookup failed or rate limited) - do not claim the user is blocked.
        return {"allowed": None, "isp": None}

    return {"allowed": isp.casefold() in get_allowed_isps(), "isp": isp}


@app.get("/register/{room_name}")
@validate_isp()
def register(request: Request, room_name: str):
    # In test mode, don't check if room exists
    if IS_TEST:
        return ['up', 'down', 'stop']
    states = get_room_states(room_name.upper())
    directions = [state['name'] for state in states]
    return directions


@app.get("/control/{room_name}/{action}")
@validate_isp()
def control_curtain(request: Request, room_name: str, action: str, direction: str = None):
    room_name = room_name.upper()

    # In test mode, just return success
    if IS_TEST:
        stats_store.record_action(room_name, action)
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
        stats_store.record_action(room_name, action)
        return {"status": "success", "message": f"Curtain in room {room_name} {action} command sent successfully."}
    else:
        raise HTTPException(status_code=res.status_code, detail=f"Failed to send command {res.text}")


@app.get("/stats/all")
@validate_isp()
def get_all_stats(request: Request):
    """Usage statistics aggregated across the whole recorded history."""
    return stats_store.get_all_statistics()


# ============== Chat Endpoints (anonymous) ==============

@app.get("/api/chat/messages")
@validate_isp()
def get_chat_messages(request: Request):
    """Get all chat messages."""
    messages = chat.get_chat_messages()
    return {"messages": messages}


@app.post("/api/chat/send")
@validate_isp()
def send_chat_message(request: Request, payload: dict):
    """Send an anonymous chat message. The sender supplies a display name."""
    name = (payload.get('name') or '').strip()
    message_text = (payload.get('message') or '').strip()

    if not name:
        name = "Anonymous"

    if not message_text:
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    if len(message_text) > 500:
        raise HTTPException(status_code=400, detail="Message too long (max 500 characters)")

    if len(name) > 40:
        raise HTTPException(status_code=400, detail="Name too long (max 40 characters)")

    chat.add_chat_message(name, message_text)

    return {"status": "success", "message": "Message sent"}

# ============== Advertising slot ==============

@app.get("/api/ads/active")
def get_active_ad(request: Request):
    """The banner currently on air, if any.

    Like /api/access this is deliberately not ISP-gated: index.html loads for
    everyone, and an advertiser is paying for impressions rather than for
    clicks from one office.
    """
    return {"ad": ads.get_active_ad()}


@app.get("/api/ads/config")
def get_ad_config(request: Request):
    """Sizing, pricing and limits, so the wizard has no hard-coded copy."""
    return ads.get_config()


@app.get("/api/ads/queue")
def get_ad_queue(request: Request):
    """What is on air now and what follows it. Not ISP-gated, same as /active."""
    return ads.get_queue()


@app.post("/api/ads/draft")
@validate_isp()
async def create_ad_draft(
    request: Request,
    banner: UploadFile = File(...),
    target_url: str = Form(...),
    hours: int = Form(...),
):
    """Take an uploaded banner and put it in the queue.

    Uploading is free and open, so unless AD_REQUIRE_CODE is switched on the
    campaign goes live straight away instead of waiting for a code.
    """
    raw = await banner.read()

    try:
        campaign = ads.create_draft(raw, banner.filename or '', target_url, hours)
        if not ads.REQUIRE_CODE:
            campaign = ads.publish_campaign(campaign['id'])
        return campaign
    except ads.AdError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/ads/{campaign_id}/redeem")
@validate_isp()
def redeem_ad_code(request: Request, campaign_id: str, payload: dict):
    """Activate a draft campaign with a payment code."""
    try:
        return ads.redeem_code(campaign_id, payload.get('code', ''), get_client_ip(request))
    except ads.RateLimited as e:
        raise HTTPException(status_code=429, detail=str(e))
    except ads.AdError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/ads/{campaign_id}")
@validate_isp()
def get_ad_campaign(request: Request, campaign_id: str):
    try:
        return ads.get_campaign(campaign_id)
    except ads.AdError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/ad/click/{campaign_id}")
def click_ad(request: Request, campaign_id: str):
    """Count a click and forward the visitor to the advertiser.

    Not ISP-gated, and it never records who clicked -- only that a click
    happened -- so it keeps the site's anonymous design.
    """
    try:
        target = ads.record_click(campaign_id)
    except ads.AdError:
        return RedirectResponse(url="/", status_code=302)

    return RedirectResponse(url=target, status_code=302)


def render_admin_page(data: dict) -> str:
    """Plain server-rendered tables. No JS, so it works from any device."""
    def esc(value):
        return html.escape(str(value if value is not None else '-'))

    def when(value):
        return esc(value[:16].replace('T', ' ')) if value else '-'

    totals = data['totals']
    rows = []
    for c in data['campaigns']:
        rows.append(
            f"<tr class='{esc(c['state']).replace(' ', '-')}'>"
            f"<td><img src='{esc(c['banner_url'])}' alt=''></td>"
            f"<td>{esc(c['state'])}</td>"
            f"<td><a href='{esc(c['target_url'])}' rel='noopener noreferrer nofollow'"
            f" target='_blank'>{esc(c['target_url'])}</a></td>"
            f"<td>{esc(c['hours'])}h</td>"
            f"<td>{when(c['starts_at'])}</td><td>{when(c['ends_at'])}</td>"
            f"<td>{esc(c['impressions'])}</td><td>{esc(c['clicks'])}</td>"
            f"<td>{c['ctr']:.2f}%</td>"
            f"<td><code>{esc(c['id'])}</code></td></tr>"
        )
    campaign_rows = ''.join(rows) or "<tr><td colspan='10'>No campaigns yet.</td></tr>"

    click_rows = ''.join(
        f"<tr><td>{when(click.get('at'))}</td>"
        f"<td><code>{esc(click.get('campaign_id'))}</code></td>"
        f"<td>{esc(click.get('target_url'))}</td></tr>"
        for click in data['recent_clicks']
    ) or "<tr><td colspan='3'>No clicks recorded yet.</td></tr>"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="robots" content="noindex, nofollow">
<title>Ad statistics</title>
<style>
  body {{ font-family: system-ui, sans-serif; margin: 1.5rem; color: #222; }}
  h1 {{ margin-bottom: 0.25rem; }}
  p.note {{ color: #666; margin-top: 0; }}
  table {{ border-collapse: collapse; width: 100%; margin-bottom: 2rem; }}
  th, td {{ border: 1px solid #ccc; padding: 0.4rem 0.6rem; text-align: left;
           font-size: 0.9rem; vertical-align: middle; }}
  th {{ background: #f2f2f2; }}
  img {{ height: 28px; width: auto; max-width: 120px; display: block; }}
  code {{ font-size: 0.8rem; }}
  tr.on-air td {{ background: #eaf7ea; }}
  tr.queued td {{ background: #fff8e5; }}
  tr.draft td {{ color: #888; }}
  .totals td {{ font-weight: bold; }}
</style>
</head>
<body>
<h1>Ad statistics</h1>
<p class="note">Generated {esc(datetime.now().strftime('%Y-%m-%d %H:%M'))}</p>

<table>
  <tr><th>Campaigns</th><th>Impressions</th><th>Clicks</th><th>CTR</th></tr>
  <tr class="totals"><td>{esc(totals['campaigns'])}</td>
    <td>{esc(totals['impressions'])}</td><td>{esc(totals['clicks'])}</td>
    <td>{totals['ctr']:.2f}%</td></tr>
</table>

<h2>Campaigns</h2>
<table>
  <tr><th>Banner</th><th>State</th><th>Target</th><th>Length</th><th>Starts</th>
      <th>Ends</th><th>Views</th><th>Clicks</th><th>CTR</th><th>ID</th></tr>
  {campaign_rows}
</table>

<h2>Recent clicks</h2>
<table>
  <tr><th>When</th><th>Campaign</th><th>Target</th></tr>
  {click_rows}
</table>
<p class="note">Full click log: <code>{esc(data['click_log'])}</code></p>
</body>
</html>"""


@app.get("/admin")
def admin_page(request: Request):
    """Private ad statistics, guarded by HTTP basic auth.

    Deliberately not ISP-gated: the owner may be on any network, and the
    password is the gate here.
    """
    def challenge(message: str, status: int = 401):
        headers = {}
        if status == 401:
            headers["WWW-Authenticate"] = 'Basic realm="Curtains admin"'
        return PlainTextResponse(message, status_code=status, headers=headers)

    header = request.headers.get("authorization", "")
    scheme, _, encoded = header.partition(" ")

    if scheme.lower() != "basic" or not encoded:
        return challenge("Sign in required.")

    try:
        username, _, password = base64.b64decode(encoded).decode('utf-8').partition(":")
    except Exception:
        return challenge("Sign in required.")

    try:
        if not ads.check_admin_login(username, password, get_client_ip(request)):
            return challenge("Wrong username or password.")
    except ads.RateLimited as e:
        return challenge(str(e), status=429)
    except ads.AdError as e:
        return challenge(str(e), status=503)

    return HTMLResponse(render_admin_page(ads.get_admin_stats()))
