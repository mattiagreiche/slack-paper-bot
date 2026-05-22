DEMO_CHANNELS = [
    {"id": "CGEN", "name": "general", "is_private": False},
    {"id": "CSAND", "name": "sandbox", "is_private": False},
    {"id": "CREADING", "name": "reading-models", "is_private": True},
]

DEMO_USERS = [
    {"id": "U1", "name": "rrabba"},
    {"id": "U2", "name": "Max"},
    {"id": "U3", "name": "Mattia"},
    {"id": "U4", "name": "Zachary"},
]


def demo_channel_by_id(channel_id: str) -> dict:
    return next((item for item in DEMO_CHANNELS if item["id"] == channel_id), DEMO_CHANNELS[0])


def demo_user_by_id(user_id: str) -> dict:
    return next((item for item in DEMO_USERS if item["id"] == user_id), DEMO_USERS[0])
