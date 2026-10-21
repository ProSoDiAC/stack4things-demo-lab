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

from django.utils.translation import ugettext_lazy as _

from horizon import exceptions
from horizon import forms
from horizon import messages

from openstack_dashboard.api import iotronic
from openstack_dashboard import policy

from iotronic_ui.iot.fleets import fleet_helpers

LOG = logging.getLogger(__name__)


def _init_board_multiselect(form, kwargs, field_name="board_list"):
    choices = kwargs.get("initial", {}).get("board_choices", [])
    form.fields[field_name].choices = choices
    form.fields[field_name].max_length = len(choices)


class CreateFleetForm(forms.SelfHandlingForm):
    name = forms.CharField(label=_("Fleet Name"))

    description = forms.CharField(
        label=_("Description"),
        widget=forms.Textarea(
            attrs={'class': 'switchable', 'data-slug': 'slug-description'})
    )

    board_list = forms.MultipleChoiceField(
        label=_("Member boards"),
        required=False,
        widget=forms.SelectMultiple(
            attrs={'class': 'switchable', 'data-slug': 'slug-fleet-boards'}),
        help_text=_("Select online boards to include in this fleet."),
    )

    def __init__(self, *args, **kwargs):
        super(CreateFleetForm, self).__init__(*args, **kwargs)
        _init_board_multiselect(self, kwargs)

    def handle(self, request, data):
        try:
            fleet = iotronic.fleet_create(
                request, data["name"], data["description"]
            )
            # Upstream fleet_create historically returned None; recover by name.
            if fleet is None or not getattr(fleet, "uuid", None):
                for item in iotronic.fleet_list(request, None) or []:
                    if getattr(item, "name", None) == data["name"]:
                        fleet = item
                        break
            if fleet is None or not getattr(fleet, "uuid", None):
                raise RuntimeError("fleet_create returned no fleet object")
            fleet_helpers.set_fleet_members(
                request, fleet.uuid, data.get("board_list") or []
            )
            messages.success(
                request,
                _("Fleet %(name)s created successfully.")
                % {"name": data["name"]},
            )
            return True
        except Exception:
            exceptions.handle(request, _('Unable to create fleet.'))


class UpdateFleetForm(forms.SelfHandlingForm):
    uuid = forms.CharField(label=_("Fleet ID"), widget=forms.HiddenInput)
    name = forms.CharField(label=_("Fleet Name"))
    description = forms.CharField(
        label=_("Description"),
        widget=forms.Textarea(
            attrs={'class': 'switchable', 'data-slug': 'slug-description'})
    )

    def __init__(self, *args, **kwargs):

        super(UpdateFleetForm, self).__init__(*args, **kwargs)

        # Admin
        if policy.check((("iot", "iot:update_fleets"),), self.request):
            pass

        # Manager or Admin of the iot project
        elif (policy.check((("iot", "iot_manager"),), self.request) or
              policy.check((("iot", "iot_admin"),), self.request)):
            pass

        # Other users
        else:
            if self.request.user.id != kwargs["initial"]["owner"]:
                self.fields["name"].widget.attrs = {'readonly': 'readonly'}
                self.fields["description"].widget.attrs = {'readonly': 'readonly'}

    def handle(self, request, data):
        try:
            iotronic.fleet_update(request, data["uuid"],
                                    {"name": data["name"],
                                     "description": data["description"]})

            messages.success(request, _("Fleet updated successfully."))
            return True

        except Exception:
            exceptions.handle(request, _('Unable to update fleet.'))


class ManageFleetMembersForm(forms.SelfHandlingForm):
    fleet_id = forms.CharField(widget=forms.HiddenInput)
    fleet_name = forms.CharField(
        label=_("Fleet"),
        widget=forms.TextInput(attrs={'readonly': 'readonly'}),
    )

    board_list = forms.MultipleChoiceField(
        label=_("Member boards"),
        widget=forms.SelectMultiple(
            attrs={'class': 'switchable', 'data-slug': 'slug-fleet-members'}),
        help_text=_("Selected boards belong to this fleet. Operations run on all members."),
    )

    def __init__(self, *args, **kwargs):
        super(ManageFleetMembersForm, self).__init__(*args, **kwargs)
        _init_board_multiselect(self, kwargs)

    def handle(self, request, data):
        try:
            fleet_helpers.set_fleet_members(
                request, data["fleet_id"], data.get("board_list") or []
            )
            messages.success(request, _("Fleet membership updated."))
            return True
        except Exception:
            exceptions.handle(request, _('Unable to update fleet members.'))


class FleetPluginOpForm(forms.SelfHandlingForm):
    """Base: pick a cloud plugin; action runs on every fleet member board."""

    fleet_id = forms.CharField(widget=forms.HiddenInput)
    plugin_id = forms.ChoiceField(
        label=_("Plugin"),
        widget=forms.Select(
            attrs={'class': 'switchable', 'data-slug': 'slug-fleet-plugin'}),
    )

    member_summary = forms.CharField(
        label=_("Fleet members"),
        required=False,
        widget=forms.TextInput(attrs={'readonly': 'readonly'}),
    )

    def __init__(self, *args, **kwargs):
        super(FleetPluginOpForm, self).__init__(*args, **kwargs)
        initial = kwargs.get("initial", {})
        plugins = initial.get("plugin_list", [])
        self.fields["plugin_id"].choices = plugins


class FleetInjectPluginForm(FleetPluginOpForm):
    onboot = forms.BooleanField(label=_("On Boot"), required=False)

    def handle(self, request, data):
        try:
            return fleet_helpers.inject_plugin_on_fleet(
                request,
                data["fleet_id"],
                data["plugin_id"],
                data.get("onboot") or False,
            )
        except Exception:
            exceptions.handle(
                request, _('Unable to inject plugin on fleet boards.')
            )


class FleetStartPluginForm(FleetPluginOpForm):
    parameters = forms.CharField(
        label=_("Parameters"),
        required=False,
        widget=forms.Textarea(
            attrs={'class': 'switchable',
                   'data-slug': 'slug-fleet-start-json'}),
        help_text=_("JSON start parameters (same for every board)."),
    )

    def handle(self, request, data):
        try:
            params = fleet_helpers.parse_json_field(data.get("parameters"))
            return fleet_helpers.start_plugin_on_fleet(
                request, data["fleet_id"], data["plugin_id"], params
            )
        except Exception:
            exceptions.handle(
                request, _('Unable to start plugin on fleet boards.')
            )


class FleetStopPluginForm(FleetPluginOpForm):
    delay = forms.IntegerField(
        label=_("Delay (seconds)"),
        required=False,
        help_text=_("Optional wait before stopping on each board."),
    )

    def handle(self, request, data):
        try:
            delay = data.get("delay")
            return fleet_helpers.stop_plugin_on_fleet(
                request, data["fleet_id"], data["plugin_id"], delay
            )
        except Exception:
            exceptions.handle(
                request, _('Unable to stop plugin on fleet boards.')
            )


class FleetCallPluginForm(FleetPluginOpForm):
    parameters = forms.CharField(
        label=_("Parameters"),
        required=False,
        widget=forms.Textarea(
            attrs={'class': 'switchable',
                   'data-slug': 'slug-fleet-call-json'}),
        help_text=_("JSON call parameters (same for every board)."),
    )

    def handle(self, request, data):
        try:
            params = fleet_helpers.parse_json_field(data.get("parameters"))
            return fleet_helpers.call_plugin_on_fleet(
                request, data["fleet_id"], data["plugin_id"], params
            )
        except Exception:
            exceptions.handle(
                request, _('Unable to call plugin on fleet boards.')
            )


class FleetRemovePluginForm(FleetPluginOpForm):
    def handle(self, request, data):
        try:
            return fleet_helpers.remove_plugin_on_fleet(
                request, data["fleet_id"], data["plugin_id"]
            )
        except Exception:
            exceptions.handle(
                request, _('Unable to remove plugin from fleet boards.')
            )
