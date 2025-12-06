# Deployment Overview

This project is deployed in two stages:  
1. *Service Creation*  
2. *Nginx Configuration*

---

## 1. Service Creation

Place the `fastapi.service` file in `/etc/systemd/system/` on your Linux machine.

After making any changes to the service or the application code, make sure to restart the service. For example:

```bash
sudo systemctl start fastapi.service
sudo systemctl stop fastapi.service
sudo systemctl restart fastapi.service
```

In order to read logs:
```bash
sudo journalctl -u fastapi.service
```
---

## 2. Nginx

Once the service is configured and running, the second stage is setting up and tuning the Nginx layer.  
This includes:

- Routing traffic to the application service  
- Handling SSL termination  
- Managing headers and request limits  
- Ensuring stable behavior during authentication redirects

Make sure both layers are properly aligned before moving to production.

