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

# -*- coding: utf-8 -*-

import logging

from django.core.urlresolvers import reverse
from django.core.urlresolvers import reverse_lazy
from django.http import HttpResponse
from django.utils.translation import ugettext_lazy as _
from django.views.generic import View

from horizon import exceptions
from horizon import forms
from horizon import tables
from horizon import tabs
from horizon.utils import memoized

from openstack_dashboard.api import iotronic
from openstack_dashboard import policy

from iotronic_ui.iot.fleets import fleet_helpers
from iotronic_ui.iot.fleets import forms as project_forms
from iotronic_ui.iot.fleets import tables as project_tables
from iotronic_ui.iot.fleets import tabs as project_tabs


LOG = logging.getLogger(__name__)


class IndexView(tables.DataTableView):
    table_class = project_tables.FleetsTable
    template_name = 'iot/fleets/index.html'
    page_title = _("Fleets")

    def get_data(self):
        fleets = []

        if policy.check((("iot", "iot:list_all_fleets"),), self.request):
            try:
                fleets = iotronic.fleet_list(self.request, None)
            except Exception:
                exceptions.handle(self.request,
                                  _('Unable to retrieve fleets list.'))

        elif policy.check((("iot", "iot:list_project_fleets"),),
                          self.request):
            try:
                fleets = iotronic.fleet_list(self.request, None)
            except Exception:
                exceptions.handle(self.request,
                                  _('Unable to retrieve user fleets list.'))

        else:
            try:
                fleets = iotronic.fleet_list(self.request, None)
            except Exception:
                exceptions.handle(self.request,
                                  _('Unable to retrieve user fleets list.'))

        return fleets


class CreateView(forms.ModalFormView):
    template_name = 'iot/fleets/create.html'
    modal_header = _("Create Fleet")
    form_id = "create_fleet_form"
    form_class = project_forms.CreateFleetForm
    submit_label = _("Create Fleet")
    submit_url = reverse_lazy("horizon:iot:fleets:create")
    success_url = reverse_lazy('horizon:iot:fleets:index')
    page_title = _("Create Fleet")

    def get_initial(self):
        return {
            "board_choices": fleet_helpers.online_board_choices(self.request),
        }


class UpdateView(forms.ModalFormView):
    template_name = 'iot/fleets/update.html'
    modal_header = _("Update Fleet")
    form_id = "update_fleet_form"
    form_class = project_forms.UpdateFleetForm
    submit_label = _("Update Fleet")
    submit_url = "horizon:iot:fleets:update"
    success_url = reverse_lazy('horizon:iot:fleets:index')
    page_title = _("Update Fleet")

    @memoized.memoized_method
    def get_object(self):
        try:
            return iotronic.fleet_get(self.request,
                                        self.kwargs['fleet_id'],
                                        None)
        except Exception:
            redirect = reverse("horizon:iot:fleets:index")
            exceptions.handle(self.request,
                              _('Unable to get fleet information.'),
                              redirect=redirect)

    def get_context_data(self, **kwargs):
        context = super(UpdateView, self).get_context_data(**kwargs)
        args = (self.get_object().uuid,)
        context['submit_url'] = reverse(self.submit_url, args=args)
        return context

    def get_initial(self):
        fleet = self.get_object()

        return {'uuid': fleet.uuid,
                'name': fleet.name,
                'description': fleet.description}


class _FleetScopedMixin(object):
    """Common fleet lookup and member summary for plugin operation modals."""

    redirect_url = 'horizon:iot:fleets:detail'

    @memoized.memoized_method
    def get_fleet(self):
        fleet_id = self.kwargs['fleet_id']
        try:
            return iotronic.fleet_get(self.request, fleet_id, None)
        except Exception:
            redirect = reverse("horizon:iot:fleets:index")
            exceptions.handle(self.request,
                              _('Unable to get fleet information.'),
                              redirect=redirect)

    def get_success_url(self):
        fleet = self.get_fleet()
        return reverse(self.redirect_url, args=(fleet.uuid,))

    def _member_summary(self, fleet_id):
        boards = fleet_helpers.fleet_boards(self.request, fleet_id)
        if not boards:
            return _("(no members - use Members tab)")
        return ", ".join(b.name for b in boards)

    def get_context_data(self, **kwargs):
        context = super(_FleetScopedMixin, self).get_context_data(**kwargs)
        fleet = self.get_fleet()
        context['submit_url'] = reverse(self.submit_url, args=(fleet.uuid,))
        return context

    def get_initial(self):
        fleet = self.get_fleet()
        return {
            'fleet_id': fleet.uuid,
            'member_summary': self._member_summary(fleet.uuid),
            'plugin_list': fleet_helpers.plugin_choices(self.request),
        }


class ManageMembersView(_FleetScopedMixin, forms.ModalFormView):
    template_name = 'iot/fleets/manage_members.html'
    modal_header = _("Manage fleet members")
    form_id = "manage_fleet_members_form"
    form_class = project_forms.ManageFleetMembersForm
    submit_label = _("Save members")
    submit_url = "horizon:iot:fleets:members"
    page_title = _("Manage fleet members")

    def get_initial(self):
        fleet = self.get_fleet()
        member_ids = fleet_helpers.fleet_board_ids(self.request, fleet.uuid)
        return {
            'fleet_id': fleet.uuid,
            'fleet_name': fleet.name,
            'board_choices': fleet_helpers.online_board_choices(self.request),
            'board_list': member_ids,
        }


class FleetInjectView(_FleetScopedMixin, forms.ModalFormView):
    template_name = 'iot/fleets/inject.html'
    modal_header = _("Inject plugin on fleet")
    form_id = "fleet_inject_form"
    form_class = project_forms.FleetInjectPluginForm
    submit_label = _("Inject on all members")
    submit_url = "horizon:iot:fleets:inject"


class FleetStartView(_FleetScopedMixin, forms.ModalFormView):
    template_name = 'iot/fleets/start.html'
    modal_header = _("Start plugin on fleet")
    form_id = "fleet_start_form"
    form_class = project_forms.FleetStartPluginForm
    submit_label = _("Start on all members")
    submit_url = "horizon:iot:fleets:start"


class FleetStopView(_FleetScopedMixin, forms.ModalFormView):
    template_name = 'iot/fleets/stop.html'
    modal_header = _("Stop plugin on fleet")
    form_id = "fleet_stop_form"
    form_class = project_forms.FleetStopPluginForm
    submit_label = _("Stop on all members")
    submit_url = "horizon:iot:fleets:stop"


class FleetCallView(_FleetScopedMixin, forms.ModalFormView):
    template_name = 'iot/fleets/call.html'
    modal_header = _("Call plugin on fleet")
    form_id = "fleet_call_form"
    form_class = project_forms.FleetCallPluginForm
    submit_label = _("Call on all members")
    submit_url = "horizon:iot:fleets:call"


class FleetRemovePluginView(_FleetScopedMixin, forms.ModalFormView):
    template_name = 'iot/fleets/remove_plugin.html'
    modal_header = _("Remove plugin from fleet")
    form_id = "fleet_remove_form"
    form_class = project_forms.FleetRemovePluginForm
    submit_label = _("Remove from all members")
    submit_url = "horizon:iot:fleets:remove_plugin"


class FleetLogsAjaxView(View):
    """JSON tail of LR docker logs for fleet member boards."""

    def get(self, request, fleet_id):
        import json

        tail = 40
        try:
            tail = int(request.GET.get("tail", 40))
        except (TypeError, ValueError):
            tail = 40
        tail = max(1, min(tail, 200))
        grep = request.GET.get("grep") or None
        refresh = request.GET.get("refresh") in ("1", "true", "yes")
        boards = fleet_helpers.fleet_boards(request, fleet_id)
        names = [b.name for b in boards]
        uuids = [b.uuid for b in boards]
        from iotronic_ui_lab.iot.lr_logs import helpers as lr_logs

        data = lr_logs.fetch_lr_logs(
            board_names=names,
            board_uuids=uuids,
            tail=tail,
            grep=grep,
            refresh=refresh,
        )
        return HttpResponse(
            json.dumps({"boards": data, "tail": tail}),
            content_type="application/json",
        )


class DetailView(tabs.TabView):
    tab_group_class = project_tabs.FleetDetailTabs
    template_name = 'horizon/common/_detail.html'
    page_title = "{{ fleet.name|default:fleet.uuid }}"

    def get_context_data(self, **kwargs):
        context = super(DetailView, self).get_context_data(**kwargs)
        fleet = self.get_data()
        context["fleet"] = fleet
        context["url"] = reverse(self.redirect_url)
        context["actions"] = self._get_actions(fleet)

        return context

    def _get_actions(self, fleet):
        table = project_tables.FleetsTable(self.request)
        return table.render_row_actions(fleet)

    @memoized.memoized_method
    def get_data(self):
        fleet = []
        fleet_boards = []

        fleet_id = self.kwargs['fleet_id']
        try:
            fleet = iotronic.fleet_get(self.request, fleet_id, None)
            boards = iotronic.fleet_get_boards(self.request, fleet_id)

            for board in boards:
                fleet_boards.append(board._info)

            fleet._info.update(dict(boards=fleet_boards))

        except Exception:
            s = fleet.name
            msg = ('Unable to retrieve fleet %s information') % {'name': s}
            exceptions.handle(self.request, msg, ignore=True)
        return fleet

    def get_tabs(self, request, *args, **kwargs):
        fleet = self.get_data()
        return self.tab_group_class(request, fleet=fleet, **kwargs)


class FleetDetailView(DetailView):
    redirect_url = 'horizon:iot:fleets:index'

    def _get_actions(self, fleet):
        table = project_tables.FleetsTable(self.request)
        return table.render_row_actions(fleet)
