# -*- coding: utf-8 -*-
"""Shared Lightning-Rod log helpers for lab Horizon panels."""

import json
import logging
import os

try:
    import urllib2
    from urllib import quote as urlquote
except ImportError:
    import urllib.request as urllib2
    from urllib.parse import quote as urlquote

LOG = logging.getLogger(__name__)

LR_LOG_PROXY_URL = os.environ.get(
    "LR_LOG_PROXY_URL", "http://lr-log-proxy:8092"
)
DEFAULT_LOG_GREP = "PluginCall|Hello |PluginInject|PluginStart|PluginStop|RPC "


def safe_exc_text(exc):
    try:
        if exc is None:
            return ""
        if isinstance(exc, unicode):
            return exc.encode("ascii", "replace")
        if isinstance(exc, str):
            return exc.decode("utf-8", "replace").encode("ascii", "replace")
        return unicode(exc).encode("ascii", "replace")
    except Exception:
        return "unknown error"


def fetch_lr_logs(board_names=None, board_uuids=None, tail=40, grep=None, refresh=False):
    names = [n for n in (board_names or []) if n]
    uuids = [u for u in (board_uuids or []) if u]
    if not names and not uuids:
        return {}
    base = LR_LOG_PROXY_URL.rstrip("/")
    parts = ["tail={0}".format(int(tail))]
    if names:
        parts.append("boards={0}".format(urlquote(",".join(names))))
    if uuids:
        parts.append("board_uuids={0}".format(urlquote(",".join(uuids))))
    if grep:
        parts.append("grep={0}".format(urlquote(grep)))
    if refresh:
        parts.append("refresh=1")
    url = "{0}/api/lr-logs?{1}".format(base, "&".join(parts))
    try:
        resp = urllib2.urlopen(url, timeout=25)
        payload = json.loads(resp.read())
        return payload.get("boards", {})
    except Exception as exc:
        LOG.warning("fetch_lr_logs failed: %s", exc)
        err = safe_exc_text(exc)
        out = {}
        for n in names:
            out[n] = {
                "container": None,
                "lines": ["[error] log proxy unreachable ({0})".format(err)],
            }
        for u in uuids:
            out[u] = {
                "container": None,
                "lines": ["[error] log proxy unreachable ({0})".format(err)],
            }
        return out


def board_log_panel(board_name, board_uuid, tail=40, grep=None):
    grep = grep if grep is not None else DEFAULT_LOG_GREP
    raw = fetch_lr_logs(
        board_names=[board_name] if board_name else None,
        board_uuids=[board_uuid] if board_uuid else None,
        tail=tail,
        grep=grep,
    )
    entry = raw.get(board_name) or raw.get(board_uuid) or {}
    lines = entry.get("lines") or ["[empty]"]
    return {
        "board_name": board_name,
        "board_uuid": board_uuid,
        "container": entry.get("container"),
        "text": "\n".join(lines),
    }


def fleet_log_panels(boards, tail=40, grep=None):
    grep = grep if grep is not None else DEFAULT_LOG_GREP
    names = [b.name for b in boards]
    raw = fetch_lr_logs(board_names=names, tail=tail, grep=grep)
    panels = []
    for board in boards:
        entry = raw.get(board.name, {})
        lines = entry.get("lines") or ["[empty]"]
        panels.append({
            "board_name": board.name,
            "board_uuid": board.uuid,
            "container": entry.get("container"),
            "text": "\n".join(lines),
        })
    return panels


def fetch_lr_network(board_name=None, board_uuid=None, refresh=False):
    """Fetch LR network interfaces / IPs / routes from the lab proxy."""
    base = LR_LOG_PROXY_URL.rstrip("/")
    parts = []
    if board_name:
        parts.append("board={0}".format(urlquote(board_name)))
    if board_uuid:
        parts.append("board_uuid={0}".format(urlquote(board_uuid)))
    if refresh:
        parts.append("refresh=1")
    if not parts:
        return {
            "ok": False,
            "error": "board_name or board_uuid required",
            "interfaces": [],
            "routes": [],
            "dns": [],
        }
    url = "{0}/api/lr-network?{1}".format(base, "&".join(parts))
    try:
        resp = urllib2.urlopen(url, timeout=25)
        return json.loads(resp.read())
    except Exception as exc:
        LOG.warning("fetch_lr_network failed: %s", exc)
        return {
            "ok": False,
            "container": None,
            "error": "network proxy unreachable ({0})".format(safe_exc_text(exc)),
            "interfaces": [],
            "routes": [],
            "dns": [],
            "hostname": None,
            "host_ports": [],
        }
