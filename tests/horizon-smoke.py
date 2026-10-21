#!/usr/bin/env python3
"""Log into Horizon like a browser and load every IoT panel; fail on HTTP errors / Django tracebacks."""
import http.cookiejar
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

HOST = os.environ.get("S4T_HORIZON_HOST", "127.0.0.1")
USER, PASSWORD = "admin", os.environ.get("ADMIN_PASS", "s4t")
PANELS = [
    "/horizon/iot/", "/horizon/iot/fleets/", "/horizon/iot/plugins/", "/horizon/iot/services/",
    "/horizon/iot/federated_learning/", "/horizon/iot/iot_metrics/", "/horizon/iot/iot_wot/",
]
EXTRA = [  # reverse proxies to the lab helper containers (same origin for the iframes)
    ("/horizon/fl-live/", (200,)), ("/horizon/metrics-live/login", (200, 302)),
]

jar = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def get(path):
    try:
        r = op.open(f"http://{HOST}{path}", timeout=60)
        return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


status, page = get("/horizon/auth/login/")
token = re.search(r"name=['\"]csrfmiddlewaretoken['\"]\s+value=['\"]([^'\"]+)['\"]", page).group(1)
data = urllib.parse.urlencode({"csrfmiddlewaretoken": token, "username": USER, "password": PASSWORD,
                               "region": "http://keystone:5000/v3"}).encode()
req = urllib.request.Request(f"http://{HOST}/horizon/auth/login/", data=data,
                             headers={"Referer": f"http://{HOST}/horizon/auth/login/"})
try:
    r = op.open(req, timeout=60)
    body = r.read().decode("utf-8", "replace")
except urllib.error.HTTPError as e:
    print("FAIL login HTTP", e.code); sys.exit(1)
if "/auth/login" in r.geturl() and "Invalid" in body:
    print("FAIL login rejected"); sys.exit(1)
print("OK   login admin ->", r.geturl())

bad = 0
for path in PANELS:
    code, html = get(path)
    ok = code == 200 and "Traceback" not in html and "Something went wrong" not in html and "/auth/login" not in html[:3000]
    print(("OK   " if ok else "FAIL ") + f"{path} HTTP {code}")
    bad += not ok
for path, allowed in EXTRA:
    code, _ = get(path)
    ok = code in allowed
    print(("OK   " if ok else "FAIL ") + f"{path} HTTP {code}")
    bad += not ok
sys.exit(1 if bad else 0)
