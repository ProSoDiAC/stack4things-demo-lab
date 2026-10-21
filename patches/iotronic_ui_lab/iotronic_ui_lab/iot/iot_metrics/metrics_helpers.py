# -*- coding: utf-8 -*-
"""HTTP client for metrics-server from Horizon (Python 2.7)."""

import json
import logging
import os

try:
    import urllib2
except ImportError:
    import urllib.request as urllib2

LOG = logging.getLogger(__name__)

METRICS_SERVER_URL = os.environ.get(
    "METRICS_SERVER_URL", "http://metrics-gateway:8093"
)


def _url(path):
    return "{0}{1}".format(METRICS_SERVER_URL.rstrip("/"), path)


def _request(method, path, body=None, timeout=20):
    data = None
    headers = {"Content-Type": "application/json"}
    if body is not None:
        data = json.dumps(body)
    req = urllib2.Request(_url(path), data=data, headers=headers)
    req.get_method = lambda: method
    return urllib2.urlopen(req, timeout=timeout)


def list_streams(board_uuid=None):
    path = "/v1/streams"
    if board_uuid:
        path = "{0}?board_uuid={1}".format(path, board_uuid)
    resp = _request("GET", path)
    payload = json.loads(resp.read())
    return payload.get("streams", [])


def list_active_streams(window_minutes=15):
    path = "/v1/streams/active?window_minutes={0}".format(int(window_minutes))
    resp = _request("GET", path)
    payload = json.loads(resp.read())
    return payload.get("streams", []), payload.get("window_minutes", window_minutes)


def provision_stream(payload):
    resp = _request("POST", "/v1/streams/provision", body=payload)
    return json.loads(resp.read())


def recent_points(stream_id, board="", limit=20):
    path = "/v1/metrics/recent?stream_id={0}&limit={1}".format(stream_id, int(limit))
    if board:
        path = "{0}&board={1}".format(path, board)
    resp = _request("GET", path)
    payload = json.loads(resp.read())
    return payload.get("points", [])


def server_health():
    resp = _request("GET", "/health", timeout=5)
    return json.loads(resp.read())
