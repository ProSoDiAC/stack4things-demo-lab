# -*- coding: utf-8 -*-
"""Fleet membership and parallel board operations for the lab Fleets panel."""

import json
import logging
import os

from django.utils.translation import ugettext_lazy as _

from horizon import messages

from openstack_dashboard.api import iotronic

try:
    import urllib2
    from urllib import quote as urlquote
except ImportError:
    import urllib.request as urllib2
    from urllib.parse import quote as urlquote

try:
    from iotronic_ui_lab.iot.iot_metrics import metrics_helpers
except ImportError:
    metrics_helpers = None

LOG = logging.getLogger(__name__)

LR_LOG_PROXY_URL = os.environ.get(
    "LR_LOG_PROXY_URL", "http://lr-log-proxy:8092"
)
LR_CONTAINER_BY_BOARD = {
    "board-alpha": "lightning-rod",
    "board-beta": "lightning-rod-2",
    "board-gamma": "lightning-rod-3",
    "board-delta": "lightning-rod-4",
    "board-epsilon": "lightning-rod-5",
    "board-zeta": "lightning-rod-6",
}


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


def online_board_choices(request):
    """Return [(uuid, name), ...] for online boards."""
    boards = iotronic.board_list(request, "online", None, None)
    boards.sort(key=lambda b: b.name)
    return [(b.uuid, b.name) for b in boards]


def plugin_choices(request):
    """Return [(uuid, name), ...] for injectable cloud plugins."""
    plugins = iotronic.plugin_list(request, None, None, all_plugins=True)
    plugins.sort(key=lambda p: p.name)
    return [(p.uuid, p.name) for p in plugins]


def fleet_boards(request, fleet_id):
    try:
        return iotronic.fleet_get_boards(request, fleet_id) or []
    except Exception as exc:
        LOG.warning("fleet_get_boards failed: %s", exc)
        return []


def fleet_board_ids(request, fleet_id):
    return [b.uuid for b in fleet_boards(request, fleet_id)]


def set_fleet_members(request, fleet_id, selected_board_ids):
    """Assign selected boards to fleet; remove unselected current members."""
    selected = set(selected_board_ids or [])
    current = fleet_boards(request, fleet_id)
    current_ids = set(b.uuid for b in current)

    for board_id in selected:
        if board_id not in current_ids:
            iotronic.board_update(request, board_id, {"fleet": fleet_id})

    for board in current:
        if board.uuid not in selected:
            iotronic.board_update(request, board.uuid, {"fleet": None})


def _flash_fleet_results(request, action_label, ok_names, failed):
    if ok_names:
        messages.success(
            request,
            _("%(action)s succeeded on %(n)d board(s): %(boards)s")
            % {
                "action": action_label,
                "n": len(ok_names),
                "boards": ", ".join(ok_names),
            },
        )
    for name, err in failed:
        messages.error(
            request,
            _("%(action)s failed on %(board)s: %(err)s")
            % {"action": action_label, "board": name, "err": err},
        )
    return len(failed) == 0


def inject_plugin_on_fleet(request, fleet_id, plugin_id, onboot=False):
    boards = fleet_boards(request, fleet_id)
    if not boards:
        messages.warning(request, _("Fleet has no member boards."))
        return False
    ok, failed = [], []
    for board in boards:
        try:
            iotronic.plugin_inject(request, board.uuid, plugin_id, onboot)
            ok.append(board.name)
        except Exception as exc:
            failed.append((board.name, safe_exc_text(exc)))
    return _flash_fleet_results(request, _("Inject"), ok, failed)


def _provision_metrics_for_board(board, plugin_id, plugin_name, params):
    if metrics_helpers is None:
        return params
    payload = {
        "board_uuid": board.uuid,
        "board_name": board.name,
        "plugin_uuid": plugin_id,
        "plugin_name": plugin_name or "",
        "measurement": "environmental_data",
        "field_schema": ["Temperature", "Humidity", "PM10", "PM25"],
        "fleet": getattr(board, "fleet", "") or "",
    }
    result = metrics_helpers.provision_stream(payload)
    merged = dict(params or {})
    merged.update(
        {
            "metrics_url": result.get("metrics_url"),
            "metrics_token": result.get("metrics_token"),
            "metrics_stream": result.get("metrics_stream"),
        }
    )
    return merged


def start_plugin_on_fleet(request, fleet_id, plugin_id, parameters=None, enable_metrics=False, plugin_name=""):
    boards = fleet_boards(request, fleet_id)
    if not boards:
        messages.warning(request, _("Fleet has no member boards."))
        return False
    params = parameters or {}
    ok, failed = [], []
    for board in boards:
        try:
            start_params = dict(params)
            if enable_metrics:
                start_params = _provision_metrics_for_board(
                    board, plugin_id, plugin_name, start_params
                )
            iotronic.plugin_action(
                request, board.uuid, plugin_id, "PluginStart", start_params
            )
            ok.append(board.name)
        except Exception as exc:
            failed.append((board.name, safe_exc_text(exc)))
    return _flash_fleet_results(request, _("Start"), ok, failed)


def stop_plugin_on_fleet(request, fleet_id, plugin_id, delay=None):
    boards = fleet_boards(request, fleet_id)
    if not boards:
        messages.warning(request, _("Fleet has no member boards."))
        return False
    params = {"delay": delay} if delay else {}
    ok, failed = [], []
    for board in boards:
        try:
            iotronic.plugin_action(
                request, board.uuid, plugin_id, "PluginStop", params
            )
            ok.append(board.name)
        except Exception as exc:
            failed.append((board.name, safe_exc_text(exc)))
    return _flash_fleet_results(request, _("Stop"), ok, failed)


def call_plugin_on_fleet(request, fleet_id, plugin_id, parameters=None):
    boards = fleet_boards(request, fleet_id)
    if not boards:
        messages.warning(request, _("Fleet has no member boards."))
        return False
    params = parameters or {}
    ok, failed = [], []
    for board in boards:
        try:
            iotronic.plugin_action(
                request, board.uuid, plugin_id, "PluginCall", params
            )
            ok.append(board.name)
        except Exception as exc:
            failed.append((board.name, safe_exc_text(exc)))
    return _flash_fleet_results(request, _("Call"), ok, failed)


def remove_plugin_on_fleet(request, fleet_id, plugin_id):
    boards = fleet_boards(request, fleet_id)
    if not boards:
        messages.warning(request, _("Fleet has no member boards."))
        return False
    ok, failed = [], []
    for board in boards:
        try:
            iotronic.plugin_remove(request, board.uuid, plugin_id)
            ok.append(board.name)
        except Exception as exc:
            failed.append((board.name, safe_exc_text(exc)))
    return _flash_fleet_results(request, _("Remove"), ok, failed)


def parse_json_field(raw, default=None):
    if default is None:
        default = {}
    if not raw:
        return default
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


def lr_container_for_board(board_name):
    return LR_CONTAINER_BY_BOARD.get(board_name or "")


def fetch_fleet_lr_logs(board_names, tail=40, grep=None):
    """Tail Lightning-Rod docker logs via lab lr-log-proxy (host :8092)."""
    names = [n for n in (board_names or []) if n]
    if not names:
        return {}
    base = LR_LOG_PROXY_URL.rstrip("/")
    qs = "boards={0}&tail={1}".format(urlquote(",".join(names)), int(tail))
    if grep:
        qs += "&grep={0}".format(urlquote(grep))
    url = "{0}/api/lr-logs?{1}".format(base, qs)
    try:
        resp = urllib2.urlopen(url, timeout=20)
        payload = json.loads(resp.read())
        return payload.get("boards", {})
    except Exception as exc:
        LOG.warning("fetch_fleet_lr_logs failed: %s", exc)
        err = safe_exc_text(exc)
        return {
            name: {
                "container": lr_container_for_board(name),
                "lines": [
                    "[error] log proxy unreachable ({0}). "
                    "Start lr-log-proxy service.".format(err)
                ],
            }
            for name in names
        }


def fleet_lr_log_panels(request, fleet_id, tail=40, grep=None):
    """Build per-board log panels for fleet member boards."""
    from iotronic_ui_lab.iot.lr_logs import helpers as lr_logs

    boards = fleet_boards(request, fleet_id)
    return lr_logs.fleet_log_panels(boards, tail=tail, grep=grep)
