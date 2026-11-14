// ESP32 room node: DHT22 temperature/humidity, PIR motion sensor, relay-driven light.
// Speaks the same MQTT topics as sim/simulator.py, so the hub can't tell the difference.
//
// Wiring (change the pins below to match your board):
//   DHT22 data -> GPIO 4 (10k pull-up to 3.3V)
//   PIR out    -> GPIO 27
//   Relay IN   -> GPIO 26 (use a 3.3V-logic relay module; mains wiring only by a qualified electrician)
//
// Libraries (Arduino Library Manager): PubSubClient, ArduinoJson (v7), DHT sensor library (Adafruit)

#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <DHT.h>
#include "secrets.h"  // copy secrets.h.example to secrets.h and fill it in

#define ROOM "living_room"
#define PIN_DHT 4
#define PIN_PIR 27
#define PIN_RELAY 26
#define SENSOR_INTERVAL_MS 5000

DHT dht(PIN_DHT, DHT22);
WiFiClient net;
PubSubClient mqtt(net);

bool lightOn = false;
bool lastMotion = false;
unsigned long lastSensorMs = 0;

String topic(const char* device, const char* kind) {
  return String("home/") + ROOM + "/" + device + "/" + kind;
}

void publishJson(const String& t, JsonDocument& doc) {
  char buf[128];
  size_t n = serializeJson(doc, buf);
  mqtt.publish(t.c_str(), (const uint8_t*)buf, n, true);  // retained
}

void publishLight() {
  JsonDocument doc;
  doc["on"] = lightOn;
  publishJson(topic("light", "state"), doc);
}

void onMessage(char* t, byte* payload, unsigned int len) {
  JsonDocument doc;
  if (deserializeJson(doc, payload, len)) return;  // ignore bad JSON
  if (String(t) == topic("light", "set") && doc["on"].is<bool>()) {
    lightOn = doc["on"];
    digitalWrite(PIN_RELAY, lightOn ? HIGH : LOW);
    publishLight();
  }
}

void connectWifi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  while (WiFi.status() != WL_CONNECTED) delay(500);
}

void connectMqtt() {
  String avail = topic("climate", "avail");
  while (!mqtt.connected()) {
    // Last will: the broker marks this node offline if it drops off the network.
    if (mqtt.connect("esp32-" ROOM, MQTT_USER, MQTT_PASSWORD, avail.c_str(), 1, true, "offline")) {
      mqtt.publish(avail.c_str(), "online", true);
      mqtt.subscribe(topic("light", "set").c_str());
      publishLight();
    } else {
      delay(2000);
    }
  }
}

void setup() {
  pinMode(PIN_PIR, INPUT);
  pinMode(PIN_RELAY, OUTPUT);
  digitalWrite(PIN_RELAY, LOW);
  dht.begin();
  connectWifi();
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setCallback(onMessage);
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) connectWifi();
  if (!mqtt.connected()) connectMqtt();
  mqtt.loop();

  bool motion = digitalRead(PIN_PIR) == HIGH;
  if (motion != lastMotion) {
    lastMotion = motion;
    JsonDocument doc;
    doc["motion"] = motion;
    publishJson(topic("motion", "state"), doc);
  }

  if (millis() - lastSensorMs >= SENSOR_INTERVAL_MS) {
    lastSensorMs = millis();
    float t = dht.readTemperature();
    float h = dht.readHumidity();
    if (!isnan(t) && !isnan(h)) {
      JsonDocument doc;
      doc["temperature_c"] = round(t * 10) / 10.0;
      doc["humidity_pct"] = (int)h;
      publishJson(topic("climate", "state"), doc);
    }
  }
}
