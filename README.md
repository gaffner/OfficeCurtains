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
- No Azure AD configuration needed - clicking "Sign in" logs you in as "Developer"
- No real curtain server connection needed - curtain commands are simulated
- All other features work normally (statistics, premium, rooms, etc.)

The UI will show `[TEST MODE]` in responses so you know commands aren't actually being sent.

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

`host.json` removes the default `/api` route prefix so the existing frontend paths and authentication redirects keep working unchanged.

## Security Notes

- Never commit `.env` file to git (already in `.gitignore`)
- Keep `COOKIES_KEY` secret and unique per deployment
- Use HTTPS only in production
- Restrict admin access by configuring `ADMIN_USERS` carefully (case-insensitive)
- Regular security updates: `sudo apt update && sudo apt upgrade`

## Screenshot

![Office Curtains Control](Images/v3_example.png?raw=true)