"""MQTT topic layout shared by the hub, the simulator and the ESP32 firmware.

    home/<room>/<device>/state   device -> hub, retained JSON with the latest readings
    home/<room>/<device>/set     hub -> device, JSON command such as {"on": true}
    home/<room>/<device>/avail   "online" / "offline" (ESP32 sets this as its MQTT last will)
"""

PREFIX = "home"


def state_topic(device_id: str) -> str:
    return f"{PREFIX}/{device_id}/state"


def set_topic(device_id: str) -> str:
    return f"{PREFIX}/{device_id}/set"


def avail_topic(device_id: str) -> str:
    return f"{PREFIX}/{device_id}/avail"


def parse(topic: str) -> tuple[str, str] | None:
    """Split 'home/living_room/light/state' into ('living_room/light', 'state')."""
    parts = topic.split("/")
    if len(parts) != 4 or parts[0] != PREFIX:
        return None
    return f"{parts[1]}/{parts[2]}", parts[3]
