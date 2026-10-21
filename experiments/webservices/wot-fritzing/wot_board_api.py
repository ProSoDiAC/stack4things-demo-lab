#!/usr/bin/env python3
"""WoT board simulator API — multi-actuator Fritzing lab backend."""

import json
import math
import random
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

# Simulated board state (GPIO map like a lab CPS)
STATE = {
    "leds": {
        "red": {"on": False, "pin": 18},
        "green": {"on": False, "pin": 23},
        "yellow": {"on": False, "pin": 24},
        "blue": {"on": False, "pin": 25},
    },
    "rgb": {"r": 0, "g": 0, "b": 0},
    "buzzer": {"active": False, "pattern": None, "until": 0},
    "servo": {"angle": 90, "pin": 12},
    "motor": {"speed": 0, "pin": 13},
    "relay": {"on": False, "pin": 16},
    "button": {"pressed": False, "pin": 4},
    "display": {"line1": "Stack4Things", "line2": "WoT Fritzing Lab"},
    "sensors": {
        "temperature": 22.0,
        "humidity": 48.0,
        "light": 512,
        "motion": False,
        "distance_cm": 42.0,
    },
    "updated_at": time.time(),
}

SCENARIOS = {
    "party": {"rgb": [255, 0, 255], "motor": 80, "pattern": "pulse"},
    "alarm": {"leds": ["red", "yellow"], "pattern": "alarm", "display": ("!! ALARM !!", "Motion detected")},
    "eco": {"leds": ["green"], "motor": 30, "display": ("ECO mode", "Temp OK")},
    "sleep": {"leds": [], "motor": 0, "rgb": [0, 0, 20], "display": ("Sleep", "All off")},
    "demo": {"servo": 45, "leds": ["red", "green", "blue"], "beep": True},
}


def _touch():
    STATE["updated_at"] = time.time()


def _simulate_sensors():
    s = STATE["sensors"]
    t = time.time()
    s["temperature"] = round(21.5 + 3 * math.sin(t / 40) + random.uniform(-0.3, 0.3), 1)
    s["humidity"] = round(48 + 8 * math.sin(t / 55) + random.uniform(-1, 1), 1)
    s["light"] = int(max(0, min(1023, 400 + 300 * math.sin(t / 25) + random.randint(-30, 30))))
    s["distance_cm"] = round(40 + 15 * math.sin(t / 12), 1)
    if STATE["motion"] if "motion" in STATE else False:
        pass
    STATE["sensors"]["motion"] = s["light"] < 200 or STATE["button"]["pressed"]


def _led_payload():
    return {k: {"on": v["on"], "pin": v["pin"]} for k, v in STATE["leds"].items()}


def _full_circuit():
    _simulate_sensors()
    buzz = STATE["buzzer"]
    if buzz["until"] and time.time() > buzz["until"]:
        buzz["active"] = False
        buzz["pattern"] = None
        buzz["until"] = 0
    return {
        "leds": _led_payload(),
        "rgb": dict(STATE["rgb"]),
        "buzzer": {
            "active": buzz["active"],
            "pattern": buzz["pattern"],
        },
        "servo": dict(STATE["servo"]),
        "motor": dict(STATE["motor"]),
        "relay": dict(STATE["relay"]),
        "button": dict(STATE["button"]),
        "display": dict(STATE["display"]),
        "sensors": dict(STATE["sensors"]),
        "updated_at": STATE["updated_at"],
    }


def _thing_description():
    return {
        "@context": "https://www.w3.org/2019/wot/td/v1",
        "title": "Fritzing Board Lab Thing",
        "description": "Multi-actuator CPS demo on Lightning Rod",
        "properties": {
            "circuit": {"href": "/api/circuit", "contentType": "application/json"},
            "sensors": {"href": "/api/sensors", "contentType": "application/json"},
            "leds": {"href": "/api/leds", "contentType": "application/json"},
        },
        "actions": {
            "toggleLed": {"href": "/api/led/{color}/toggle"},
            "setRgb": {"href": "/api/rgb", "contentType": "application/json"},
            "setServo": {"href": "/api/servo", "contentType": "application/json"},
            "setMotor": {"href": "/api/motor", "contentType": "application/json"},
            "beep": {"href": "/api/buzzer/beep"},
            "runScenario": {"href": "/api/scenario/{name}"},
            "setDisplay": {"href": "/api/display", "contentType": "application/json"},
        },
    }


class WoTBoardHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length < 1:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return {}

    def _json(self, code, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        qs = parse_qs(parsed.query)

        if path == "/api/circuit":
            self._json(200, _full_circuit())
        elif path == "/api/sensors":
            _simulate_sensors()
            _touch()
            self._json(200, STATE["sensors"])
        elif path == "/api/leds":
            self._json(200, _led_payload())
        elif path.startswith("/api/led/") and path.endswith("/status"):
            color = path.split("/")[3]
            if color not in STATE["leds"]:
                self.send_error(404)
                return
            led = STATE["leds"][color]
            self._json(200, {"color": color, "on": led["on"], "pin": led["pin"]})
        elif path == "/api/buzzer/status":
            self._json(200, STATE["buzzer"])
        elif path == "/api/servo":
            self._json(200, STATE["servo"])
        elif path == "/api/motor":
            self._json(200, STATE["motor"])
        elif path == "/api/relay":
            self._json(200, STATE["relay"])
        elif path == "/api/button":
            self._json(200, STATE["button"])
        elif path == "/api/display":
            self._json(200, STATE["display"])
        elif path == "/api/rgb":
            self._json(200, STATE["rgb"])
        elif path == "/api/thing":
            self._json(200, _thing_description())
        elif path in ("/api/led/status", "/led/status"):
            red = STATE["leds"]["red"]
            self._json(200, {
                "state": "on" if red["on"] else "off",
                "pin": red["pin"],
                "updated_at": STATE["updated_at"],
            })
        else:
            self.send_error(404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        body = self._read_json()

        # Legacy single LED (red)
        if path == "/led/toggle":
            STATE["leds"]["red"]["on"] = not STATE["leds"]["red"]["on"]
            _touch()
            r = STATE["leds"]["red"]
            self._json(200, {"state": "on" if r["on"] else "off", "pin": r["pin"]})
            return
        if path == "/led/on":
            STATE["leds"]["red"]["on"] = True
            _touch()
            self._json(200, {"state": "on", "pin": STATE["leds"]["red"]["pin"]})
            return
        if path == "/led/off":
            STATE["leds"]["red"]["on"] = False
            _touch()
            self._json(200, {"state": "off", "pin": STATE["leds"]["red"]["pin"]})
            return

        if path.startswith("/api/led/"):
            parts = path.split("/")
            if len(parts) < 4:
                self.send_error(404)
                return
            color, action = parts[3], parts[4] if len(parts) > 4 else "toggle"
            if color not in STATE["leds"]:
                self.send_error(404)
                return
            if action == "toggle":
                STATE["leds"][color]["on"] = not STATE["leds"][color]["on"]
            elif action == "on":
                STATE["leds"][color]["on"] = True
            elif action == "off":
                STATE["leds"][color]["on"] = False
            else:
                self.send_error(404)
                return
            _touch()
            self._json(200, {"color": color, "on": STATE["leds"][color]["on"]})
            return

        if path == "/api/leds/all/on":
            for led in STATE["leds"].values():
                led["on"] = True
            _touch()
            self._json(200, _led_payload())
            return
        if path == "/api/leds/all/off":
            for led in STATE["leds"].values():
                led["on"] = False
            _touch()
            self._json(200, _led_payload())
            return

        if path == "/api/rgb":
            for ch in ("r", "g", "b"):
                if ch in body:
                    STATE["rgb"][ch] = max(0, min(255, int(body[ch])))
            for name, key in (("red", "r"), ("green", "g"), ("blue", "b")):
                STATE["leds"][name]["on"] = STATE["rgb"][key] > 32
            _touch()
            self._json(200, STATE["rgb"])
            return

        if path == "/api/buzzer/beep":
            dur = float(body.get("duration", 0.3))
            STATE["buzzer"] = {"active": True, "pattern": "beep", "until": time.time() + dur}
            _touch()
            self._json(200, STATE["buzzer"])
            return
        if path == "/api/buzzer/pattern":
            pat = body.get("pattern", "pulse")
            dur = float(body.get("duration", 2.0))
            STATE["buzzer"] = {"active": True, "pattern": pat, "until": time.time() + dur}
            _touch()
            self._json(200, STATE["buzzer"])
            return

        if path == "/api/servo":
            angle = int(body.get("angle", STATE["servo"]["angle"]))
            STATE["servo"]["angle"] = max(0, min(180, angle))
            _touch()
            self._json(200, STATE["servo"])
            return

        if path == "/api/motor":
            speed = int(body.get("speed", 0))
            STATE["motor"]["speed"] = max(0, min(100, speed))
            _touch()
            self._json(200, STATE["motor"])
            return

        if path == "/api/relay/toggle":
            STATE["relay"]["on"] = not STATE["relay"]["on"]
            _touch()
            self._json(200, STATE["relay"])
            return
        if path == "/api/relay/on":
            STATE["relay"]["on"] = True
            _touch()
            self._json(200, STATE["relay"])
            return
        if path == "/api/relay/off":
            STATE["relay"]["on"] = False
            _touch()
            self._json(200, STATE["relay"])
            return

        if path == "/api/button/press":
            STATE["button"]["pressed"] = True
            _touch()
            self._json(200, STATE["button"])
            return
        if path == "/api/button/release":
            STATE["button"]["pressed"] = False
            _touch()
            self._json(200, STATE["button"])
            return

        if path == "/api/display":
            if "line1" in body:
                STATE["display"]["line1"] = str(body["line1"])[:16]
            if "line2" in body:
                STATE["display"]["line2"] = str(body["line2"])[:16]
            _touch()
            self._json(200, STATE["display"])
            return

        if path.startswith("/api/scenario/"):
            name = path.split("/")[-1]
            if name not in SCENARIOS:
                self.send_error(404)
                return
            self._run_scenario(name)
            _touch()
            self._json(200, {"scenario": name, "circuit": _full_circuit()})
            return

        self.send_error(404)

    def _run_scenario(self, name):
        sc = SCENARIOS[name]
        for led in STATE["leds"]:
            STATE["leds"][led]["on"] = led in sc.get("leds", [])
        if "rgb" in sc:
            r, g, b = sc["rgb"]
            STATE["rgb"] = {"r": r, "g": g, "b": b}
        if "motor" in sc:
            STATE["motor"]["speed"] = sc["motor"]
        if "servo" in sc:
            STATE["servo"]["angle"] = sc["servo"]
        if "display" in sc:
            STATE["display"]["line1"] = sc["display"][0]
            STATE["display"]["line2"] = sc["display"][1]
        if sc.get("pattern"):
            STATE["buzzer"] = {
                "active": True,
                "pattern": sc["pattern"],
                "until": time.time() + 3,
            }
        if sc.get("beep"):
            STATE["buzzer"] = {"active": True, "pattern": "beep", "until": time.time() + 0.5}


def main():
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8091
    server = HTTPServer(("127.0.0.1", port), WoTBoardHandler)
    print("WoT Board API on 127.0.0.1:%d" % port)
    server.serve_forever()


if __name__ == "__main__":
    main()
