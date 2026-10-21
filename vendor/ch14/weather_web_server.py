#!/usr/bin/env python3
"""
Weather Station WoT Server — Messina Lab Edition
Board-local HTTP thing exposed via Stack4Things WSTUN.

Endpoints:
  GET  /             Dashboard UI (HTML)
  GET  /sensors      Board sensor data (JSON)
  GET  /led/status   LED state (JSON)
  POST /led/toggle   Toggle LED (JSON)
  POST /led/on       Turn LED ON
  POST /led/off      Turn LED OFF
  GET  /opendata     Messina open data aggregated (JSON)
  GET  /history      Last N sensor readings (JSON)
"""

import http.server
import json
import math
import os
import random
import sys
import time
import threading
from urllib.parse import urlparse, parse_qs
try:
    from urllib.request import urlopen, Request
    from urllib.error import URLError
except ImportError:
    from urllib2 import urlopen, Request, URLError

# ── Board state ──────────────────────────────────────────────────────────────
LED_STATE = {"on": False, "pin": 18}
HISTORY = []          # rolling buffer of sensor readings
HISTORY_MAX = 60

# ── Messina open sources ─────────────────────────────────────────────────────
# Open-Meteo: free, no API key, WMO station Messina (lat 38.19, lon 15.55)
OPEN_METEO = (
    "https://api.open-meteo.com/v1/forecast"
    "?latitude=38.19&longitude=15.55"
    "&current=temperature_2m,relative_humidity_2m,wind_speed_10m,"
    "precipitation,weather_code,surface_pressure"
    "&wind_speed_unit=ms&timezone=Europe%2FRome"
)

# Nominatim geocoder (just for city info)
NOMINATIM = "https://nominatim.openstreetmap.org/search?q=Messina,Italy&format=json&limit=1"

WMO_CODES = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Rime fog", 51: "Light drizzle", 53: "Moderate drizzle",
    55: "Dense drizzle", 61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow", 77: "Snow grains",
    80: "Slight showers", 81: "Moderate showers", 82: "Violent showers",
    85: "Slight snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm+hail", 99: "Thunderstorm+heavy hail",
}

_opendata_cache = {"data": None, "ts": 0, "ttl": 300}
_opendata_lock = threading.Lock()


# ── Simulated sensors ─────────────────────────────────────────────────────────
def read_board_sensors():
    t = time.time()
    temp = round(20.0 + 4 * math.sin(t / 50) + random.uniform(-0.3, 0.3), 1)
    hum  = round(55 + 10 * math.sin(t / 70) + random.uniform(-1, 1), 1)
    pres = round(1013.0 + 5 * math.sin(t / 120) + random.uniform(-0.5, 0.5), 1)
    lux  = max(0, int(400 + 350 * math.sin(t / 30) + random.randint(-30, 30)))
    uv   = round(max(0, 3.5 + 3 * math.sin(t / 35)), 1)
    co2  = int(420 + 80 * math.sin(t / 90) + random.randint(-10, 10))
    data = {
        "timestamp": t,
        "temperature": temp,
        "humidity": hum,
        "pressure": pres,
        "light_lux": lux,
        "uv_index": uv,
        "co2_ppm": co2,
        "led": "on" if LED_STATE["on"] else "off",
        "device": "weather-station",
    }
    HISTORY.append({"ts": t, "temp": temp, "hum": hum, "pres": pres, "lux": lux})
    if len(HISTORY) > HISTORY_MAX:
        HISTORY.pop(0)
    return data


def fetch_opendata():
    with _opendata_lock:
        now = time.time()
        if _opendata_cache["data"] and now - _opendata_cache["ts"] < _opendata_cache["ttl"]:
            return _opendata_cache["data"]
    result = {"source": "open-meteo.com", "city": "Messina, IT", "error": None}
    try:
        req = Request(OPEN_METEO, headers={"User-Agent": "WoT-WeatherStation/1.0"})
        with urlopen(req, timeout=8) as r:
            d = json.loads(r.read().decode())
        cur = d.get("current", {})
        result.update({
            "temperature": cur.get("temperature_2m"),
            "humidity": cur.get("relative_humidity_2m"),
            "wind_speed_ms": cur.get("wind_speed_10m"),
            "precipitation_mm": cur.get("precipitation"),
            "pressure_hpa": cur.get("surface_pressure"),
            "weather_code": cur.get("weather_code"),
            "weather_desc": WMO_CODES.get(cur.get("weather_code", -1), "Unknown"),
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })
    except Exception as e:
        result["error"] = str(e)[:120]
    with _opendata_lock:
        _opendata_cache["data"] = result
        _opendata_cache["ts"] = time.time()
    return result


# ── HTTP Handler ──────────────────────────────────────────────────────────────
class WeatherHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send(self, code, ctype, body):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, payload):
        self._send(code, "application/json", json.dumps(payload))

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        qs = parse_qs(urlparse(self.path).query)
        if path == "/" or path == "":
            self._send(200, "text/html; charset=utf-8", DASHBOARD_HTML)
        elif path == "/sensors":
            self._json(200, read_board_sensors())
        elif path == "/led/status":
            self._json(200, {"state": "on" if LED_STATE["on"] else "off", "pin": LED_STATE["pin"]})
        elif path == "/opendata":
            self._json(200, fetch_opendata())
        elif path == "/history":
            n = int(qs.get("n", ["30"])[0])
            self._json(200, {"readings": HISTORY[-n:], "total": len(HISTORY)})
        else:
            self._send(404, "text/plain", "Not found")

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/led/toggle":
            LED_STATE["on"] = not LED_STATE["on"]
        elif path == "/led/on":
            LED_STATE["on"] = True
        elif path == "/led/off":
            LED_STATE["on"] = False
        else:
            self._send(404, "text/plain", "Not found")
            return
        self._json(200, {"state": "on" if LED_STATE["on"] else "off", "pin": LED_STATE["pin"]})


# ── Dashboard HTML ────────────────────────────────────────────────────────────
DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Messina Weather Station — WoT</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:"Segoe UI",Helvetica,Arial,sans-serif;background:#0d1b2a;color:#cdd9e5;min-height:100vh}
header{background:linear-gradient(135deg,#1565c0,#0d47a1);padding:16px 24px;display:flex;align-items:center;gap:12px}
.logo{font-size:1.4rem}
.hdr-info h1{font-size:1.1rem;font-weight:700;color:#fff}
.hdr-info p{font-size:.8rem;color:#90caf9;margin-top:2px}
.hdr-info{flex:1}
.live-dot{width:10px;height:10px;border-radius:50%;background:#4caf50;display:inline-block;margin-right:6px;animation:pulse 2s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
.live-dot.err{background:#f44336;animation:none}
nav{background:#112240;display:flex;gap:2px;padding:6px 16px;overflow-x:auto}
nav button{background:none;border:0;color:#90a4ae;padding:8px 16px;border-radius:4px;cursor:pointer;font-size:.82rem;font-weight:600;white-space:nowrap;transition:all .15s}
nav button:hover{background:#1e3a5f;color:#e3f2fd}
nav button.active{background:#1565c0;color:#fff}
section{display:none;padding:16px;max-width:1400px;margin:0 auto}
section.show{display:block}
.grid{display:grid;gap:14px}
.g2{grid-template-columns:1fr 1fr}
.g3{grid-template-columns:repeat(3,1fr)}
.g4{grid-template-columns:repeat(4,1fr)}
@media(max-width:900px){.g3,.g4,.g2{grid-template-columns:1fr 1fr}}
@media(max-width:580px){.g3,.g4,.g2{grid-template-columns:1fr}}
.card{background:#112240;border-radius:10px;padding:16px;border:1px solid #1e3a5f}
.card h2{font-size:.75rem;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:#42a5f5;margin-bottom:12px}
/* Sensor tiles */
.stile{background:#0d1b2a;border-radius:8px;padding:14px;text-align:center;border:1px solid #1e3a5f}
.stile .icon{font-size:1.8rem;margin-bottom:6px}
.stile .lbl{font-size:.65rem;font-weight:700;color:#546e7a;text-transform:uppercase}
.stile .val{font-size:2rem;font-weight:700;color:#e3f2fd;line-height:1}
.stile .unit{font-size:.8rem;color:#78909c;margin-top:2px}
/* Trend sparkline */
canvas{display:block;width:100%;border-radius:6px}
/* LED */
.led-visual{width:70px;height:70px;border-radius:50%;margin:0 auto 12px;transition:all .3s;border:4px solid #37474f}
.led-visual.off{background:#37474f}
.led-visual.on{background:#ffeb3b;box-shadow:0 0 24px #ffeb3b,0 0 48px #ff9800;border-color:#f57f17}
.btn-row{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px}
button{border:0;border-radius:6px;padding:9px 16px;font-size:.8rem;font-weight:600;cursor:pointer;transition:filter .12s}
button:hover{filter:brightness(1.15)}
button:active{filter:brightness(.82)}
.b-blue{background:#1565c0;color:#fff}.b-green{background:#2e7d32;color:#fff}
.b-red{background:#c62828;color:#fff}.b-orange{background:#e65100;color:#fff}
.b-grey{background:#37474f;color:#fff}.b-yellow{background:#f57f17;color:#000}
.b-sm{padding:6px 12px;font-size:.75rem}
/* Open data */
.od-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:10px}
.od-item{background:#0d1b2a;border-radius:6px;padding:10px 12px;border:1px solid #1e3a5f}
.od-item .key{font-size:.65rem;font-weight:700;color:#42a5f5;text-transform:uppercase}
.od-item .val{font-size:1.1rem;font-weight:700;color:#e3f2fd;margin-top:4px}
.od-item .desc{font-size:.7rem;color:#546e7a;margin-top:2px}

.cam-card{background:#0d1b2a;border-radius:8px;overflow:hidden;border:1px solid #1e3a5f}
.cam-card img{width:100%;height:200px;object-fit:cover;display:block;background:#1e3a5f}
.cam-card .cam-info{padding:10px}
.cam-card .cam-name{font-size:.82rem;font-weight:700;color:#e3f2fd}
.cam-card .cam-desc{font-size:.72rem;color:#78909c;margin-top:2px}
.cam-card .cam-footer{display:flex;gap:6px;margin-top:8px;flex-wrap:wrap}
/* Status bar */
.status-bar{background:#0d1b2a;border-radius:6px;padding:8px 12px;font-size:.75rem;color:#546e7a;margin-top:12px;border:1px solid #1e3a5f}
.badge{display:inline-block;border-radius:10px;padding:2px 8px;font-size:.7rem;font-weight:700}
.badge.ok{background:#1b5e20;color:#a5d6a7}.badge.err{background:#b71c1c;color:#ffcdd2}.badge.warn{background:#e65100;color:#fff3e0}
/* Chart */
.chart-wrap{background:#0d1b2a;border-radius:8px;padding:10px;margin-top:8px}
input[type=range]{accent-color:#42a5f5;width:100%}
select{background:#0d1b2a;border:1px solid #1e3a5f;color:#cdd9e5;border-radius:4px;padding:6px 8px;font-size:.8rem}
</style>
</head>
<body>
<header>
  <div class="logo">&#127782;</div>
  <div class="hdr-info">
    <h1>Messina Weather Station — WoT Thing</h1>
    <p>Stack4Things &#8226; Lightning Rod board &#8226; HTTP Web Thing</p>
  </div>
  <span class="live-dot" id="live-dot"></span>
  <span id="live-txt" style="font-size:.78rem;color:#90caf9">LIVE</span>
</header>

<nav>
  <button class="active" onclick="tab('sensors',this)">&#127777; Board Sensors</button>
  <button onclick="tab('trend',this)">&#128200; Trend</button>
  <button onclick="tab('led',this)">&#128161; LED Control</button>
  <button onclick="tab('opendata',this)">&#127759; Messina Open Data</button>
  <button onclick="tab('api',this)">&#9654; WoT API</button>
</nav>

<!-- ── BOARD SENSORS ── -->
<section id="sec-sensors" class="show">
  <div class="grid g4" style="margin-bottom:14px">
    <div class="stile"><div class="icon">&#127777;</div><div class="lbl">Temperature</div><div class="val" id="v-temp">—</div><div class="unit">°C</div></div>
    <div class="stile"><div class="icon">&#128167;</div><div class="lbl">Humidity</div><div class="val" id="v-hum">—</div><div class="unit">%</div></div>
    <div class="stile"><div class="icon">&#129404;</div><div class="lbl">Pressure</div><div class="val" id="v-pres">—</div><div class="unit">hPa</div></div>
    <div class="stile"><div class="icon">&#9728;</div><div class="lbl">Light</div><div class="val" id="v-lux">—</div><div class="unit">lux</div></div>
    <div class="stile"><div class="icon">&#9728;&#65039;</div><div class="lbl">UV Index</div><div class="val" id="v-uv">—</div><div class="unit"></div></div>
    <div class="stile"><div class="icon">&#128168;</div><div class="lbl">CO₂</div><div class="val" id="v-co2">—</div><div class="unit">ppm</div></div>
    <div class="stile"><div class="icon">&#128161;</div><div class="lbl">LED</div><div class="val" id="v-led" style="font-size:1.2rem">OFF</div><div class="unit"></div></div>
    <div class="stile"><div class="icon">&#128336;</div><div class="lbl">Last update</div><div class="val" id="v-ts" style="font-size:.9rem;margin-top:4px">—</div><div class="unit"></div></div>
  </div>
  <div class="status-bar">Refresh 3 s &bull; Board: weather-station &bull; Proto: HTTP WoT &bull; Transport: WSTUN</div>
</section>

<!-- ── TREND ── -->
<section id="sec-trend">
  <div class="card">
    <h2>Sensor history (last readings from board)</h2>
    <div style="display:flex;gap:10px;margin-bottom:10px;flex-wrap:wrap;align-items:center">
      <label style="font-size:.8rem;color:#78909c">Show:</label>
      <select id="chart-metric" onchange="drawChart()">
        <option value="temp">Temperature (°C)</option>
        <option value="hum">Humidity (%)</option>
        <option value="pres">Pressure (hPa)</option>
        <option value="lux">Light (lux)</option>
      </select>
    </div>
    <div class="chart-wrap"><canvas id="trend-canvas" height="180"></canvas></div>
  </div>
</section>

<!-- ── LED CONTROL ── -->
<section id="sec-led">
  <div class="grid g2">
    <div class="card" style="text-align:center">
      <h2>Board LED (GPIO 18)</h2>
      <div class="led-visual off" id="led-vis"></div>
      <div style="font-size:1.2rem;font-weight:700;margin-bottom:12px" id="led-lbl">OFF</div>
      <div class="btn-row" style="justify-content:center">
        <button class="b-yellow" onclick="ledCmd('toggle')">&#128161; Toggle</button>
        <button class="b-green b-sm" onclick="ledCmd('on')">ON</button>
        <button class="b-red b-sm" onclick="ledCmd('off')">OFF</button>
      </div>
      <div style="font-size:.75rem;color:#546e7a;margin-top:12px">POST /led/toggle &bull; POST /led/on &bull; POST /led/off</div>
    </div>
    <div class="card">
      <h2>LED auto-blink</h2>
      <p style="font-size:.8rem;color:#78909c;margin-bottom:10px">Automatically toggles the LED at a set interval.</p>
      <label style="font-size:.8rem;color:#90a4ae">Interval: <span id="blink-val">1</span> s</label>
      <input type="range" min="1" max="10" value="1" id="blink-sl" oninput="document.getElementById('blink-val').textContent=this.value" style="margin:6px 0">
      <div class="btn-row">
        <button class="b-orange" id="btn-blink" onclick="toggleBlink()">Start blink</button>
      </div>
    </div>
  </div>
</section>

<!-- ── MESSINA OPEN DATA ── -->
<section id="sec-opendata">
  <div class="card" style="margin-bottom:14px">
    <h2>&#127759; Condizioni meteo attuali — Messina (Open-Meteo)</h2>
    <div class="od-grid" id="od-grid">
      <div class="od-item"><div class="key">Status</div><div class="val" id="od-status">Loading…</div></div>
    </div>
    <div style="margin-top:12px;display:flex;gap:8px;align-items:center;flex-wrap:wrap">
      <button class="b-blue b-sm" onclick="loadOpenData()">&#8635; Refresh</button>
      <a href="https://open-meteo.com/" target="_blank" rel="noopener" style="font-size:.75rem;color:#42a5f5">open-meteo.com</a>
      <span style="font-size:.75rem;color:#546e7a" id="od-ts"></span>
    </div>
  </div>
  <div class="card">
    <h2>&#128205; Risorse open data Messina</h2>
    <div class="grid g2" style="gap:10px">
      <div class="od-item">
        <div class="key">ARPA Sicilia</div>
        <div class="val" style="font-size:.85rem">Rete monitoraggio qualità aria</div>
        <div class="desc">Dati PM10, PM2.5, NO₂, O₃ per stazione Messina</div>
        <div class="cam-footer"><a href="https://www.arpa.sicilia.it/temi-ambientali/aria/dati/" target="_blank" rel="noopener"><button class="b-blue b-sm" style="margin-top:6px">Apri &#8599;</button></a></div>
      </div>
      <div class="od-item">
        <div class="key">Comune di Messina — Open Data</div>
        <div class="val" style="font-size:.85rem">Dataset comunali</div>
        <div class="desc">Trasparenza, mobilità, ambiente</div>
        <div class="cam-footer"><a href="https://www.comune.messina.it/it/amministrazione/opendata" target="_blank" rel="noopener"><button class="b-blue b-sm" style="margin-top:6px">Apri &#8599;</button></a></div>
      </div>
      <div class="od-item">
        <div class="key">OpenStreetMap Messina</div>
        <div class="val" style="font-size:.85rem">Mappa open source</div>
        <div class="desc">POI, infrastrutture, percorsi</div>
        <div class="cam-footer"><a href="https://www.openstreetmap.org/#map=13/38.1938/15.5540" target="_blank" rel="noopener"><button class="b-blue b-sm" style="margin-top:6px">Apri &#8599;</button></a></div>
      </div>
      <div class="od-item">
        <div class="key">ISPRA Stretto di Messina</div>
        <div class="val" style="font-size:.85rem">Dati marini e meteo-marini</div>
        <div class="desc">Correnti, livello mare, temperatura acqua</div>
        <div class="cam-footer"><a href="https://www.ispra.ambiente.it/" target="_blank" rel="noopener"><button class="b-blue b-sm" style="margin-top:6px">Apri &#8599;</button></a></div>
      </div>
    </div>
  </div>
</section>

<!-- ── WoT API ── -->
<section id="sec-api">
  <div class="grid g2">
    <div class="card">
      <h2>WoT HTTP Endpoints</h2>
      <table style="width:100%;border-collapse:collapse;font-size:.78rem">
        <thead><tr style="background:#0d1b2a"><th style="padding:6px;text-align:left;color:#42a5f5">Method</th><th style="padding:6px;text-align:left;color:#42a5f5">Path</th><th style="padding:6px;text-align:left;color:#42a5f5">Description</th></tr></thead>
        <tbody id="api-table">
          <tr><td style="padding:5px 6px"><span class="badge ok">GET</span></td><td style="padding:5px 6px;font-family:monospace">/sensors</td><td style="padding:5px 6px;color:#78909c">Board sensor data</td></tr>
          <tr style="background:#0d1b2a"><td><span class="badge ok">GET</span></td><td style="font-family:monospace;padding:5px 6px">/led/status</td><td style="color:#78909c;padding:5px 6px">LED state</td></tr>
          <tr><td><span class="badge warn">POST</span></td><td style="font-family:monospace;padding:5px 6px">/led/toggle</td><td style="color:#78909c;padding:5px 6px">Toggle LED</td></tr>
          <tr style="background:#0d1b2a"><td><span class="badge warn">POST</span></td><td style="font-family:monospace;padding:5px 6px">/led/on</td><td style="color:#78909c;padding:5px 6px">Turn ON</td></tr>
          <tr><td><span class="badge warn">POST</span></td><td style="font-family:monospace;padding:5px 6px">/led/off</td><td style="color:#78909c;padding:5px 6px">Turn OFF</td></tr>
          <tr style="background:#0d1b2a"><td><span class="badge ok">GET</span></td><td style="font-family:monospace;padding:5px 6px">/opendata</td><td style="color:#78909c;padding:5px 6px">Meteo Messina</td></tr>
          <tr><td><span class="badge ok">GET</span></td><td style="font-family:monospace;padding:5px 6px">/history?n=30</td><td style="color:#78909c;padding:5px 6px">Reading history</td></tr>
        </tbody>
      </table>
    </div>
    <div class="card">
      <h2>Console</h2>
      <div style="display:flex;gap:6px;margin-bottom:8px;flex-wrap:wrap">
        <select id="c-m" style="width:70px"><option>GET</option><option>POST</option></select>
        <input type="text" id="c-p" value="/sensors" style="flex:1;background:#0d1b2a;border:1px solid #1e3a5f;color:#cdd9e5;border-radius:4px;padding:5px 8px;font-size:.8rem">
        <button class="b-blue b-sm" onclick="consoleSend()">Send</button>
      </div>
      <div style="background:#0d1b2a;border-radius:6px;padding:10px;font-family:monospace;font-size:.73rem;color:#a5d6a7;min-height:80px;max-height:300px;overflow-y:auto;white-space:pre-wrap;word-break:break-all;border:1px solid #1e3a5f" id="con">Ready.</div>
    </div>
  </div>
</section>

<script>
var REFRESH_MS = 3000;
var boardData = null;

// ── Tab navigation ──
function tab(name, btn) {
  document.querySelectorAll('section').forEach(function(s){ s.classList.remove('show'); });
  document.querySelectorAll('nav button').forEach(function(b){ b.classList.remove('active'); });
  document.getElementById('sec-'+name).classList.add('show');
  btn.classList.add('active');
  if (name === 'trend') drawChart();
  if (name === 'opendata' && !document.getElementById('od-grid').children.length > 1) loadOpenData();
}

// ── Sensors ──
function refreshSensors() {
  fetch('/sensors', {headers:{Accept:'application/json'}})
    .then(function(r){ return r.json(); })
    .then(function(d){
      boardData = d;
      set('v-temp', d.temperature);
      set('v-hum', d.humidity);
      set('v-pres', d.pressure);
      set('v-lux', d.light_lux);
      set('v-uv', d.uv_index);
      set('v-co2', d.co2_ppm);
      set('v-led', d.led.toUpperCase());
      set('v-ts', new Date(d.timestamp*1000).toLocaleTimeString());
      applyLed(d.led === 'on');
      setLive(true);
    }).catch(function(){ setLive(false); });
}

function setLive(ok) {
  var d = document.getElementById('live-dot');
  var t = document.getElementById('live-txt');
  d.className = 'live-dot' + (ok ? '' : ' err');
  t.textContent = ok ? 'LIVE' : 'ERR';
}

// ── LED ──
function ledCmd(cmd) {
  fetch('/led/'+cmd, {method:'POST'})
    .then(function(r){ return r.json(); })
    .then(function(d){ applyLed(d.state === 'on'); });
}
function applyLed(on) {
  var v = document.getElementById('led-vis');
  var l = document.getElementById('led-lbl');
  var v2 = document.getElementById('v-led');
  if (!v) return;
  v.className = 'led-visual ' + (on ? 'on' : 'off');
  if (l) l.textContent = on ? 'ON' : 'OFF';
  if (v2) v2.textContent = on ? 'ON' : 'OFF';
}
var blinkId = null;
function toggleBlink() {
  var btn = document.getElementById('btn-blink');
  if (blinkId) { clearInterval(blinkId); blinkId = null; btn.textContent = 'Start blink'; return; }
  btn.textContent = 'Stop blink';
  var sl = document.getElementById('blink-sl');
  blinkId = setInterval(function(){
    var secs = +(sl ? sl.value : 1);
    ledCmd('toggle');
  }, +(sl ? sl.value : 1) * 1000);
}

// ── Trend chart ──
var chartHistory = [];
function drawChart() {
  var metric = document.getElementById('chart-metric').value;
  var canvas = document.getElementById('trend-canvas');
  if (!canvas) return;
  fetch('/history?n=60')
    .then(function(r){ return r.json(); })
    .then(function(d){
      chartHistory = d.readings || [];
      renderCanvas(canvas, metric);
    }).catch(function(){
      if (chartHistory.length) renderCanvas(canvas, metric);
    });
}
function renderCanvas(canvas, metric) {
  var data = chartHistory.map(function(r){ return r[metric] || 0; });
  if (!data.length) return;
  var W = canvas.parentElement.offsetWidth - 20;
  var H = 180;
  canvas.width = W; canvas.height = H;
  var ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, W, H);
  var min = Math.min.apply(null, data), max = Math.max.apply(null, data);
  var pad = (max - min) * 0.1 || 1;
  min -= pad; max += pad;
  ctx.fillStyle = '#0d1b2a'; ctx.fillRect(0, 0, W, H);
  // grid
  ctx.strokeStyle = '#1e3a5f'; ctx.lineWidth = 1;
  for (var i = 0; i <= 4; i++) {
    var y = H * i / 4;
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke();
    var v = max - (max-min)*i/4;
    ctx.fillStyle = '#546e7a'; ctx.font = '10px sans-serif';
    ctx.fillText(v.toFixed(1), 4, y > 10 ? y - 3 : y + 12);
  }
  // line
  ctx.strokeStyle = '#42a5f5'; ctx.lineWidth = 2;
  ctx.shadowColor = '#42a5f5'; ctx.shadowBlur = 4;
  ctx.beginPath();
  data.forEach(function(v, i){
    var x = i / (data.length - 1 || 1) * W;
    var y = H - (v - min) / (max - min) * H;
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  });
  ctx.stroke();
  ctx.shadowBlur = 0;
  // fill under
  ctx.lineTo(W, H); ctx.lineTo(0, H); ctx.closePath();
  ctx.fillStyle = 'rgba(66,165,245,.08)'; ctx.fill();
  // last value label
  if (data.length) {
    var lv = data[data.length-1];
    ctx.fillStyle = '#e3f2fd'; ctx.font = 'bold 13px sans-serif';
    ctx.fillText(lv.toFixed(1), W - 50, 20);
  }
}

// ── Open data ──
function loadOpenData() {
  var grid = document.getElementById('od-grid');
  var ts = document.getElementById('od-ts');
  grid.innerHTML = '<div class="od-item"><div class="key">Loading…</div></div>';
  fetch('/opendata').then(function(r){ return r.json(); }).then(function(d){
    var items = [];
    if (d.error) {
      items.push({k:'Error',v:d.error,desc:'Controlla connessione'});
    } else {
      items = [
        {k:'Condition',v:d.weather_desc||'—',desc:'WMO code '+d.weather_code},
        {k:'Temperature',v:(d.temperature!=null?d.temperature+'°C':'—'),desc:'2 m above ground'},
        {k:'Humidity',v:(d.humidity!=null?d.humidity+'%':'—'),desc:'Relative humidity'},
        {k:'Wind',v:(d.wind_speed_ms!=null?d.wind_speed_ms+' m/s':'—'),desc:'10 m height'},
        {k:'Precipitation',v:(d.precipitation_mm!=null?d.precipitation_mm+' mm':'—'),desc:'Last hour'},
        {k:'Pressure',v:(d.pressure_hpa!=null?d.pressure_hpa+' hPa':'—'),desc:'Surface pressure'},
        {k:'Source',v:'Open-Meteo',desc:d.city||'Messina, IT'},
      ];
    }
    grid.innerHTML = items.map(function(i){
      return '<div class="od-item"><div class="key">'+i.k+'</div><div class="val">'+i.v+'</div><div class="desc">'+i.desc+'</div></div>';
    }).join('');
    if (ts && d.fetched_at) ts.textContent = 'fetched: '+d.fetched_at;
  }).catch(function(e){ grid.innerHTML = '<div class="od-item"><div class="key">Error</div><div class="val">'+e+'</div></div>'; });
}

// ── Console ──
function consoleSend() {
  var m = document.getElementById('c-m').value;
  var p = document.getElementById('c-p').value;
  var t0 = Date.now();
  fetch(p, {method:m, headers:{Accept:'application/json'}})
    .then(function(r){ return r.json().then(function(d){ conLog(m+' '+p+' → '+r.status+' ('+(Date.now()-t0)+'ms)\n'+JSON.stringify(d,null,2)); }); })
    .catch(function(e){ conLog('Error: '+e); });
}
function conLog(msg) { var c=document.getElementById('con'); c.textContent+='\n'+msg; c.scrollTop=c.scrollHeight; }
function set(id,v) { var e=document.getElementById(id); if(e) e.textContent=v; }

// ── Boot ──
refreshSensors();
loadOpenData();
setInterval(refreshSensors, REFRESH_MS);
setInterval(drawChart, 10000);
</script>
</body>
</html>
"""


# ── Server startup ────────────────────────────────────────────────────────────
class ReusableTCPServer(http.server.HTTPServer):
    allow_reuse_address = True


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8088
    server = ReusableTCPServer(("", port), WeatherHandler)
    print("Weather Station WoT on port %d" % port)
    server.serve_forever()


if __name__ == "__main__":
    main()
