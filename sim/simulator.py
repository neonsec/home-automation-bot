"""Simulated home: publishes the same MQTT messages as the ESP32 nodes, so the
hub and bot can be built and demoed before any hardware arrives.

Run:  python -m sim.simulator
"""

from __future__ import annotations

import json
import math
import os
import random
import time

import paho.mqtt.client as mqtt

from hab import topics

MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))

# device_id -> state. Switches accept {"on": bool}; the fan also takes {"speed": 1-3}.
home = {
    "living_room/light": {"on": False},
    "living_room/fan": {"on": False, "speed": 1},
    "living_room/climate": {"temperature_c": 26.0, "humidity_pct": 55},
    "living_room/motion": {"motion": False},
    "hallway/light": {"on": False},
    "hallway/motion": {"motion": False},
    "front_door/contact": {"open": False},
    "outside/light_sensor": {"lux": 400},
}
SWITCHES = {"living_room/light", "living_room/fan", "hallway/light"}

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="hab-sim")


def publish(device_id: str) -> None:
    client.publish(topics.state_topic(device_id), json.dumps(home[device_id]), qos=1, retain=True)


def on_connect(c, userdata, flags, reason_code, properties):
    for device_id in home:
        c.publish(topics.avail_topic(device_id), "online", retain=True)
        publish(device_id)
    c.subscribe(f"{topics.PREFIX}/+/+/set")


def on_message(c, userdata, msg):
    parsed = topics.parse(msg.topic)
    if not parsed or parsed[0] not in SWITCHES:
        return
    device_id = parsed[0]
    try:
        cmd = json.loads(msg.payload)
    except json.JSONDecodeError:
        return
    if "on" in cmd:
        home[device_id]["on"] = bool(cmd["on"])
    if "speed" in cmd and "speed" in home[device_id]:
        home[device_id]["speed"] = max(1, min(3, int(cmd["speed"])))
    print(f"[sim] {device_id} <- {cmd}")
    publish(device_id)


def tick(t: float) -> None:
    climate = home["living_room/climate"]
    # Temperature follows a slow daily-style wave; a running fan cools the room.
    target = 27 + 3 * math.sin(t / 120) - (1.5 if home["living_room/fan"]["on"] else 0)
    climate["temperature_c"] = round(climate["temperature_c"] + (target - climate["temperature_c"]) * 0.1
                                     + random.uniform(-0.1, 0.1), 1)
    climate["humidity_pct"] = max(30, min(80, climate["humidity_pct"] + random.randint(-1, 1)))
    publish("living_room/climate")

    for room in ("living_room", "hallway"):
        motion = random.random() < 0.15
        if motion != home[f"{room}/motion"]["motion"]:
            home[f"{room}/motion"]["motion"] = motion
            publish(f"{room}/motion")

    if random.random() < 0.03:
        home["front_door/contact"]["open"] = not home["front_door/contact"]["open"]
        publish("front_door/contact")

    home["outside/light_sensor"]["lux"] = max(0, int(400 + 400 * math.sin(t / 180)))
    publish("outside/light_sensor")


def main() -> None:
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(MQTT_HOST, MQTT_PORT)
    client.loop_start()
    print(f"[sim] publishing {len(home)} devices to {MQTT_HOST}:{MQTT_PORT}")
    start = time.time()
    try:
        while True:
            tick(time.time() - start)
            time.sleep(2)
    except KeyboardInterrupt:
        for device_id in home:
            client.publish(topics.avail_topic(device_id), "offline", retain=True)
        client.loop_stop()


if __name__ == "__main__":
    main()
