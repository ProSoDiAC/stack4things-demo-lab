# -*- coding: utf-8 -*-

import json
import os

from django.core.urlresolvers import reverse
from django.http import HttpResponseRedirect
from django.utils.translation import ugettext_lazy as _
from django.views.generic import TemplateView

from horizon import exceptions
from horizon import messages

from iotronic_ui_lab.iot.federated_learning import fl_helpers
from iotronic_ui_lab.iot.federated_learning import fl_server_ctl
from iotronic_ui_lab.iot.federated_learning.fl_helpers import safe_exception_text
from iotronic_ui_lab.iot.federated_learning.fl_constants import scenario_from_plugin_name, scenario_label


class IndexView(TemplateView):
    template_name = "federated_learning/index.html"

    def get_context_data(self, **kwargs):
        context = super(IndexView, self).get_context_data(**kwargs)
        request = self.request
        clients, meta = fl_helpers.build_client_rows(request, request.session)
        context["page_title"] = _("Federated Learning")
        context["clients"] = clients
        context["global_config"] = meta["global_config"]
        context["fl_scenarios"] = meta.get("fl_scenarios", {})
        context["selected_lab_plugin"] = meta.get("selected_lab_plugin", "")
        context["fl_lab_plugin_ids"] = meta.get("fl_lab_plugin_ids", {})
        plugin_codes = meta.get("fl_lab_plugin_codes", {})
        selected = meta.get("selected_lab_plugin") or "fl-client-heart"
        context["fl_lab_plugin_codes_json"] = json.dumps(plugin_codes, ensure_ascii=True)
        context["plugin_display_code"] = plugin_codes.get(
            selected, plugin_codes.get("fl-client-heart", "")
        )
        context["workflow_step"] = meta["workflow_step"]
        context["plugins_exist"] = meta["plugins_exist"]
        context["injected_count"] = meta["injected_count"]
        context["all_injected"] = meta["all_injected"]
        context["total_clients"] = meta["total_clients"]
        context["all_plugins"] = meta["all_plugins"]
        context["all_boards"] = meta["all_boards"]
        context["server_status"] = fl_server_ctl.server_status(meta["global_config"])
        context["fl_dashboard_url"] = _dashboard_embed_url(request, meta["global_config"])
        active_scenario = meta["global_config"].get("fl_scenario") or scenario_from_plugin_name(
            meta.get("selected_lab_plugin", "")
        ) or "heart"
        context["active_scenario"] = active_scenario
        context["active_scenario_label"] = scenario_label(active_scenario)
        return context

    def _client_specs(self, request):
        return fl_helpers.get_client_specs(request)

    def _apply_lab_post(self, request, apply_clients=False):
        cfg = fl_helpers.ensure_lab_config_from_post(request.session, request.POST)
        if apply_clients and request.POST.get("apply_to_clients") == "1":
            fl_helpers.apply_global_to_all_params(
                request.session, cfg, self._client_specs(request)
            )
        return cfg

    def _post_action(self, request):
        return request.POST.get("fl_action", "").strip()

    def post(self, request, *args, **kwargs):
        action = self._post_action(request)
        redirect = HttpResponseRedirect(reverse("horizon:iot:federated_learning:index"))

        try:
            if not action:
                messages.warning(request, _("No action selected."))
                return redirect

            if action == "save_code":
                code = request.POST.get("code", "")
                fl_helpers.save_plugin_code(request.session, code)
                messages.success(request, _("Plugin source saved for this session."))

            elif action == "create_plugins":
                code = request.POST.get("code", "") or fl_helpers.read_plugin_code(
                    request.session
                )
                if not code.strip():
                    messages.error(request, _("Plugin source is empty."))
                else:
                    fl_helpers.save_plugin_code(request.session, code)
                    lab_plugin = request.POST.get("fl_lab_plugin", "").strip()
                    if lab_plugin:
                        fl_helpers.save_selected_lab_plugin(
                            request.session, lab_plugin
                        )
                    fl_helpers.create_plugins(request, code)

            elif action == "save_assignments":
                specs = self._client_specs(request)
                fl_helpers.save_assignments(request.session, request.POST, specs)
                messages.success(request, _("Board / plugin mapping saved."))

            elif action == "inject_selected":
                specs = self._client_specs(request)
                cfg = fl_helpers.read_global_config(request.session)
                fl_helpers.ensure_lab_plugin_assignments(
                    request, request.session, specs, request.POST, cfg
                )
                fl_helpers.save_assignments(request.session, request.POST, specs)
                fl_helpers.inject_selected(request, request.session)

            elif action == "inject_all":
                fl_helpers.inject_all(request)

            elif action == "prepare_demo":
                code = request.POST.get("code", "") or fl_helpers.read_plugin_code(
                    request.session
                )
                if not code.strip():
                    messages.error(request, _("Plugin source is empty."))
                else:
                    fl_helpers.save_plugin_code(request.session, code)
                    fl_helpers.prepare_demo(request, code)

            elif action == "save_global_config":
                cfg = fl_helpers.save_global_lab_config(request.session, request.POST)
                if request.POST.get("apply_to_clients") == "1":
                    fl_helpers.apply_global_to_all_params(
                        request.session, cfg, self._client_specs(request)
                    )
                specs = self._client_specs(request)
                st = fl_server_ctl.server_status(cfg)
                if st.get("running"):
                    fl_helpers.ensure_lab_plugin_assignments(
                        request, request.session, specs, request.POST, cfg
                    )
                    fl_helpers.save_assignments(request.session, request.POST, specs)
                    active = fl_helpers.validate_lab_scenarios(
                        request, request.session, request.POST
                    )
                    cfg["fl_scenario"] = active
                    fl_helpers.save_global_lab_config(request.session, cfg)
                    fl_helpers.stop_all_clients(request, request.session, quiet=True)
                    fl_server_ctl.restart_server(request, cfg)
                    fl_helpers.restart_all_clients(request, request.session, cfg)
                    messages.info(
                        request,
                        _("Parameters saved - Flower server restarted with new settings."),
                    )
                else:
                    fl_helpers.save_assignments(request.session, request.POST, specs)
                    messages.success(
                        request,
                        _("Parameters saved - use Start server to apply."),
                    )

            elif action == "run_lab_plugin":
                cfg = fl_helpers.read_global_config(request.session)
                st = fl_server_ctl.server_status(cfg)
                fl_helpers.run_lab_scenario(
                    request, request.session, request.POST, st.get("running")
                )

            elif action == "start_fl_server":
                cfg = self._apply_lab_post(request, apply_clients=True)
                specs = self._client_specs(request)
                fl_helpers.ensure_lab_plugin_assignments(
                    request, request.session, specs, request.POST, cfg
                )
                fl_helpers.save_assignments(request.session, request.POST, specs)
                active = fl_helpers.validate_lab_scenarios(
                    request, request.session, request.POST
                )
                cfg["fl_scenario"] = active
                fl_helpers.save_global_lab_config(request.session, cfg)
                fl_helpers.stop_all_clients(request, request.session, quiet=True)
                fl_server_ctl.start_server(request, cfg)
                fl_helpers.restart_all_clients(request, request.session, cfg)
                messages.info(
                    request,
                    _("Flower server and edge clients started - live topology updates during FL rounds."),
                )

            elif action == "stop_fl_server":
                cfg = self._apply_lab_post(request, apply_clients=False)
                fl_helpers.stop_all_clients(request, request.session, quiet=True)
                fl_server_ctl.stop_server(request, cfg)

            elif action == "restart_fl_server":
                cfg = self._apply_lab_post(request, apply_clients=True)
                specs = self._client_specs(request)
                fl_helpers.ensure_lab_plugin_assignments(
                    request, request.session, specs, request.POST, cfg
                )
                fl_helpers.save_assignments(request.session, request.POST, specs)
                active = fl_helpers.validate_lab_scenarios(
                    request, request.session, request.POST
                )
                cfg["fl_scenario"] = active
                fl_helpers.save_global_lab_config(request.session, cfg)
                fl_helpers.stop_all_clients(request, request.session, quiet=True)
                fl_server_ctl.restart_server(request, cfg)
                fl_helpers.restart_all_clients(request, request.session, cfg)
                messages.info(
                    request,
                    _("Server restarted and edge clients reconnected - watch live topology."),
                )

            elif action == "start_all_clients":
                cfg = self._apply_lab_post(request, apply_clients=True)
                specs = self._client_specs(request)
                fl_helpers.ensure_lab_plugin_assignments(
                    request, request.session, specs, request.POST, cfg
                )
                fl_helpers.save_assignments(request.session, request.POST, specs)
                active = fl_helpers.validate_lab_scenarios(
                    request, request.session, request.POST
                )
                cfg["fl_scenario"] = active
                fl_helpers.save_global_lab_config(request.session, cfg)
                st = fl_server_ctl.server_status(cfg)
                if not st.get("running"):
                    messages.warning(
                        request,
                        _("Flower server is not running - use Start server first."),
                    )
                else:
                    fl_helpers.start_all_clients(request, request.session)

            elif action == "stop_all_clients":
                specs = self._client_specs(request)
                fl_helpers.save_assignments(request.session, request.POST, specs)
                fl_helpers.stop_all_clients(request, request.session)

        except exceptions.WorkflowValidationError as exc:
            messages.error(request, safe_exception_text(getattr(exc, "message", exc)))
            return redirect
        except Exception as exc:
            LOG_MSG = safe_exception_text(exc)
            hint = ""
            if "flwr" in LOG_MSG:
                hint = _(
                    " Install FL deps on boards: "
                    "./experiments/federated-learning/install-fl-on-boards.sh"
                )
            messages.error(
                request,
                _("FL client operation failed: {0}{1}").format(LOG_MSG, hint),
            )
            return redirect

        return redirect


def _dashboard_embed_url(request, global_cfg):
    """Browser-reachable URL for live topology iframe (not host.docker.internal)."""
    import time
    proxy_path = os.environ.get("FL_DASHBOARD_PROXY_PATH", "/horizon/fl-live/")
    bust = int(time.time())
    if proxy_path:
        return proxy_path.rstrip("/") + "/?embed=1&v={0}".format(bust)
    host = request.META.get("HTTP_HOST", "127.0.0.1").split(":")[0]
    port = global_cfg.get("dashboard_port", "8090")
    return "http://{0}:{1}/?embed=1&v={2}".format(host, port, bust)
