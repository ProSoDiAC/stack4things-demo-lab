# -*- coding: utf-8 -*-
"""IoTronic helpers for FL client plugin deploy from Horizon panel."""

import cPickle
import json
import logging
import os
import time

from horizon import exceptions
from horizon import messages
from django.utils.translation import ugettext_lazy as _

from openstack_dashboard.api import iotronic
from openstack_dashboard.api.iotronic import iotronicclient

from iotronic_ui_lab.iot.federated_learning.fl_constants import (
    DEFAULT_SCENARIO,
    FL_LAB_PLUGIN_NAMES,
    FL_LEGACY_PLUGIN_NAMES,
    FL_PLUGIN_HEART,
    FL_PLUGIN_PATH,
    FL_PLUGIN_PM,
    FL_SCENARIOS,
    FL_SHARED_PLUGIN_NAME,
    GLOBAL_PARAM_KEYS,
    LAB_BOARD_NAMES,
    LAB_CONFIG_PATH,
    csv_path_for_board,
    default_global_config,
    default_params,
    default_params_json,
    lab_plugins_ready,
    merge_params,
    params_for_plugin_board,
    params_json_for_board,
    read_global_config,
    save_global_config,
    scenario_from_csv,
    scenario_from_plugin_name,
    scenario_label,
    spec_from_board,
    stub_params_json,
)

LOG = logging.getLogger(__name__)


def read_plugin_code(session):
    cached = session.get("fl_plugin_code")
    if cached:
        return _ascii_safe(cached)
    try:
        with open(FL_PLUGIN_PATH, "r") as fh:
            return _ascii_safe(fh.read())
    except (IOError, OSError):
        return ""


def _ascii_safe(text):
    """IoTronic inject/update path expects ASCII-safe plugin source (Python 2)."""
    if not text:
        return text
    if isinstance(text, unicode):
        return text.encode("ascii", "replace")
    if isinstance(text, str):
        try:
            return text.decode("utf-8").encode("ascii", "replace")
        except (UnicodeDecodeError, AttributeError):
            pass
        try:
            text.decode("ascii")
            return text
        except UnicodeDecodeError:
            return text.decode("utf-8", "replace").encode("ascii", "replace")
    return str(text).encode("ascii", "replace")


def safe_exception_text(exc):
    """ASCII-safe exception text for Horizon flash messages (Python 2)."""
    try:
        if exc is None:
            return ""
        if isinstance(exc, unicode):
            return exc.encode("ascii", "replace")
        if isinstance(exc, str):
            return exc.decode("utf-8", "replace").encode("ascii", "replace")
        return unicode(exc).encode("ascii", "replace")
    except Exception:
        try:
            return repr(exc).encode("ascii", "replace")
        except Exception:
            return "unknown error"


def read_lab_plugin_codes(request, session=None, global_cfg=None):
    """Fetch registered cloud plugin source per lab plugin name (read-only display)."""
    session = session or {}
    global_cfg = global_cfg or read_global_config(session)
    fallback = read_plugin_code(session)
    codes = {}
    plugins = _plugins_by_name(request)
    for name in FL_LAB_PLUGIN_NAMES:
        plugin_id = plugins.get(name)
        source = fallback
        if plugin_id:
            try:
                plugin = iotronic.plugin_get(request, plugin_id, ["code"])
                raw = _info_value(plugin, "code")
                if raw:
                    source = _ascii_safe(cPickle.loads(str(raw)))
            except Exception as exc:
                LOG.warning("read_lab_plugin_codes %s: %s", name, exc)
        codes[name] = format_plugin_display_code(name, source, global_cfg)
    return codes


def format_plugin_display_code(plugin_name, source_code, global_cfg=None):
    """Distinct read-only header per cloud plugin + shared LR source body."""
    scenario = scenario_from_plugin_name(plugin_name) or DEFAULT_SCENARIO
    meta = FL_SCENARIOS.get(scenario, FL_SCENARIOS[DEFAULT_SCENARIO])
    cfg = global_cfg or default_global_config()
    header = [
        "# IoTronic cloud plugin: {0}".format(plugin_name),
        "# Scenario: {0}".format(meta.get("label", scenario)),
        "#",
        "# Edge datasets (one CSV per board):",
    ]
    for board_name in sorted(LAB_BOARD_NAMES):
        header.append(
            "#   {0}: {1}".format(
                board_name, csv_path_for_board(board_name, scenario)
            )
        )
    example = default_params(
        {
            "board_name_param": "board-alpha",
            "fl_scenario": scenario,
            "csv_file": csv_path_for_board("board-alpha", scenario),
        },
        cfg,
    )
    header.append("#")
    header.append("# Example PluginStart JSON (board-alpha):")
    for line in json.dumps(example, indent=2, sort_keys=True).splitlines():
        header.append("# {0}".format(line))
    header.extend(
        [
            "#",
            "# --- registered plugin source (read-only; edit in IoT -> Plugins) ---",
            "",
        ]
    )
    body = source_code or ""
    if body.startswith("# IoTronic cloud plugin:"):
        return body
    return "\n".join(header) + body


def save_plugin_code(session, code):
    session["fl_plugin_code"] = _ascii_safe(code)
    session.modified = True


def _info_value(obj, key, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    info = getattr(obj, "_info", None)
    if isinstance(info, dict) and key in info:
        return info.get(key, default)
    return getattr(obj, key, default)


def _boards_by_name(request):
    result = {}
    try:
        boards = iotronic.board_list(request)
        for board in boards:
            name = _info_value(board, "name")
            uuid = _info_value(board, "uuid")
            status = _info_value(board, "status", "")
            if name and uuid:
                result[name] = {"uuid": uuid, "status": status or ""}
    except Exception:
        exceptions.handle(request, _("Unable to retrieve boards list."))
    return result


def _plugins_by_name(request):
    result = {}
    try:
        plugins = iotronic.plugin_list(request, None, None, all_plugins=True)
        for plugin in plugins:
            name = _info_value(plugin, "name")
            uuid = _info_value(plugin, "uuid")
            if name and uuid:
                result[name] = uuid
    except Exception:
        exceptions.handle(request, _("Unable to retrieve plugins list."))
    return result


def _plugins_list(request):
    """Cloud plugin dropdown: only FL lab plugins (heart + PM)."""
    items = []
    try:
        plugins = iotronic.plugin_list(request, None, None, all_plugins=True)
        for plugin in plugins:
            name = _info_value(plugin, "name")
            uuid = _info_value(plugin, "uuid")
            if name and uuid and name in FL_LAB_PLUGIN_NAMES:
                items.append({"uuid": uuid, "name": name})
        items.sort(
            key=lambda x: FL_LAB_PLUGIN_NAMES.index(x["name"])
        )
    except Exception:
        pass
    return items


def remove_legacy_plugins(request):
    """Drop pre-dual-scenario fl-client plugin from cloud catalog."""
    plugins = _plugins_by_name(request)
    removed = []
    for name in FL_LEGACY_PLUGIN_NAMES:
        plugin_id = plugins.get(name)
        if not plugin_id:
            continue
        for board in _boards_list(request):
            board_id = board.get("uuid", "")
            if not board_id:
                continue
            if _plugin_on_board(request, board_id, plugin_id):
                try:
                    iotronic.plugin_remove(request, board_id, plugin_id)
                except Exception as exc:
                    LOG.warning(
                        "Could not uninject legacy plugin %s from %s: %s",
                        name,
                        board.get("name", board_id),
                        exc,
                    )
        try:
            iotronic.plugin_delete(request, plugin_id)
            removed.append(name)
        except Exception as exc:
            LOG.warning("Could not delete legacy plugin %s: %s", name, exc)
    return removed


def _boards_list(request):
    items = []
    try:
        boards = iotronic.board_list(request)
        for board in boards:
            name = _info_value(board, "name")
            uuid = _info_value(board, "uuid")
            status = _info_value(board, "status", "")
            if name and uuid:
                items.append({"uuid": uuid, "name": name, "status": status or ""})
        items.sort(key=lambda x: x["name"])
    except Exception:
        pass
    return items


def _plugin_on_board(request, board_id, plugin_id):
    try:
        on_board = iotronic.plugins_on_board(request, board_id)
        for entry in on_board:
            if isinstance(entry, dict):
                pid = entry.get("plugin") or entry.get("id")
            else:
                pid = _info_value(entry, "plugin") or getattr(entry, "plugin", None)
            if pid and str(pid) == str(plugin_id):
                return True
    except Exception:
        LOG.debug("plugins_on_board failed", exc_info=True)
    return False


def _workflow_step(plugins_exist, all_injected, any_started):
    if not plugins_exist:
        return 1
    if not all_injected:
        return 2
    return 3


def get_client_specs(request, session=None):
    """One FL client row per lab board (alpha, beta, gamma)."""
    session = session or request.session
    global_cfg = read_global_config(session)
    boards = _boards_list(request)
    return [
        spec_from_board(board, idx, global_cfg)
        for idx, board in enumerate(boards)
        if board.get("name") in LAB_BOARD_NAMES
    ]


def read_selected_lab_plugin(session, plugins=None):
    """Active lab example = cloud plugin name (heart or PM)."""
    plugins = plugins or {}
    selected = session.get("fl_selected_lab_plugin")
    if selected in FL_LAB_PLUGIN_NAMES and plugins.get(selected):
        return selected
    return FL_PLUGIN_HEART if plugins.get(FL_PLUGIN_HEART) else FL_LAB_PLUGIN_NAMES[0]


def save_selected_lab_plugin(session, plugin_name):
    if plugin_name in FL_LAB_PLUGIN_NAMES:
        session["fl_selected_lab_plugin"] = plugin_name
        session.modified = True


def apply_lab_plugin_to_all(session, plugin_name, specs, plugins, global_cfg=None):
    """Set cloud plugin + JSON params for every lab board in session."""
    if plugin_name not in FL_LAB_PLUGIN_NAMES:
        return
    global_cfg = global_cfg or read_global_config(session)
    save_selected_lab_plugin(session, plugin_name)
    plugin_id = plugins.get(plugin_name, "")
    for spec in specs:
        board_name = spec.get("board_name")
        if board_name not in LAB_BOARD_NAMES:
            continue
        slug = spec["slug"]
        built = params_for_plugin_board(plugin_name, board_name, global_cfg)
        if built:
            session["fl_params_{0}".format(slug)] = built
        prev = session.get("fl_assign_{0}".format(slug)) or {}
        session["fl_assign_{0}".format(slug)] = {
            "board_id": spec.get("board_id") or prev.get("board_id", ""),
            "plugin_id": plugin_id or prev.get("plugin_id", ""),
            "board_name": board_name,
            "plugin_name": plugin_name,
        }
    session.modified = True


def _scenario_for_row(session, slug, spec, params_json, plugin_name=None):
    if plugin_name:
        detected = scenario_from_plugin_name(plugin_name)
        if detected:
            return detected
    if params_json:
        try:
            data = json.loads(params_json)
            if isinstance(data, dict):
                if data.get("fl_scenario") in FL_SCENARIOS:
                    return data["fl_scenario"]
                detected = scenario_from_csv(data.get("csv_file", ""))
                if detected:
                    return detected
        except (ValueError, TypeError):
            pass
    assign = session.get("fl_assign_{0}".format(slug)) or {}
    detected = scenario_from_plugin_name(assign.get("plugin_name", ""))
    if detected:
        return detected
    return spec.get("fl_scenario") or DEFAULT_SCENARIO


def collect_active_scenarios(request, session, form_data=None):
    """Return set of scenario ids implied by selected cloud plugins."""
    scenarios = set()
    plugins = _plugins_by_name(request)
    for spec in get_client_specs(request, session):
        if not spec.get("csv_file"):
            continue
        slug = spec["slug"]
        plugin_name = ""
        params_json = ""
        if form_data is not None:
            plugin_name = form_data.get("plugin_name_{0}".format(slug), "")
            if not plugin_name:
                pid = form_data.get("plugin_id_{0}".format(slug), "")
                for name, uuid in plugins.items():
                    if uuid == pid:
                        plugin_name = name
                        break
            params_json = form_data.get("parameters_{0}".format(slug), "")
        else:
            assign = session.get("fl_assign_{0}".format(slug)) or {}
            plugin_name = assign.get("plugin_name", "")
            params_json = session.get("fl_params_{0}".format(slug), "")
        scenarios.add(
            _scenario_for_row(session, slug, spec, params_json, plugin_name)
        )
    scenarios.discard(None)
    return scenarios


def validate_lab_scenarios(request, session, form_data=None):
    """Single active scenario - driven by top-level plugin pick when present."""
    if form_data is not None:
        lab_plugin = form_data.get("fl_lab_plugin", "").strip()
        detected = scenario_from_plugin_name(lab_plugin)
        if detected:
            return detected
    scenarios = collect_active_scenarios(request, session, form_data)
    if len(scenarios) > 1:
        labels = ", ".join(sorted(scenario_label(s) for s in scenarios))
        raise exceptions.WorkflowValidationError(
            _("Mixed FL plugins in one run are not supported ({0}). "
              "Use the same cloud plugin on all boards (heart or PM).").format(labels)
        )
    return scenarios.pop() if scenarios else DEFAULT_SCENARIO


def read_dashboard_scenario():
    """Scenario from live dashboard state file (None if unavailable)."""
    path = os.environ.get("FL_DASHBOARD_STATE", "/tmp/fl_dashboard_state.json")
    try:
        with open(path, "r") as fh:
            data = json.loads(fh.read())
            scenario = data.get("fl_scenario")
            if scenario in FL_SCENARIOS:
                return scenario
    except (IOError, OSError, ValueError, TypeError):
        pass
    return None


def run_lab_scenario(request, session, form_data, server_running):
    """Apply selected cloud plugin, start/restart Flower server, start edge clients."""
    from iotronic_ui_lab.iot.federated_learning import fl_server_ctl

    cfg = ensure_lab_config_from_post(session, form_data)
    if form_data.get("apply_to_clients") == "1":
        specs = get_client_specs(request)
        apply_global_to_all_params(session, cfg, specs)
    specs = get_client_specs(request)
    save_assignments(session, form_data, specs)
    ensure_lab_plugin_assignments(request, session, specs, form_data, cfg)
    active = validate_lab_scenarios(request, session, form_data)
    cfg["fl_scenario"] = active
    save_global_lab_config(session, cfg)

    stop_all_clients(request, session, quiet=True)
    time.sleep(2.0)

    if server_running:
        fl_server_ctl.restart_server(request, cfg, quiet=True)
    else:
        fl_server_ctl.start_server(request, cfg, quiet=True)
    expected = len([s for s in specs if s.get("board_name") in LAB_BOARD_NAMES])
    started = restart_all_clients(request, session, cfg, quiet=True)

    label = scenario_label(active)
    plugin = form_data.get("fl_lab_plugin", "").strip()
    if started == 0:
        raise RuntimeError(
            "No edge clients started - inject plugins and check boards online."
        )
    if started < expected:
        messages.warning(
            request,
            _(
                "Server ready ({0}, {1}) but only {2}/{3} edge client(s) started - "
                "inject plugins and check boards online."
            ).format(label, plugin or active, started, expected),
        )
        return cfg
    if server_running:
        messages.success(
            request,
            _("Server restarted with {0} ({1}) - edge clients running.").format(
                label, plugin or active
            ),
        )
    else:
        messages.success(
            request,
            _("Server started: {0} ({1}) - edge clients running.").format(
                label, plugin or active
            ),
        )
    return cfg


def _status_class(board_status):
    if board_status == "online":
        return "success"
    if board_status == "offline":
        return "warning"
    return "danger"


def build_client_rows(request, session):
    boards = _boards_by_name(request)
    all_boards = _boards_list(request)
    plugins = _plugins_by_name(request)
    all_plugins = _plugins_list(request)
    global_cfg = read_global_config(session)
    specs = get_client_specs(request)
    rows = []
    injected_count = 0
    plugins_exist = lab_plugins_ready(plugins)

    for spec in specs:
        slug = spec["slug"]
        board_id = spec["board_id"]
        board_name = spec["board_name"]

        assign = _read_assignment(session, slug, spec, boards, plugins)
        plugin_id = assign["plugin_id"]
        plugin_name = assign["plugin_name"]

        board_info = boards.get(board_name, {})
        board_status = board_info.get("status", "unknown") or "unknown"

        injected = False
        if board_id and plugin_id:
            injected = _plugin_on_board(request, board_id, plugin_id)
        if injected:
            injected_count += 1

        params_key = "fl_params_{0}".format(slug)
        params_json = params_json_for_board(
            session, slug, spec, global_cfg, board_status
        )
        params_ready = board_status == "online" and bool(spec.get("csv_file"))
        fl_scenario = _scenario_for_row(
            session, slug, spec, params_json, plugin_name
        )

        rows.append({
            "slug": slug,
            "board_name": board_name,
            "plugin_name": plugin_name,
            "board_id": board_id,
            "board_status": board_status,
            "status_class": _status_class(board_status),
            "plugin_id": plugin_id,
            "plugin_exists": bool(plugin_id),
            "injected": injected,
            "params_json": params_json,
            "params_key": params_key,
            "params_ready": params_ready,
            "default_csv": spec["csv_file"],
            "fl_scenario": fl_scenario,
            "fl_scenario_label": scenario_label(fl_scenario),
            "spec": spec,
        })

    total = len(specs)
    all_injected = bool(total) and plugins_exist and injected_count == total
    workflow_step = _workflow_step(plugins_exist, all_injected, False)

    return rows, {
        "global_config": global_cfg,
        "fl_scenarios": FL_SCENARIOS,
        "selected_lab_plugin": read_selected_lab_plugin(session, plugins),
        "fl_lab_plugin_ids": {
            name: plugins.get(name, "") for name in FL_LAB_PLUGIN_NAMES
        },
        "fl_lab_plugin_codes": read_lab_plugin_codes(request, session, global_cfg),
        "workflow_step": workflow_step,
        "plugins_exist": plugins_exist,
        "injected_count": injected_count,
        "all_injected": all_injected,
        "total_clients": total,
        "all_plugins": all_plugins,
        "all_boards": all_boards,
    }


def _read_assignment(session, slug, spec, boards, plugins):
    key = "fl_assign_{0}".format(slug)
    stored = session.get(key) or {}
    board_id = stored.get("board_id") or spec.get("board_id") or ""
    plugin_name = stored.get("plugin_name") or read_selected_lab_plugin(session, plugins)
    plugin_id = (
        stored.get("plugin_id")
        or plugins.get(plugin_name, "")
        or plugins.get(FL_PLUGIN_HEART, "")
        or plugins.get(FL_SHARED_PLUGIN_NAME, "")
    )
    board_name = stored.get("board_name") or spec.get("board_name", "")
    legacy_id = plugins.get("fl-client", "")
    if plugin_id and legacy_id and plugin_id == legacy_id and plugins.get(FL_PLUGIN_HEART):
        plugin_name = FL_PLUGIN_HEART
        plugin_id = plugins.get(FL_PLUGIN_HEART, plugin_id)
    elif plugin_name in ("fl-client", FL_SHARED_PLUGIN_NAME) and plugins.get(FL_PLUGIN_HEART):
        plugin_name = FL_PLUGIN_HEART
        plugin_id = plugins.get(FL_PLUGIN_HEART, plugin_id)
    if board_id and not board_name:
        for name, info in boards.items():
            if info.get("uuid") == board_id:
                board_name = name
                break
    if plugin_id and not plugin_name:
        for name, pid in plugins.items():
            if pid == plugin_id:
                plugin_name = name
                break
    return {
        "board_id": board_id,
        "plugin_id": plugin_id,
        "board_name": board_name,
        "plugin_name": plugin_name,
    }


def ensure_lab_plugin_assignments(request, session, specs, form_data=None, global_cfg=None):
    """Apply selected lab plugin (heart or PM) to all board rows in session."""
    global_cfg = global_cfg or read_global_config(session)
    plugins = _plugins_by_name(request)
    lab_plugin = ""
    if form_data:
        lab_plugin = form_data.get("fl_lab_plugin", "").strip()
    if lab_plugin not in FL_LAB_PLUGIN_NAMES:
        lab_plugin = read_selected_lab_plugin(session, plugins)
    apply_lab_plugin_to_all(session, lab_plugin, specs, plugins, global_cfg)
    return lab_plugin


def _stop_all_lab_plugins_on_board(request, board_id, plugins):
    """Stop every FL lab plugin injected on a board (heart + PM)."""
    stopped = False
    for name in FL_LAB_PLUGIN_NAMES:
        plugin_id = plugins.get(name, "")
        if not plugin_id:
            continue
        if not _plugin_on_board(request, board_id, plugin_id):
            continue
        if _safe_plugin_stop(request, board_id, plugin_id):
            stopped = True
    return stopped


def save_assignments(session, form_data, specs):
    global_cfg = read_global_config(session)
    lab_plugin = form_data.get("fl_lab_plugin", "").strip()
    if lab_plugin in FL_LAB_PLUGIN_NAMES:
        save_selected_lab_plugin(session, lab_plugin)
    for spec in specs:
        slug = spec["slug"]
        prev = session.get("fl_assign_{0}".format(slug)) or {}
        board_id = form_data.get("board_id_{0}".format(slug)) or prev.get("board_id") or spec.get("board_id", "")
        plugin_id = form_data.get("plugin_id_{0}".format(slug)) or prev.get("plugin_id") or ""
        board_name = form_data.get("board_name_{0}".format(slug)) or prev.get("board_name") or spec.get("board_name", "")
        plugin_name = form_data.get("plugin_name_{0}".format(slug)) or prev.get("plugin_name") or ""
        params_json = form_data.get("parameters_{0}".format(slug)) or session.get("fl_params_{0}".format(slug), "")
        if plugin_name and spec.get("board_name"):
            built = params_for_plugin_board(
                plugin_name, spec["board_name"], global_cfg
            )
            if built:
                params_json = built
        session["fl_assign_{0}".format(slug)] = {
            "board_id": board_id,
            "plugin_id": plugin_id,
            "board_name": board_name,
            "plugin_name": plugin_name,
        }
        if params_json:
            session["fl_params_{0}".format(slug)] = params_json
    session.modified = True


def _assignments_from_session(session, specs):
    result = []
    for spec in specs:
        assign = session.get("fl_assign_{0}".format(spec["slug"])) or {}
        board_id = assign.get("board_id") or spec.get("board_id", "")
        plugin_id = assign.get("plugin_id", "")
        if not board_id or not plugin_id:
            continue
        params_json = session.get("fl_params_{0}".format(spec["slug"]), "")
        result.append({
            "slug": spec["slug"],
            "spec": spec,
            "board_id": board_id,
            "plugin_id": plugin_id,
            "params_json": params_json,
            "inject": assign.get("inject", True),
        })
    return result


def _safe_plugin_stop(request, board_id, plugin_id):
    """Best-effort stop; ignore stale 'not running' errors from IoTronic."""
    try:
        iotronic.plugin_action(request, board_id, plugin_id, "PluginStop", {})
        return True
    except Exception as exc:
        msg = unicode(exc).lower()
        if "not running" in msg or "instantiated but" in msg:
            return False
        LOG.debug("plugin stop ignored for %s: %s", board_id, exc)
        return False


def wait_for_flower_server(global_cfg, timeout=45):
    """Block until Flower gRPC port accepts connections (VM-side)."""
    host = global_cfg.get("server_host", "127.0.0.1")
    port = int(global_cfg.get("server_port", "8087"))
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            import socket
            sock = socket.create_connection((host, port), timeout=2)
            sock.close()
            time.sleep(1.5)
            return True
        except (socket.error, OSError):
            time.sleep(0.5)
    return False


def _inject_plugins_for_spec(request, session, spec, plugin_ids, issues):
    """Inject one or more plugins on a board; return (new_count, already_count)."""
    slug = spec["slug"]
    assign = session.get("fl_assign_{0}".format(slug)) or {}
    board_id = assign.get("board_id") or spec.get("board_id", "")
    if not board_id:
        issues.append(_("Board {0} not found.").format(spec.get("board_name", slug)))
        return 0, 0
    injected = 0
    already = 0
    board_label = spec.get("board_name", slug)
    for plugin_id in plugin_ids:
        if not plugin_id:
            continue
        if _plugin_on_board(request, board_id, plugin_id):
            already += 1
            continue
        try:
            _inject_plugin_on_board(request, board_id, plugin_id, board_label)
            injected += 1
        except Exception as exc:
            LOG.exception("inject_selected %s", slug)
            issues.append("{0}: {1}".format(board_label, safe_exception_text(exc)))
    return injected, already


def inject_selected(request, session):
    injected = 0
    already = 0
    issues = []
    specs = get_client_specs(request)
    plugins = _plugins_by_name(request)
    checked = [
        spec for spec in specs
        if request.POST.get("inject_{0}".format(spec["slug"])) == "1"
    ]
    # No checkboxes when plugins already show OK or lab plugin changed client-side.
    inject_all_boards = not checked

    if inject_all_boards:
        targets = [
            spec for spec in specs
            if spec.get("board_name") in LAB_BOARD_NAMES
        ]
        plugin_ids = [plugins.get(name, "") for name in FL_LAB_PLUGIN_NAMES]
    else:
        targets = checked
        plugin_ids = None

    for spec in targets:
        if plugin_ids is not None:
            row_injected, row_already = _inject_plugins_for_spec(
                request, session, spec, plugin_ids, issues
            )
        else:
            slug = spec["slug"]
            assign = session.get("fl_assign_{0}".format(slug)) or {}
            plugin_id = (
                assign.get("plugin_id")
                or request.POST.get("plugin_id_{0}".format(slug), "")
            )
            if not plugin_id:
                issues.append(
                    _("Row {0}: pick a plugin.").format(spec.get("board_name", slug))
                )
                continue
            row_injected, row_already = _inject_plugins_for_spec(
                request, session, spec, [plugin_id], issues
            )
        injected += row_injected
        already += row_already

    if injected and not issues:
        messages.success(request, _("Injected on {0} board(s).").format(injected))
    elif injected:
        messages.warning(
            request,
            _("Injected {0} board(s). {1}").format(injected, "; ".join(issues)),
        )
    elif already and not issues:
        messages.success(
            request,
            _("FL plugins already injected on {0} edge board(s).").format(
                len({spec.get("board_name") for spec in targets if spec.get("board_name")})
            ),
        )
    else:
        messages.error(
            request,
            _("Injection failed. {0}").format("; ".join(issues) or _("Unknown error.")),
        )


def start_all_clients(request, session, quiet_stop=False, quiet=False):
    global_cfg = read_global_config(session)
    plugins = _plugins_by_name(request)
    for spec in get_client_specs(request):
        board_id = spec.get("board_id", "")
        if board_id:
            _stop_all_lab_plugins_on_board(request, board_id, plugins)
    time.sleep(1.0)

    started = 0
    issues = []
    online_specs = []
    for spec in get_client_specs(request):
        slug = spec["slug"]
        if not spec.get("csv_file"):
            continue
        assign = session.get("fl_assign_{0}".format(slug)) or {}
        board_id = assign.get("board_id") or spec.get("board_id", "")
        plugin_id = assign.get("plugin_id", "")
        if not board_id or not plugin_id:
            continue
        if not _plugin_on_board(request, board_id, plugin_id):
            try:
                _inject_plugin_on_board(
                    request, board_id, plugin_id, spec.get("board_name", slug)
                )
            except Exception as exc:
                LOG.exception("auto-inject %s", slug)
                issues.append(
                    _("{0}: plugin not injected ({1}).").format(
                        spec.get("board_name", slug), safe_exception_text(exc)
                    )
                )
                continue
        online_specs.append((spec, slug, board_id, plugin_id))

    # Alpha last: it often starts before Flower gRPC is fully ready on server restart.
    _start_order = {"board-beta": 0, "board-gamma": 1, "board-alpha": 2}
    online_specs.sort(
        key=lambda row: _start_order.get(row[0].get("board_name", ""), 99)
    )

    for idx, (spec, slug, board_id, plugin_id) in enumerate(online_specs):
        time.sleep(2.0 if idx == 0 else 0.8)
        params_json = session.get("fl_params_{0}".format(slug), "")
        try:
            params = merge_params(spec, global_cfg, params_json)
            iotronic.plugin_action(request, board_id, plugin_id, "PluginStart", params)
            started += 1
        except Exception as exc:
            LOG.exception("start_all %s", slug)
            issues.append("{0}: {1}".format(
                spec.get("board_name", slug), safe_exception_text(exc)
            ))

    if quiet:
        return started
    if started and not issues:
        messages.success(request, _("Start: {0} FL client(s) running.").format(started))
    elif started:
        messages.warning(
            request,
            _("Started {0} client(s). {1}").format(started, "; ".join(issues)),
        )
    elif not quiet_stop:
        messages.error(
            request,
            _("No client started. Inject plugins first. {0}").format(
                "; ".join(issues) or ""
            ),
        )
    return started


def restart_all_clients(request, session, global_cfg=None, quiet=False):
    """Stop then start all edge clients after Flower server (re)start."""
    global_cfg = global_cfg or read_global_config(session)
    if not wait_for_flower_server(global_cfg):
        if not quiet:
            messages.warning(
                request,
                _("Flower port :{0} not ready - clients will retry automatically.").format(
                    global_cfg.get("server_port", "8087")
                ),
            )
    return start_all_clients(request, session, quiet_stop=True, quiet=quiet)


def stop_all_clients(request, session, quiet=False):
    stopped = 0
    plugins = _plugins_by_name(request)
    for spec in get_client_specs(request):
        board_id = spec.get("board_id", "")
        if not board_id:
            continue
        if _stop_all_lab_plugins_on_board(request, board_id, plugins):
            stopped += 1
    if quiet:
        return stopped
    if stopped:
        messages.success(request, _("Stop: {0} client(s) interrupted.").format(stopped))
    else:
        messages.warning(request, _("No running client to stop."))
    return stopped


def ensure_plugin(request, name, code):
    """Create or update a cloud-side plugin; return its UUID."""
    code = _ascii_safe(code)
    plugins = _plugins_by_name(request)
    if name in plugins:
        iotronic.plugin_update(
            request,
            plugins[name],
            {
                "name": name,
                "public": True,
                "callable": False,
                "code": cPickle.dumps(str(code)),
            },
        )
        return plugins[name]

    client = iotronicclient(request)
    plugin = client.plugin.create(
        name=name,
        public=True,
        callable=False,
        code=code,
        parameters={},
    )
    plugin_id = _info_value(plugin, "uuid")
    if not plugin_id:
        raise RuntimeError(_("Plugin {0} created but UUID missing.").format(name))
    return plugin_id


def create_plugins(request, code):
    try:
        global_cfg = read_global_config(request.session)
        for pname in FL_LAB_PLUGIN_NAMES:
            ensure_plugin(request, pname, code)
        removed = remove_legacy_plugins(request)
        plugins = _plugins_by_name(request)
        specs = get_client_specs(request)
        selected = read_selected_lab_plugin(request.session, plugins)
        apply_lab_plugin_to_all(request.session, selected, specs, plugins, global_cfg)
        msg = _("FL client plugins ready: {0}.").format(
            ", ".join(FL_LAB_PLUGIN_NAMES)
        )
        if removed:
            msg = msg + " " + _("Removed legacy plugin(s): {0}.").format(
                ", ".join(removed)
            )
        messages.success(request, msg)
    except Exception as exc:
        LOG.exception("create_plugins failed")
        messages.error(
            request,
            _("Plugin creation failed: {0}").format(exc),
        )


def prepare_demo(request, code):
    """Create plugins and inject on all boards (one-click demo setup)."""
    create_plugins(request, code)
    inject_all(request)


def _inject_plugin_on_board(request, board_id, plugin_id, board_label):
    """Inject plugin if missing; return True when present on board."""
    if not board_id or not plugin_id:
        return False
    if _plugin_on_board(request, board_id, plugin_id):
        return True
    iotronic.plugin_inject(request, board_id, plugin_id, False)
    return True


def inject_all(request):
    injected_boards = 0
    injected_plugins = 0
    issues = []
    plugins = _plugins_by_name(request)
    specs = get_client_specs(request)
    session = request.session

    for spec in specs:
        board_id = spec.get("board_id", "")
        if not board_id:
            issues.append(_("Board {0} not found.").format(spec["board_name"]))
            continue
        board_ok = True
        for plugin_name in FL_LAB_PLUGIN_NAMES:
            plugin_id = plugins.get(plugin_name, "")
            if not plugin_id:
                issues.append(
                    _("Plugin '{0}' missing - create FL client plugins first.").format(
                        plugin_name
                    )
                )
                board_ok = False
                continue
            try:
                if _inject_plugin_on_board(
                    request, board_id, plugin_id, spec["board_name"]
                ):
                    injected_plugins += 1
            except Exception as exc:
                LOG.exception("inject failed for %s / %s", spec["board_name"], plugin_name)
                issues.append("{0} ({1}): {2}".format(
                    spec["board_name"], plugin_name, safe_exception_text(exc)
                ))
                board_ok = False
        if board_ok:
            injected_boards += 1
            assign = session.get("fl_assign_{0}".format(spec["slug"])) or {}
            plugin_name = assign.get("plugin_name") or read_selected_lab_plugin(
                session, plugins
            )
            plugin_id = plugins.get(plugin_name, "") or plugins.get(FL_PLUGIN_HEART, "")
            session["fl_assign_{0}".format(spec["slug"])] = {
                "board_id": board_id,
                "plugin_id": plugin_id,
                "board_name": spec["board_name"],
                "plugin_name": plugin_name,
            }
    session.modified = True

    total = len(specs)
    if total and injected_boards == total and not issues:
        messages.success(
            request,
            _("FL plugins (heart + PM) injected on all {0} edge board(s).").format(
                injected_boards
            ),
        )
    elif injected_boards:
        messages.warning(
            request,
            _("Injected on {0}/{1} boards ({2} plugin ops). {3}").format(
                injected_boards,
                total,
                injected_plugins,
                "; ".join(issues),
            ),
        )
    elif not total:
        messages.error(request, _("No edge boards found."))
    else:
        messages.error(
            request,
            _("Injection failed. {0}").format("; ".join(issues) or _("Unknown error.")),
        )


def inject_client(request, board_id, plugin_id):
    iotronic.plugin_inject(request, board_id, plugin_id, False)
    messages.success(request, _("Plugin injected on board."))


def start_client(request, board_id, plugin_id, params_json, client_spec=None):
    global_cfg = read_global_config(request.session)
    if client_spec:
        params = merge_params(client_spec, global_cfg, params_json)
    else:
        params = json.loads(params_json) if params_json.strip() else {}
    iotronic.plugin_action(request, board_id, plugin_id, "PluginStart", params)
    messages.success(request, _("FL client started."))


def stop_client(request, board_id, plugin_id):
    iotronic.plugin_action(request, board_id, plugin_id, "PluginStop", {})
    messages.success(request, _("FL client stopped."))


def save_global_lab_config(session, form_data):
    cfg = read_global_config(session)
    for key in GLOBAL_PARAM_KEYS:
        if key in form_data and str(form_data[key]).strip():
            cfg[key] = str(form_data[key]).strip()
    if form_data.get("fl_scenario") in FL_SCENARIOS:
        cfg["fl_scenario"] = form_data["fl_scenario"]
    save_global_config(session, cfg)
    _write_lab_config_file(cfg)
    return cfg


def _write_lab_config_file(cfg):
    try:
        import os
        path = LAB_CONFIG_PATH
        parent = os.path.dirname(path)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent)
        with open(path, "w") as fh:
            fh.write(json.dumps(cfg, indent=2, sort_keys=True))
    except (IOError, OSError) as exc:
        LOG.warning("Could not write lab config file: %s", exc)


def ensure_lab_config_from_post(session, form_data):
    """Persist lab fields from POST when present; return merged active config."""
    if any(str(form_data.get(k, "")).strip() for k in GLOBAL_PARAM_KEYS):
        return save_global_lab_config(session, form_data)
    return read_global_config(session)


def apply_global_to_all_params(session, global_cfg, specs):
    """Update server/dashboard URLs in per-board JSON; CSV stays tied to cloud plugin."""
    for spec in specs:
        slug = spec["slug"]
        params_key = "fl_params_{0}".format(slug)
        existing = session.get(params_key, "")
        try:
            obj = json.loads(existing) if existing else {}
            if not isinstance(obj, dict):
                obj = {}
        except (ValueError, TypeError):
            obj = {}
        if spec.get("board_name") and spec.get("csv_file"):
            urls = default_params(spec, global_cfg)
            if obj:
                obj["server_address"] = urls["server_address"]
                obj["dashboard_url"] = urls["dashboard_url"]
                session[params_key] = json.dumps(obj, indent=2, sort_keys=True)
            else:
                assign = session.get("fl_assign_{0}".format(slug)) or {}
                plugin_name = assign.get("plugin_name") or spec.get("plugin_name")
                built = params_for_plugin_board(
                    plugin_name, spec["board_name"], global_cfg
                )
                session[params_key] = built or default_params_json(spec, global_cfg)
        else:
            session[params_key] = stub_params_json(spec)
    session.modified = True
