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

## Production Deployment

For production deployment with real curtain control and Azure AD authentication:

### Prerequisites
- Linux server (Ubuntu/Debian recommended)
- Python 3.8+
- Nginx
- Domain name with SSL certificate (Let's Encrypt recommended)
- Azure AD app registration
- Access to curtain control servers

### Step 1: Clone and Install Dependencies
```bash
cd /home/www/curtains  # Or your preferred path
git clone https://github.com/gaffner/OfficeCurtains.git
cd OfficeCurtains
pip install -r data/requirements.txt
```

### Step 2: Configure Environment

1. Copy the example environment file:
```bash
cp .env.example .env
```

2. Edit `.env` and set `IS_TEST=false`, then fill in all production values:

**Required Azure AD Configuration:**
- `AZURE_CLIENT_ID` - From Azure AD app registration
- `AZURE_TENANT_ID` - Your organization's tenant ID
- `AZURE_REDIRECT_URI` - `https://your-domain.com/auth/callback`
- `CERT_PATH` - Path to certificate file (if using certificate authentication)
- `CERT_THUMBPRINT` - Certificate thumbprint (if applicable)

**Required Curtain Server Configuration:**
- `SERVER_IP` - Curtain control server IP
- `SERVER_PORT_A`, `SERVER_PORT_B`, `SERVER_PORT_C` - Ports for different buildings
- `CURTAINS_USERNAME` - Authentication username for curtain server
- `CURTAINS_PASSWORD` - Authentication password
- `MD5_VALUE` - Required MD5 hash for curtain protocol

**Required Application Settings:**
- `COOKIES_KEY` - Generate a strong random secret: `python -c "import secrets; print(secrets.token_hex(32))"`
- `ADMIN_USERS` - Comma-separated list of admin display names (e.g., "John Doe,Jane Smith")
- `REPORTS_FILE` - Path to reports file (default: `reports.txt`)
- `STATISTICS_FILE` - Path to statistics file (default: `statistics.txt`)

### Step 3: Set Up Systemd Service

1. Update the service file paths in `configs/service/curtains.service` if needed
2. Copy and enable the service:
```bash
sudo cp configs/service/curtains.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable curtains
sudo systemctl start curtains
sudo systemctl status curtains  # Verify it's running
```

### Step 4: Configure Nginx

1. Update `configs/nginx/curtains` with your domain name
2. Copy to Nginx sites:
```bash
sudo cp configs/nginx/curtains /etc/nginx/sites-available/curtains
sudo ln -s /etc/nginx/sites-available/curtains /etc/nginx/sites-enabled/
```

3. Get SSL certificate (using Let's Encrypt):
```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
```

4. Test and reload Nginx:
```bash
sudo nginx -t
sudo systemctl reload nginx
```

### Step 5: Verify Deployment

1. Check the service is running: `sudo systemctl status curtains`
2. Check logs: `sudo journalctl -u curtains -f`
3. Visit `https://your-domain.com` and test login
4. Verify Azure AD authentication works
5. Test curtain control on a real room

### Updating the Application

```bash
cd /home/www/curtains/OfficeCurtains
git pull origin main
sudo systemctl restart curtains
```

### Troubleshooting

- **Service won't start**: Check logs with `sudo journalctl -u curtains -xe`
- **Azure AD login fails**: Verify redirect URI matches in Azure AD app registration
- **502 Bad Gateway**: Check if gunicorn socket exists: `ls -la run/gunicorn.sock`
- **Curtain commands fail**: Verify `SERVER_IP`, `SERVER_PORT_*`, and credentials in `.env`

### Security Notes

- Never commit `.env` file to git (already in `.gitignore`)
- Keep `COOKIES_KEY` secret and unique per deployment
- Use HTTPS only in production
- Restrict admin access by configuring `ADMIN_USERS` carefully (case-insensitive)
- Regular security updates: `sudo apt update && sudo apt upgrade`

## Screenshot

![Office Curtains Control](Images/v3_example.png?raw=true)