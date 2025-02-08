import os

SERVER_IP = os.getenv('SERVER_IP')
CURTAINS_USERNAME = os.getenv('CURTAINS_USERNAME')
MD5_VALUE = os.getenv('MD5_VALUE')
CURTAINS_PASSWORD = os.getenv('CURTAINS_PASSWORD')
REPORTS_FILE = os.getenv('REPORTS_FILE')

def get_server_port(suffix):
    return os.getenv('SERVER_PORT_' + suffix)
