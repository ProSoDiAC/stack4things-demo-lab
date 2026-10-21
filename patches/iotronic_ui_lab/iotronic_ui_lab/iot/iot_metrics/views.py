# -*- coding: utf-8 -*-

import os
import time

from django.core.urlresolvers import reverse
from django.http import HttpResponseRedirect
from django.utils.translation import ugettext_lazy as _
from django.views.generic import TemplateView

from horizon import exceptions
from horizon import messages

from openstack_dashboard.api import iotronic

from iotronic_ui_lab.iot.iot_metrics import metrics_helpers


def _metrics_embed_url(request, board="", measurement="environmental_data"):
    proxy_path = os.environ.get("IOT_METRICS_PROXY_PATH", "/horizon/metrics-live/")
    bust = int(time.time())
    base = proxy_path.rstrip("/") + "/d/s4t-iot-metrics/iot-metrics"
    params = "?kiosk=tv&var-measurement={0}&refresh=30s&v={1}".format(
        measurement, bust
    )
    if board:
        params = "?kiosk=tv&var-board={0}&var-measurement={1}&refresh=30s&v={2}".format(
            board, measurement, bust
        )
    if proxy_path:
        return base + params
    host = request.META.get("HTTP_HOST", "127.0.0.1").split(":")[0]
    return "http://{0}:3000{1}".format(host, base + params)


def _stream_label(stream):
    board = stream.get("board_name") or stream.get("board_uuid") or "?"
    plugin = stream.get("plugin_name") or stream.get("plugin_uuid") or "?"
    measurement = stream.get("measurement") or stream.get("stream_id") or "?"
    return "{0} / {1} ({2})".format(board, plugin, measurement)


class IndexView(TemplateView):
    template_name = "iot_metrics/index.html"

    def get_context_data(self, **kwargs):
        context = super(IndexView, self).get_context_data(**kwargs)
        request = self.request
        context["page_title"] = _("IoT Metrics")

        stream_key = request.GET.get("stream", "").strip()
        window_minutes = 15
        active_streams = []
        provisioned_streams = []

        try:
            active_streams, window_minutes = metrics_helpers.list_active_streams(
                window_minutes
            )
        except Exception as exc:
            messages.warning(
                request,
                _("Could not detect live streams: {0}").format(str(exc)[:120]),
            )

        try:
            provisioned_streams = metrics_helpers.list_streams()
        except Exception as exc:
            messages.warning(
                request,
                _("Metrics server unreachable: {0}").format(str(exc)[:120]),
            )

        live_streams = [s for s in active_streams if s.get("active")]
        for stream in live_streams:
            stream["label"] = _stream_label(stream)

        selected = None
        if stream_key:
            for stream in live_streams:
                if stream.get("stream_key") == stream_key:
                    selected = stream
                    break
        if not selected and live_streams:
            selected = live_streams[0]

        try:
            context["metrics_health"] = metrics_helpers.server_health()
        except Exception:
            context["metrics_health"] = {"ok": False}

        try:
            boards = iotronic.board_list(request, "online", None, None)
            boards.sort(key=lambda b: b.name)
            context["boards"] = boards
        except Exception:
            context["boards"] = []

        try:
            plugins = iotronic.plugin_list(request, None, None, all_plugins=True)
            plugins.sort(key=lambda p: p.name)
            context["plugins"] = plugins
        except Exception:
            context["plugins"] = []

        board_name = ""
        measurement = "environmental_data"
        if selected:
            board_name = selected.get("board_name") or ""
            measurement = selected.get("measurement") or selected.get("stream_id") or measurement
            stream_key = selected.get("stream_key") or stream_key

        context["live_streams"] = live_streams
        context["provisioned_streams"] = provisioned_streams
        context["streams"] = live_streams or provisioned_streams
        context["selected_stream_key"] = stream_key
        context["selected_stream"] = selected
        context["active_window_minutes"] = window_minutes
        context["selected_board_name"] = board_name
        context["selected_measurement"] = measurement
        context["metrics_dashboard_url"] = _metrics_embed_url(
            request, board=board_name, measurement=measurement
        )

        return context

    def post(self, request, *args, **kwargs):
        redirect = HttpResponseRedirect(reverse("horizon:iot:iot_metrics:index"))
        action = request.POST.get("metrics_action", "").strip()

        try:
            if action == "provision":
                board_uuid = request.POST.get("board_uuid", "").strip()
                plugin_uuid = request.POST.get("plugin_uuid", "").strip()
                measurement = request.POST.get("measurement", "environmental_data").strip()
                board_name = request.POST.get("board_name", "").strip()
                plugin_name = request.POST.get("plugin_name", "").strip()

                if not board_uuid or not plugin_uuid:
                    messages.error(request, _("Board and plugin are required."))
                    return redirect

                payload = {
                    "board_uuid": board_uuid,
                    "board_name": board_name,
                    "plugin_uuid": plugin_uuid,
                    "plugin_name": plugin_name,
                    "measurement": measurement,
                    "field_schema": ["Temperature", "Humidity", "PM10", "PM25"],
                }
                result = metrics_helpers.provision_stream(payload)
                messages.success(
                    request,
                    _("Stream provisioned: {0}").format(result.get("stream_id", "")),
                )
                url = reverse("horizon:iot:iot_metrics:index")
                stream_key = "{0}|{1}|{2}".format(
                    measurement, board_name, plugin_name
                )
                return HttpResponseRedirect(
                    "{0}?stream={1}".format(url, stream_key)
                )

            messages.warning(request, _("No action selected."))
        except Exception as exc:
            exceptions.handle(request, unicode(exc))

        return redirect
