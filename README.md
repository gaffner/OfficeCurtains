# Office Curtains Control
No more stupid apps in order to control curtains. Lets get back to the good old days, where we control curtains using simple HTML Websites.

## How to Develop (Quick Start)

Want to contribute or test locally? It's easy:

1. Clone the repo
2. Install dependencies and run:
   ```bash
   pip install -r data/requirements.txt
   python -m uvicorn server:app --reload --port 8000
   ```
3. Open http://127.0.0.1:8000

**That's it!** No `.env` file needed - the app automatically uses `.env.example` which has `IS_TEST=true`.

When in test mode:
- No IP whitelisting is enforced - localhost is always allowed
- No real curtain server connection needed - curtain commands are simulated
- All other features work normally (rooms, chat, etc.)

The UI will show `[TEST MODE]` in responses so you know commands aren't actually being sent.

## Access Control

There are no user accounts or SSO. Access is gated purely by IP whitelisting:
only clients whose ISP appears in the comma-separated `ALLOWED_ISP` allowlist
(e.g. `Microsoft,Partner Communications Ltd.`) are allowed in;
everyone else is redirected to a "blocked" page. Localhost is always allowed for
local development. The public chat is anonymous - users type a display name with
each message.

## Azure Functions

The FastAPI app can also run as an Azure Functions Python app through `function_app.py`.

1. Install Azure Functions Core Tools and dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Create local settings and run the function host:
   ```bash
   cp local.settings.json.example local.settings.json
   func start
   ```
3. Open http://127.0.0.1:7071

`host.json` removes the default `/api` route prefix so the existing frontend paths keep working unchanged.

## Security Notes

- Never commit `.env` file to git (already in `.gitignore`)
- Configure `ALLOWED_ISP` to restrict access to your organization's network
- Use HTTPS only in production
- Regular security updates: `sudo apt update && sudo apt upgrade`

## Screenshot

![Office Curtains Control](Images/v3_example.png?raw=true)