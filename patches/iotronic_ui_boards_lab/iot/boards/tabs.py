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
    template_name = ("iot/boards/_detail_overview.html")

    def get_context_data(self, request):

        coordinates = self.tab_group.kwargs['board'].__dict__['location'][0]
        ports = self.tab_group.kwargs['board']._info['ports']
        services = self.tab_group.kwargs['board']._info['services']
        webservices = self.tab_group.kwargs['board']._info['webservices']
        plugins = self.tab_group.kwargs['board']._info['plugins']

        return {"board": self.tab_group.kwargs['board'],
                "coordinates": coordinates,
                "services": services,
                "webservices": webservices,
                "ports": ports,
                "plugins": plugins,
                "is_superuser": request.user.is_superuser}


class LogsTab(tabs.Tab):
    name = _("LR logs")
    slug = "logs"
    template_name = ("iot/boards/_detail_logs.html")

    def get_context_data(self, request):
        from iotronic_ui_lab.iot.lr_logs import helpers as lr_logs

        board = self.tab_group.kwargs['board']
        panel = lr_logs.board_log_panel(board.name, board.uuid, tail=50)
        return {
            "board": board,
            "log_panels": [panel],
            "logs_ajax_url": reverse(
                "horizon:iot:boards:logs_ajax", args=(board.uuid,)
            ),
            "log_tail": 50,
            "single_board": True,
            "help_text": _(
                "Live tail of the Lightning-Rod docker logs for this board. "
                "The LR container is detected automatically after registration."
            ),
        }


class NetworkTab(tabs.Tab):
    name = _("Network")
    slug = "network"
    template_name = ("iot/boards/_detail_network.html")

    def get_context_data(self, request):
        from iotronic_ui_lab.iot.lr_logs import helpers as lr_logs

        board = self.tab_group.kwargs['board']
        network = lr_logs.fetch_lr_network(
            board_name=board.name,
            board_uuid=board.uuid,
            refresh=True,
        )
        return {
            "board": board,
            "network": network,
            "network_ajax_url": reverse(
                "horizon:iot:boards:network_ajax", args=(board.uuid,)
            ),
        }


class BoardDetailTabs(tabs.TabGroup):
    slug = "board_details"
    tabs = (OverviewTab, NetworkTab, LogsTab)
    sticky = True
