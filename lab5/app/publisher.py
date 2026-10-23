"""Publicador MQTT del Lab 5.

Simula un sensor de sala con ciclo diario (hora de Colombia, UTC-5) y publica
cada PUBLISH_INTERVAL segundos un JSON con temperature (°C), humidity (%) e
illuminance (lux) en lab5/sensors/<DEVICE_ID>.
"""
import json
import math
import os
import random
import time
from datetime import datetime, timedelta, timezone

import paho.mqtt.client as mqtt

BROKER = os.environ.get("MQTT_HOST", "mosquitto")
PORT = int(os.environ.get("MQTT_PORT", "1883"))
DEVICE = os.environ.get("DEVICE_ID", "sim-01")
INTERVAL = float(os.environ.get("PUBLISH_INTERVAL", "10"))
TOPIC = f"lab5/sensors/{DEVICE}"
BOGOTA = timezone(timedelta(hours=-5))


def reading(now: datetime) -> dict:
    hour = now.hour + now.minute / 60
    # Máximo de temperatura ~15:00, mínimo ~03:00
    day = math.sin((hour - 9) / 24 * 2 * math.pi)
    temperature = 23 + 5 * day + random.gauss(0, 0.3)
    humidity = 62 - 14 * day + random.gauss(0, 1.0)
    # Luz natural entre 06:00 y 18:00, más luz artificial de oficina 07–19
    sun = max(0.0, math.sin((hour - 6) / 12 * math.pi)) if 6 <= hour <= 18 else 0.0
    office = 300 if 7 <= hour < 19 and now.weekday() < 5 else 0
    illuminance = 700 * sun + office + random.gauss(0, 15)
    return {
        "device": DEVICE,
        "temperature": round(temperature, 2),
        "humidity": round(min(100, max(0, humidity)), 2),
        "illuminance": round(max(0, illuminance), 1),
    }


def main() -> None:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"publisher-{DEVICE}")
    client.username_pw_set(os.environ["MQTT_USER"], os.environ["MQTT_PASS"])
    client.on_connect = lambda c, u, f, rc, p: print(f"conectado a {BROKER}:{PORT} rc={rc}", flush=True)
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    client.connect_async(BROKER, PORT, keepalive=60)
    client.loop_start()

    while True:
        payload = reading(datetime.now(BOGOTA))
        info = client.publish(TOPIC, json.dumps(payload), qos=1)
        print(f"{datetime.now(timezone.utc).isoformat()} {TOPIC} {payload} rc={info.rc}", flush=True)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
