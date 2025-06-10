from msal import ConfidentialClientApplication
from fastapi import HTTPException, Request
from starlette.responses import RedirectResponse
from functools import wraps
import os

def get_certificate_from_file():
    import logging
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.serialization import pkcs12
    
    cert_path = os.getenv('CERT_PATH')
    try:
        logging.info(f"Attempting to read certificate from: {cert_path}")
        with open(cert_path, 'rb') as cert_file:
            pfx_data = cert_file.read()
            logging.info(f"Read PFX file, size: {len(pfx_data)} bytes")
            
            # Load PFX
            private_key, certificate, _ = pkcs12.load_key_and_certificates(
                pfx_data,
                password=None.encode() if None else None  # Handle None password case
            )
            
            # Get private key in PEM format and decode to string
            key_pem = private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption()
            ).decode('utf-8')
            
            # Get certificate in PEM format and decode to string
            cert_pem = certificate.public_bytes(
                encoding=serialization.Encoding.PEM
            ).decode('utf-8')
            
            logging.info("Successfully processed certificate and private key")
            logging.debug(f"Private key: {key_pem[:100]}...")  # Log first 100 chars
            logging.debug(f"Certificate: {cert_pem[:100]}...")  # Log first 100 chars
            
            return {
                'key': key_pem,
                'cert': cert_pem
            }
            
    except Exception as e:
        logging.error(f"Failed to process certificate: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Certificate error: {str(e)}")

def log_env_vars():
    import logging
    logging.info("Azure AD Configuration:")
    logging.info(f"Client ID: {os.getenv('AZURE_CLIENT_ID')}")
    logging.info(f"Tenant ID: {os.getenv('AZURE_TENANT_ID')}")
    logging.info(f"Redirect URI: {os.getenv('AZURE_REDIRECT_URI')}")
    logging.info(f"Cert Path: {os.getenv('CERT_PATH')}")
    logging.info(f"Cert Thumbprint: {os.getenv('CERT_THUMBPRINT')}")

def get_auth_app():
    log_env_vars()
    cert_data = get_certificate_from_file()
    
    import logging
    try:
        app = ConfidentialClientApplication(
        os.getenv('AZURE_CLIENT_ID'),
        authority=f"https://login.microsoftonline.com/{os.getenv('AZURE_TENANT_ID')}",
        client_credential={
            'private_key': cert_data['key'],
            'thumbprint': os.getenv('CERT_THUMBPRINT'),
            'public_certificate': cert_data['cert']
        }
    )
        logging.info("Successfully created ConfidentialClientApplication")
        return app
    except Exception as e:
        logging.error(f"Failed to create ConfidentialClientApplication: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Authentication setup error: {str(e)}")

def require_auth():
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            request = kwargs.get('request')
            if not request.session.get('user'):
                auth_url = get_auth_app().get_authorization_request_url(
                    scopes=['User.Read'],
                    redirect_uri=os.getenv('AZURE_REDIRECT_URI')
                )
                return RedirectResponse(url=auth_url)
            return await func(*args, **kwargs)
        return wrapper
    return decorator
