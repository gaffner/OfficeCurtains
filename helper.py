import json
import logging
from functools import lru_cache

import requests
from fastapi import HTTPException

from config import CURTAINS_USERNAME, MD5_VALUE


def get_suffix(room_name):
    suffix = room_name[1]
    if suffix not in ('A', 'B', 'C'):
        raise HTTPException(status_code=404, detail=f"incorrect building {suffix}")

    return suffix


def get_username(room_name):
    suffix = get_suffix(room_name)
    username = CURTAINS_USERNAME + suffix
    logging.info(f'username is {username}')

    return username


def get_states_by_direction(room_name, direction):
    states = get_room_states(room_name)
    # if this room have multiple directions, get the correct one
    if direction and len(states) > 1:
        for state in states:
            if state['name'] == direction:
                return state

    # if not, return the only direction ex~s
    return states[0]


@lru_cache(maxsize=None)
def load_rooms_data():
    try:
        with open('rooms.json', 'r', encoding='utf-8') as file:
            return json.load(file)
    except Exception as e:
        logging.error(f"Error loading rooms.json: {e}")
        return {}


def send_message(group, command, creds, address):
    url = f"https://{address[0]}:{address[1]}/iphone/send"
    data = f"username={creds[0]}\r\npassword={creds[1]}\r\nsk=\r\nversion=2\r\nmd5={MD5_VALUE}\r\ngroup={group}\r\neis=1.001\r\nvalue={command}\r\n"
    logging.info(f'Posting to: {url} with data: {data}')

    res = requests.post(url, data=data, headers={'User-Agent': 'XXter/1.0'}, verify=False)
    return res


def get_room_states(room_name: str):
    rooms = load_rooms_data()

    if room_name not in rooms:
        raise HTTPException(status_code=404, detail="Room not found")

    return rooms[room_name]
