# Deployment Guide

This document explains how to deploy the Office Curtains Control application using nginx and systemd.

## Prerequisites

- Ubuntu/Debian Linux server
- Python 3.10+
- nginx installed
- SSL certificate (e.g., via Let's Encrypt)

## Directory Structure

```
/home/www/curtains/OfficeCurtains/    # Application directory
├── server.py                          # FastAPI application
├── auth.py                            # Azure AD authentication
├── .env                               # Environment variables (create from .env.example)
├── cert/                              # SSL certificates for Azure AD
│   └── curtains.pfx.base64           # Base64 encoded PFX certificate
├── Frontend/                          # Static frontend files
└── ...
```

---

## 1. Install Dependencies

```bash
# Install system packages
sudo apt update
sudo apt install python3-pip nginx

# Install Python dependencies
pip3 install -r data/requirements.txt

# Important: Make sure you have PyJWT, NOT jwt package
pip3 uninstall jwt -y  # Remove conflicting package if present
pip3 install PyJWT
```

---

## 2. Environment Configuration

Create a `.env` file in the application directory:

```bash
# Server Configuration
SERVER_IP='<curtains-server-ip>'
SERVER_PORT_A='<port>'
SERVER_PORT_B='<port>'
SERVER_PORT_C='<port>'
CURTAINS_USERNAME='<username>'
CURTAINS_PASSWORD='<password>'
MD5_VALUE='<md5-hash>'

# Application Settings
REPORTS_FILE='reports.txt'
TSHIRT_FILE='tshirt_requests.txt'
STATISTICS_FILE='stats.csv'
ALLOWED_ISP='localhost'
COOKIES_KEY='<random-secret-key>'

# Azure AD Configuration
AZURE_CLIENT_ID='<your-azure-client-id>'
AZURE_TENANT_ID='<your-azure-tenant-id>'
AZURE_REDIRECT_URI='https://your-domain.example.com/auth/callback'
CERT_PATH='cert/curtains.pfx.base64'
CERT_THUMBPRINT='<certificate-thumbprint>'
```

---

## 3. Systemd Service Setup

### Install the Service

```bash
# Copy the service file
sudo cp configs/service/curtains.service /etc/systemd/system/

# Reload systemd
sudo systemctl daemon-reload

# Enable the service to start on boot
sudo systemctl enable curtains.service

# Start the service
sudo systemctl start curtains.service
```

### Service Management Commands

```bash
# Start the service
sudo systemctl start curtains.service

# Stop the service
sudo systemctl stop curtains.service

# Restart the service
sudo systemctl restart curtains.service

# Check service status
sudo systemctl status curtains.service

# View logs
sudo journalctl -u curtains.service -f
```

---

## 4. Nginx Configuration

### Install the Configuration

```bash
# Copy nginx config
sudo cp configs/nginx/curtains /etc/nginx/sites-available/curtains

# Edit the config and replace 'your-domain.example.com' with your actual domain
sudo nano /etc/nginx/sites-available/curtains

# Enable the site
sudo ln -s /etc/nginx/sites-available/curtains /etc/nginx/sites-enabled/

# Test nginx configuration
sudo nginx -t

# Reload nginx
sudo systemctl reload nginx
```

### SSL Certificate Setup (Let's Encrypt)

```bash
# Install certbot
sudo apt install certbot python3-certbot-nginx

# Obtain certificate (replace with your domain)
sudo certbot --nginx -d your-domain.example.com

# Certbot will automatically configure SSL in your nginx config
```

---

## 5. Verify Deployment

1. Check the service is running:
   ```bash
   sudo systemctl status curtains.service
   ```

2. Check nginx is running:
   ```bash
   sudo systemctl status nginx
   ```

3. Test the application:
   ```bash
   curl -I https://your-domain.example.com
   ```

4. Check application logs:
   ```bash
   sudo journalctl -u curtains.service -f
   ```

---

## Troubleshooting

### JWT Authentication Error
If you see "module 'jwt' has no attribute 'encode'", uninstall the `jwt` package and keep only `PyJWT`:
```bash
pip3 uninstall jwt -y --break-system-packages
pip3 install PyJWT --break-system-packages
sudo systemctl restart curtains.service
```

### Service Won't Start
Check logs for errors:
```bash
sudo journalctl -u curtains.service -n 50
```

### 502 Bad Gateway
Ensure the application is running and listening on port 8000:
```bash
sudo systemctl status curtains.service
curl http://127.0.0.1:8000
```

---

## Updating the Application

```bash
# Pull latest changes
cd /home/www/curtains/OfficeCurtains
git pull

# Restart the service
sudo systemctl restart curtains.service
```

