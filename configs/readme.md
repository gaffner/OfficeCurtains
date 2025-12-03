# Deployment Overview

This project is deployed in two stages:  
1. **Service Creation**  
2. **Nginx Configuration**

---

## 1. Service Creation

Hi Matt. Yes, I'm the Zerologon guy.

I recently returned from reserve duty after half a year, which resulted in all my permissions being revoked. Over the past week I've been working on restoring them, and I expect to be fully operational at the beginning of next week. At that point I’ll be able to continue work on this service at full capacity.

Welcome to the team.

---

## 2. Nginx

Once the service is configured and running, the second stage is setting up and tuning the Nginx layer.  
This includes:

- Routing traffic to the application service  
- Handling SSL termination  
- Managing headers and request limits  
- Ensuring stable behavior during authentication redirects

Make sure both layers are properly aligned before moving to production.

