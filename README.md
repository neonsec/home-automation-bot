# Home Automation Bot

Control your home in plain English. ESP32 sensor and relay nodes publish over MQTT
to a hub that keeps live state, runs automation rules and serves a dashboard.
A Claude-powered bot reads and controls everything through the hub's API.

```
 ESP32 nodes ─┐                      ┌─ Dashboard (browser, live via SSE)
 (DHT22, PIR, │  MQTT   ┌─────────┐  │
  relay)      ├────────►│   Hub   │◄─┼─ REST API
 Simulator ───┘ home/#  │ FastAPI │  │
                        │ + rules │  └─ Claude bot (tool use) ◄── "turn on the fan when it's over 28°C"
                        └─────────┘
```

## Run it (no hardware needed)

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
brew install mosquitto && mosquitto -c broker/mosquitto.conf -d   # or: docker compose up -d
.venv/bin/python -m sim.simulator              # terminal 1: simulated home
.venv/bin/uvicorn hab.hub:app --port 8000       # terminal 2: hub + dashboard at http://localhost:8000
export ANTHROPIC_API_KEY=...                    # terminal 3: the bot
.venv/bin/python -m hab.bot
```

Things to try in the bot:
- "What's the temperature in the living room?"
- "Turn the fan on at speed 2"
- "Turn on the hallway light whenever there's motion"
- "If the front door opens, turn on the living room light"
- "What automations do I have? Delete the door one."

## Real hardware

`firmware/esp32_node/esp32_node.ino` runs one room on an ESP32 with:
- a DHT22 temperature and humidity sensor
- a PIR motion sensor
- a relay for the light

It uses the same topics as the simulator, so the hub and bot need no changes. Before flashing:
1. Copy `secrets.h.example` to `secrets.h` and fill in your Wi-Fi and the broker IP.
2. Install the PubSubClient, ArduinoJson and DHT libraries.
3. Flash from the Arduino IDE.

Relays switching mains voltage must be wired by a qualified electrician. Use low-voltage loads (LED strips, 12 V fans) for testing.

## MQTT topics

| Topic | Direction | Example |
|---|---|---|
| `home/<room>/<device>/state` | device → hub (retained) | `{"temperature_c": 27.4, "humidity_pct": 55}` |
| `home/<room>/<device>/set` | hub → device | `{"on": true, "speed": 2}` |
| `home/<room>/<device>/avail` | device → hub (MQTT last will) | `online` / `offline` |

## Rules engine

A rule fires once when its condition becomes true (not on every reading), and then
waits for its cooldown. This stops a lamp from clicking on and off when a reading
hovers around the threshold. Rules are saved in `rules.json`. Tests: `.venv/bin/pytest`.
