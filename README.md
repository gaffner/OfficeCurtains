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

## Production Setup

For production deployment with real curtain control:

1. Get fully rooms.json file from admin (requests in private)
2. Get other necessary data from admin (requests in private)
    ```bash
    export SERVER_IP=''
    export SERVER_PORT_A=None
    export SERVER_PORT_B=None
    export SERVER_PORT_C=None
    export USERNAME=''
    export MD5_VALUE=''
    export COOKIES_KEY=''
    
    # Azure AD Configuration
    export AZURE_CLIENT_ID=''
    export AZURE_TENANT_ID=''
    export AZURE_REDIRECT_URI='http://{{HOST}}/auth/callback'
    export CERT_PATH=''
    export CERT_THUMBPRINT='' 
    ```
3. Then run the server in your prefer way, for example uvicorn + nginx
```bash
pip install -r requirements.txt
uvicorn server:app --reload 
```
![example.png](Images/example.png)