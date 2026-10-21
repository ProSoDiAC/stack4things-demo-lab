# -*- coding: utf-8 -*-

from django.utils.translation import ugettext_lazy as _
from django.views.generic import TemplateView

from horizon import messages

from openstack_dashboard.api import iotronic

from iotronic_ui_lab.iot.iot_wot import wot_helpers


class IndexView(TemplateView):
    template_name = "iot_wot/index.html"

    def get_context_data(self, **kwargs):
        context = super(IndexView, self).get_context_data(**kwargs)
        request = self.request
        context["page_title"] = _("Web Services (WoT)")

        stream_key = request.GET.get("thing", "").strip()
        boards = []
        try:
            boards = iotronic.board_list(request, "online", None, None)
            boards.sort(key=lambda b: b.name)
        except Exception as exc:
            messages.warning(
                request,
                _("Unable to list boards: {0}").format(str(exc)[:120]),
            )

        host, tunnels = wot_helpers.collect_wot_tunnels(request, boards)
        selected = None
        if stream_key:
            for tunnel in tunnels:
                if tunnel.get("stream_key") == stream_key:
                    selected = tunnel
                    break
        if not selected and tunnels:
            selected = tunnels[0]

        context["lab_host"] = host
        context["tunnels"] = tunnels
        context["selected_thing"] = selected
        context["selected_stream_key"] = (
            selected.get("stream_key") if selected else stream_key
        )
        context["thing_url"] = selected.get("public_url") if selected else ""

        return context
