# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import logging

from django.core.urlresolvers import reverse
from django.utils.translation import ugettext_lazy as _

from horizon import tabs

LOG = logging.getLogger(__name__)


class OverviewTab(tabs.Tab):
    name = _("Overview")
    slug = "overview"
    template_name = ("iot/fleets/_detail_overview.html")

    def get_context_data(self, request):
        boards = self.tab_group.kwargs['fleet']._info['boards']

        return {"fleet": self.tab_group.kwargs['fleet'],
                "boards": boards,
                "is_superuser": request.user.is_superuser}


class MembersTab(tabs.Tab):
    name = _("Members")
    slug = "members"
    template_name = ("iot/fleets/_detail_members.html")

    def get_context_data(self, request):
        fleet = self.tab_group.kwargs['fleet']
        boards = fleet._info.get('boards', [])
        fleet_id = fleet.uuid
        return {
            "fleet": fleet,
            "boards": boards,
            "manage_url": reverse("horizon:iot:fleets:members", args=(fleet_id,)),
        }


class OperationsTab(tabs.Tab):
    name = _("Operations")
    slug = "operations"
    template_name = ("iot/fleets/_detail_operations.html")

    def get_context_data(self, request):
        fleet = self.tab_group.kwargs['fleet']
        fleet_id = fleet.uuid
        boards = fleet._info.get('boards', [])
        return {
            "fleet": fleet,
            "boards": boards,
            "inject_url": reverse("horizon:iot:fleets:inject", args=(fleet_id,)),
            "start_url": reverse("horizon:iot:fleets:start", args=(fleet_id,)),
            "stop_url": reverse("horizon:iot:fleets:stop", args=(fleet_id,)),
            "call_url": reverse("horizon:iot:fleets:call", args=(fleet_id,)),
            "remove_url": reverse(
                "horizon:iot:fleets:remove_plugin", args=(fleet_id,)
            ),
        }


class LogsTab(tabs.Tab):
    name = _("LR logs")
    slug = "logs"
    template_name = ("iot/fleets/_detail_logs.html")

    def get_context_data(self, request):
        from iotronic_ui.iot.fleets import fleet_helpers

        fleet = self.tab_group.kwargs['fleet']
        fleet_id = fleet.uuid
        tail = 40
        grep = request.GET.get("grep") or "PluginCall|Hello |PluginInject|RPC "
        panels = fleet_helpers.fleet_lr_log_panels(
            request, fleet_id, tail=tail, grep=grep
        )
        return {
            "fleet": fleet,
            "log_panels": panels,
            "logs_ajax_url": reverse("horizon:iot:fleets:logs_ajax", args=(fleet_id,)),
            "log_tail": tail,
            "log_grep": grep,
            "single_board": False,
            "help_text": _(
                "Last lines from each fleet member Lightning-Rod (docker logs). "
                "Filtered for plugin activity."
            ),
        }


class FleetDetailTabs(tabs.TabGroup):
    slug = "fleet_details"
    tabs = (OverviewTab, MembersTab, OperationsTab, LogsTab)
    sticky = True
