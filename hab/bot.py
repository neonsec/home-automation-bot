"""Chat with your home in plain English. Claude reads device state and controls
devices and automation rules through the hub's REST API.

Run:  python -m hab.bot
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

import anthropic

HUB = os.getenv("HUB_URL", "http://localhost:8000")
MODEL = "claude-opus-5-5"

SYSTEM = """You are the assistant for a home automation hub. Devices are named
"<room>/<device>" (for example "living_room/light"). Switch devices accept {"on": true|false};
the fan also accepts {"speed": 1-3}. Sensors are read-only.

Check live state with the tools before answering questions about the home, and read
state back after changing something to confirm it worked. When the user asks for an
automation ("turn on the fan when it gets hot"), create a rule, then say in one line
what it does. Keep replies short."""


def _call(method: str, path: str, body: dict | None = None) -> str:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{HUB}{path}", data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.read().decode()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"hub returned {e.code}: {e.read().decode()}") from e


def _device_path(device_id: str) -> str:
    room, _, name = device_id.partition("/")
    if not room or not name:
        raise RuntimeError('device must look like "room/device"')
    return f"/api/devices/{room}/{name}"


def run_tool(name: str, args: dict) -> str:
    if name == "list_devices":
        return _call("GET", "/api/devices")
    if name == "set_device":
        return _call("POST", _device_path(args["device"]) + "/set", {"command": args["command"]})
    if name == "list_rules":
        return _call("GET", "/api/rules")
    if name == "add_rule":
        return _call("POST", "/api/rules", args)
    if name == "delete_rule":
        return _call("DELETE", f"/api/rules/{args['rule_id']}")
    raise RuntimeError(f"unknown tool {name}")


TOOLS = [
    {
        "name": "list_devices",
        "description": "Get every device with its live state, online status and last update time.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "set_device",
        "description": "Send a command to a device, e.g. {\"on\": true} or {\"speed\": 2}.",
        "input_schema": {
            "type": "object",
            "properties": {
                "device": {"type": "string", "description": "room/device, e.g. living_room/light"},
                "command": {"type": "object", "description": "fields to set on the device"},
            },
            "required": ["device", "command"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_rules",
        "description": "List automation rules and the most recent times they fired.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "add_rule",
        "description": ("Create an automation: when when_device.when_field <op> value becomes true, "
                        "send then_command to then_device. Fires once per change, then waits cooldown_s."),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "when_device": {"type": "string"},
                "when_field": {"type": "string", "description": "e.g. temperature_c, motion, open, lux"},
                "op": {"type": "string", "enum": ["==", "!=", ">", ">=", "<", "<="]},
                "value": {"description": "number, boolean or string to compare against"},
                "then_device": {"type": "string"},
                "then_command": {"type": "object"},
                "cooldown_s": {"type": "integer", "minimum": 0},
            },
            "required": ["name", "when_device", "when_field", "op", "value", "then_device", "then_command"],
            "additionalProperties": False,
        },
    },
    {
        "name": "delete_rule",
        "description": "Delete an automation rule by its id.",
        "input_schema": {
            "type": "object",
            "properties": {"rule_id": {"type": "string"}},
            "required": ["rule_id"],
            "additionalProperties": False,
        },
    },
]


def ask(client: anthropic.Anthropic, messages: list) -> str:
    """Run one user turn to completion, executing tool calls against the hub."""
    while True:
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            system=SYSTEM,
            tools=TOOLS,
            messages=messages,
            thinking={"type": "adaptive"},
            output_config={"effort": "low"},
            # If a safety classifier declines, the API retries on a fallback model automatically.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "refusal":
            return "(The request was declined.)"
        if response.stop_reason != "tool_use":
            return "".join(b.text for b in response.content if b.type == "text")

        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            try:
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": run_tool(block.name, block.input)})
            except (RuntimeError, KeyError, urllib.error.URLError) as e:
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": f"Error: {e}", "is_error": True})
        messages.append({"role": "user", "content": results})


def main() -> None:
    client = anthropic.Anthropic()
    messages: list = []
    print("Home bot ready. Try: \"what's the temperature?\" or \"turn on the fan when it's over 28°C\". Ctrl+C to quit.")
    while True:
        try:
            text = input("\nyou › ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not text:
            continue
        messages.append({"role": "user", "content": text})
        try:
            print("bot ›", ask(client, messages))
        except anthropic.APIConnectionError:
            print("bot › Can't reach the Claude API. Check your network.")
            messages.pop()
        except anthropic.RateLimitError:
            print("bot › Rate limited. Wait a moment and try again.")
            messages.pop()
        except anthropic.APIStatusError as e:
            print(f"bot › API error {e.status_code}: {e.message}")
            messages.pop()


if __name__ == "__main__":
    main()
