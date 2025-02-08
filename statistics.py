import hashlib
import os
from datetime import datetime

from fastapi import Request

from config import STATISTICS_FOLDER, CSV_FORMAT
from utils import get_client_ip


def get_current_csv():
    csv_name = datetime.now().strftime("%Y-%m-%d")
    csv = open(os.path.join(STATISTICS_FOLDER, csv_name), "a")
    csv.write(CSV_FORMAT)

    return csv


def log_control(request: Request, room_name: str, direction: str):
    hashed_user_ip = hashlib.sha1(get_client_ip(request).encode()).hexdigest()
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    report_entry = f"{room_name},{hashed_user_ip},{direction}\n"

    csv = get_current_csv()
    csv.write(report_entry)
