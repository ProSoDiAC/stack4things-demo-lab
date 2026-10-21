# -*- coding: utf-8 -*-
"""Call FL control API on VM host from Horizon (Python 2.7)."""

import json
import logging
import os

from django.utils.translation import ugettext_lazy as _
from horizon import messages

try:
    import urllib2
except ImportError:
    import urllib.request as urllib2

LOG = logging.getLogger(__name__)

FL_CONTROL_URL = os.environ.get(
    "FL_CONTROL_URL", "http://fl-control:8091"
)


def _safe_exc(exc):
    try:
        if isinstance(exc, unicode):
            return exc.encode("ascii", "replace")
        if isinstance(exc, str):
            return exc.decode("utf-8", "replace").encode("ascii", "replace")
        return unicode(exc).encode("ascii", "replace")
    except Exception:
        return repr(exc)


def _control_url(path):
    return "{0}{1}".format(FL_CONTROL_URL.rstrip("/"), path)


def _http_request(method, path, body=None, timeout=30):
    url = _control_url(path)
    data = None
    headers = {"Content-Type": "application/json"}
    if body is not None:
        data = json.dumps(body)
    req = urllib2.Request(url, data=data, headers=headers)
    req.get_method = lambda: method
    return urllib2.urlopen(req, timeout=timeout)


def _cfg_payload(global_cfg):
    return {
        "fl_rounds": global_cfg.get("fl_rounds", "2"),
        "fl_scenario": global_cfg.get("fl_scenario", "heart"),
        "fl_port": global_cfg.get("server_port", "8087"),
        "fl_host": "0.0.0.0",
        "fl_dashboard_port": global_cfg.get("dashboard_port", "8090"),
        "fl_dashboard_host": "0.0.0.0",
    }


def server_status(global_cfg=None):
    try:
        query = ""
        if global_cfg:
            payload = _cfg_payload(global_cfg)
            query = "?fl_port={0}&fl_dashboard_port={1}".format(
                payload["fl_port"], payload["fl_dashboard_port"]
            )
        resp = _http_request("GET", "/api/fl/status{0}".format(query), timeout=5)
        raw = resp.read()
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        result = json.loads(raw)
        result["control_reachable"] = True
        return result
    except Exception as exc:
        LOG.debug("FL control status failed", exc_info=True)
        return {
            "running": False,
            "dashboard_running": False,
            "control_reachable": False,
            "error": str(exc),
        }


def start_server(request, global_cfg, quiet=False):
    body = _cfg_payload(global_cfg)
    try:
        resp = _http_request("POST", "/api/fl/start", body=body, timeout=120)
        raw = resp.read()
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        result = json.loads(raw)
        if not quiet:
            if result.get("running"):
                rounds = body.get("fl_rounds", "2")
                messages.success(
                    request,
                    _("Flower server started on :{0} - {1} round(s), dashboard :{2}.").format(
                        result.get("fl_port", body["fl_port"]),
                        rounds,
                        result.get("fl_dashboard_port", body["fl_dashboard_port"]),
                    ),
                )
            else:
                messages.warning(request, _("Server start requested but not yet listening."))
        return result
    except Exception as exc:
        LOG.exception("FL server start failed")
        raise RuntimeError(
            _("Cannot start Flower server: {0}. Is fl-control running?").format(
                _safe_exc(exc)
            )
        )


def restart_server(request, global_cfg, quiet=False):
    body = _cfg_payload(global_cfg)
    try:
        _http_request("POST", "/api/fl/stop", body=body, timeout=30)
        resp = _http_request("POST", "/api/fl/start", body=body, timeout=120)
        raw = resp.read()
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        result = json.loads(raw)
        if not quiet:
            if result.get("running"):
                rounds = body.get("fl_rounds", "2")
                messages.success(
                    request,
                    _("Flower server restarted - {0} round(s), dashboard :{1}.").format(
                        rounds,
                        result.get("fl_dashboard_port", body["fl_dashboard_port"]),
                    ),
                )
            else:
                messages.warning(request, _("Restart requested but server not listening."))
        return result
    except Exception as exc:
        LOG.exception("FL server restart failed")
        raise RuntimeError(
            _("Cannot restart Flower server: {0}. Is fl-control running?").format(
                _safe_exc(exc)
            )
        )


def stop_server(request, global_cfg=None):
    body = _cfg_payload(global_cfg) if global_cfg else {}
    try:
        resp = _http_request("POST", "/api/fl/stop", body=body, timeout=30)
        raw = resp.read()
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        result = json.loads(raw)
        messages.success(request, _("Flower server stopped."))
        return result
    except Exception as exc:
        LOG.exception("FL server stop failed")
        raise RuntimeError(_("Cannot stop Flower server: {0}").format(_safe_exc(exc)))
