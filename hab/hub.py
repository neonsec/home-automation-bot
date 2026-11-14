"""The hub: keeps live device state from MQTT, runs the rules engine, and
serves a REST API plus a live dashboard.

Run:  uvicorn hab.hub:app --port 8000
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

import paho.mqtt.client as mqtt
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

from . import topics
from .rules import Rule, RuleEngine

MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
RULES_FILE = Path(os.getenv("RULES_FILE", "rules.json"))

devices: dict[str, dict] = {}  # device_id -> {"state": {...}, "online": bool, "updated": ts}
_version = 0  # bumped on every change so the dashboard stream knows to push

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="hab-hub")


def send_command(device_id: str, command: dict) -> None:
    client.publish(topics.set_topic(device_id), json.dumps(command), qos=1)


engine = RuleEngine(RULES_FILE, send_command)


def _on_connect(c, userdata, flags, reason_code, properties):
    c.subscribe(f"{topics.PREFIX}/+/+/state")
    c.subscribe(f"{topics.PREFIX}/+/+/avail")


def _on_message(c, userdata, msg):
    global _version
    parsed = topics.parse(msg.topic)
    if not parsed:
        return
    device_id, kind = parsed
    entry = devices.setdefault(device_id, {"state": {}, "online": True, "updated": 0})
    if kind == "avail":
        entry["online"] = msg.payload.decode() == "online"
    elif kind == "state":
        try:
            state = json.loads(msg.payload)
        except json.JSONDecodeError:
            return
        entry["state"] = state
        entry["online"] = True
        entry["updated"] = time.time()
        engine.on_state(device_id, state)
    _version += 1


client.on_connect = _on_connect
client.on_message = _on_message

app = FastAPI(title="Home Automation Hub")


@app.on_event("startup")
def _start_mqtt():
    client.connect_async(MQTT_HOST, MQTT_PORT)
    client.loop_start()


@app.on_event("shutdown")
def _stop_mqtt():
    client.loop_stop()
    client.disconnect()


class Command(BaseModel):
    command: dict


class RuleIn(BaseModel):
    name: str
    when_device: str
    when_field: str
    op: str
    value: bool | int | float | str
    then_device: str
    then_command: dict
    cooldown_s: int = 30


@app.get("/api/devices")
def list_devices():
    return devices


@app.get("/api/devices/{room}/{name}")
def get_device(room: str, name: str):
    device_id = f"{room}/{name}"
    if device_id not in devices:
        raise HTTPException(404, f"unknown device {device_id}")
    return devices[device_id]


@app.post("/api/devices/{room}/{name}/set")
def set_device(room: str, name: str, body: Command):
    device_id = f"{room}/{name}"
    if device_id not in devices:
        raise HTTPException(404, f"unknown device {device_id}")
    send_command(device_id, body.command)
    return {"sent": body.command, "to": device_id}


@app.get("/api/rules")
def list_rules():
    return {"rules": [r.__dict__ for r in engine.rules.values()], "recent_fires": engine.log[-20:]}


@app.post("/api/rules")
def add_rule(body: RuleIn):
    try:
        rule = engine.add(Rule(**body.model_dump()))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return rule.__dict__


@app.delete("/api/rules/{rule_id}")
def delete_rule(rule_id: str):
    if not engine.delete(rule_id):
        raise HTTPException(404, "no such rule")
    return {"deleted": rule_id}


@app.get("/api/stream")
async def stream():
    """Server-sent events: pushes the full device map whenever it changes."""
    async def gen():
        seen = -1
        while True:
            if _version != seen:
                seen = _version
                yield f"data: {json.dumps({'devices': devices, 'fires': engine.log[-5:]})}\n\n"
            await asyncio.sleep(0.5)
    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/", response_class=HTMLResponse)
def dashboard():
    return (Path(__file__).parent / "dashboard.html").read_text()
