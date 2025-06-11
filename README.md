# Office Curtains Control
No more stupid apps in order to control curtains. Lets get back to the good old days, where we control curtains using simple HTML Websites.

## How to use?
1. get fully rooms.json file from admin (requests in private)
2. Get other necessary data from admin (requests in private)
    ```bash
    export SERVER_IP=''
    export SERVER_PORT_A=None
    export SERVER_PORT_B=None
    export SERVER_PORT_C=None
    export USERNAME=''
    export MD5_VALUE=''
    export CORS_ORIGINS=''
    
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