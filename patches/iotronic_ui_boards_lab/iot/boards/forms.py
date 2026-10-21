# -*- coding: utf-8 -*-
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

LOG = logging.getLogger(__name__)


class CreateBoardForm(forms.SelfHandlingForm):
    name = forms.CharField(label=_("Board Name"))
    code = forms.CharField(
        label=_("Registration Code"),
        help_text=_("Registration code")
    )

    # MODIFY ---> options: yun, server
    type = forms.ChoiceField(
        label=_("Type"),
        # choices=[('yun', _('YUN')), ('server', _('Server'))],
        choices=[('gateway', _('Gateway')), ('server', _('Server'))],
        widget=forms.Select(
            attrs={'class': 'switchable', 'data-slug': 'slug-type'},
        )
    )

    """
    mobile = forms.ChoiceField(
        label=_("Mobile"),
        choices =[('false', _('False')), ('true', _('True'))],
        widget=forms.Select(
            attrs={'class': 'switchable', 'data-slug': 'slug-mobile'},
        )
    )
    """
    mobile = forms.BooleanField(label=_("Mobile"), required=False)

    latitude = forms.FloatField(label=_("Latitude"))
    longitude = forms.FloatField(label=_("Longitude"))
    altitude = forms.FloatField(label=_("Altitude"))

    def handle(self, request, data):
        try:

            # Float
            # data["location"] = [{"latitude": data["latitude"],
            #                      "longitude": data["longitude"],
            #                      "altitude": data["altitude"]}]
            # String
            data["location"] = [{"latitude": str(data["latitude"]),
                                 "longitude": str(data["longitude"]),
                                 "altitude": str(data["altitude"])}]

            iotronic.board_create(request, data["code"],
                                  data["mobile"], data["location"],
                                  data["type"], data["name"])

            messages.success(request, _("Board created successfully."))
            return True

        except Exception:
            exceptions.handle(request, _('Unable to create board.'))


class CreateLabBoardForm(forms.SelfHandlingForm):
    """Create IoTronic board + spawn/register a Lightning-Rod container (lab)."""

    name = forms.CharField(
        label=_("Board Name"),
        required=False,
        help_text=_("Leave empty to auto-name (board-lab-N)."),
    )
    latitude = forms.FloatField(label=_("Latitude"), initial=38.19)
    longitude = forms.FloatField(label=_("Longitude"), initial=15.55)
    altitude = forms.FloatField(label=_("Altitude"), initial=0.0)

    def handle(self, request, data):
        import json
        import os
        import re
        import uuid as uuid_mod

        try:
            import urllib2
        except ImportError:
            import urllib.request as urllib2  # py3

        try:
            name = (data.get("name") or "").strip()
            if not name:
                existing = set()
                try:
                    for b in iotronic.board_list(request) or []:
                        n = getattr(b, "name", None) or ""
                        existing.add(n)
                except Exception:
                    pass
                n = 1
                while "board-lab-{0}".format(n) in existing:
                    n += 1
                name = "board-lab-{0}".format(n)

            if not re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$", name):
                messages.error(
                    request,
                    _("Invalid board name. Use letters, digits, . _ -"),
                )
                return False

            code = "{0}-{1}".format(name, uuid_mod.uuid4().hex[:8])
            location = [{
                "latitude": str(data["latitude"]),
                "longitude": str(data["longitude"]),
                "altitude": str(data["altitude"]),
            }]

            # Match lab boards (virtual) - fall back to server if API rejects type
            try:
                iotronic.board_create(
                    request, code, False, location, "virtual", name
                )
            except Exception:
                iotronic.board_create(
                    request, code, False, location, "server", name
                )

            proxy = os.environ.get(
                "LR_LOG_PROXY_URL", "http://lr-log-proxy:8092"
            ).rstrip("/")
            payload = json.dumps({
                "board_name": name,
                "registration_code": code,
                "wamp_url": os.environ.get(
                    "LR_WAMP_URL", "wss://crossbar:8181"
                ),
            })
            req = urllib2.Request(
                proxy + "/provision",
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            try:
                resp = urllib2.urlopen(req, timeout=180)
                body = resp.read()
            except Exception as exc:
                messages.error(
                    request,
                    _(
                        "Board '{0}' created in IoTronic, but Lightning-Rod "
                        "provision failed ({1}). Configure LR manually with "
                        "code: {2}"
                    ).format(name, exc, code),
                )
                return True

            try:
                result = json.loads(body)
            except Exception:
                result = {}

            if not result.get("ok"):
                messages.error(
                    request,
                    _(
                        "Board '{0}' created, but LR provision error: {1}. "
                        "Registration code: {2}"
                    ).format(
                        name,
                        result.get("error") or body,
                        code,
                    ),
                )
                return True

            host = request.META.get("HTTP_HOST", "127.0.0.1").split(":")[0]
            port = result.get("host_port")
            lr_url = "http://{0}:{1}".format(host, port)
            status = (
                _("online")
                if result.get("operative")
                else _("starting - refresh Boards in a few seconds")
            )
            messages.success(
                request,
                _(
                    "Lab board '{0}' ready ({1}). Lightning-Rod: {2} "
                    "(container {3}, login me / arancino)."
                ).format(
                    name,
                    status,
                    lr_url,
                    result.get("container", ""),
                ),
            )
            return True

        except Exception:
            exceptions.handle(
                request,
                _("Unable to create lab board + Lightning-Rod."),
            )


class UpdateBoardForm(forms.SelfHandlingForm):
    uuid = forms.CharField(label=_("Board ID"), widget=forms.HiddenInput)
    name = forms.CharField(label=_("Board Name"))
    
    fleet_list = forms.ChoiceField(
        label=_("Fleets List"),
        widget=forms.Select(
            attrs={'class': 'switchable', 'data-slug': 'slug-fleet'}),
        help_text=_("Select fleet in this pool "),
        required=False
    )

    mobile = forms.BooleanField(label=_("Mobile"), required=False)

    """
    latitude = forms.FloatField(label=_("Latitude"))
    longitude = forms.FloatField(label=_("Longitude"))
    altitude = forms.FloatField(label=_("Altitude"))
    """

    def __init__(self, *args, **kwargs):

        super(UpdateBoardForm, self).__init__(*args, **kwargs)

        # Populate fleets
        fleets = iotronic.fleet_list(self.request, None)
        fleets.sort(key=lambda b: b.name)

        fleet_list = []
        fleet_list.append((None, _("-")))
        for fleet in fleets:
            fleet_list.append((fleet.uuid, _(fleet.name)))

        # LOG.debug("FLEETS: %s", fleet_list)
        self.fields["fleet_list"].choices = fleet_list
        self.fields["fleet_list"].initial = kwargs["initial"]["fleet_id"]

        # LOG.debug("INITIAL: %s", kwargs["initial"])

        # LOG.debug("Manager: %s", policy.check((("iot", "iot_manager"),),
        #                                            self.request))
        # LOG.debug("Admin: %s", policy.check((("iot", "iot_admin"),),
        #                                          self.request))

        # Admin
        if policy.check((("iot", "iot:update_boards"),), self.request):
            # LOG.debug("ADMIN")
            pass

        # Manager or Admin of the iot project
        elif (policy.check((("iot", "iot_manager"),), self.request) or
              policy.check((("iot", "iot_admin"),), self.request)):
            # LOG.debug("NO-edit IOT ADMIN")
            pass

        # Other users
        else:
            if self.request.user.id != kwargs["initial"]["owner"]:
                # LOG.debug("IMMUTABLE FIELDS")
                self.fields["name"].widget.attrs = {'readonly': 'readonly'}
                self.fields["mobile"].widget.attrs = {'disabled': 'disabled'}
                self.fields["fleet_list"].widget.attrs = {'disabled':
                                                          'disabled'}

                """
                self.fields["latitude"].widget.attrs = {'readonly':
                                                        'readonly'}
                self.fields["longitude"].widget.attrs = {'readonly':
                                                         'readonly'}
                self.fields["altitude"].widget.attrs = {'readonly':
                                                        'readonly'}
                """

    def handle(self, request, data):

        try:

            # data["location"] = [{"latitude": str(data["latitude"]),
            #                      "longitude": str(data["longitude"]),
            #                      "altitude": str(data["altitude"])}]
            # iotronic.board_update(request, data["uuid"],
            #                       {"name": data["name"],
            #                        "mobile": data["mobile"],
            #                        "location": data["location"]})
            if data["fleet_list"] == '':
                data["fleet_list"] = None

            iotronic.board_update(request, data["uuid"],
                                  {"name": data["name"],
                                   "fleet": data["fleet_list"],
                                   "mobile": data["mobile"]})
            messages.success(request, _("Board updated successfully."))
            return True

        except Exception:
            exceptions.handle(request, _('Unable to update board.'))


class EnableServiceForm(forms.SelfHandlingForm):

    uuid = forms.CharField(label=_("Board ID"), widget=forms.HiddenInput)

    name = forms.CharField(
        label=_('Board Name'),
        widget=forms.TextInput(attrs={'readonly': 'readonly'})
    )

    service_list = forms.MultipleChoiceField(
        label=_("Services List"),
        widget=forms.SelectMultiple(
            attrs={'class': 'switchable',
                   'data-slug': 'slug-select-services'}),
        help_text=_("Add available services from this pool")
    )

    def __init__(self, *args, **kwargs):
        super(EnableServiceForm, self).__init__(*args, **kwargs)
        self.fields["service_list"].choices = kwargs["initial"]["service_list"]

    def handle(self, request, data):

        counter = 0
        for service in data["service_list"]:
            try:
                action = iotronic.service_action(request, data["uuid"],
                                                 service, "ServiceEnable")

                # message_text = "Service(s) enabled successfully."
                message_text = action
                messages.success(request, _(message_text))

                if counter != len(data["service_list"]) - 1:
                    counter += 1
                else:
                    return True

            except Exception:
                message_text = "Unable to enable service."
                exceptions.handle(request, _(message_text))


class DisableServiceForm(forms.SelfHandlingForm):

    uuid = forms.CharField(label=_("Board ID"), widget=forms.HiddenInput)

    name = forms.CharField(
        label=_('Board Name'),
        widget=forms.TextInput(attrs={'readonly': 'readonly'})
    )

    service_list = forms.MultipleChoiceField(
        label=_("Services List"),
        widget=forms.SelectMultiple(
            attrs={'class': 'switchable',
                   'data-slug': 'slug-select-services'}),
        help_text=_("Select services to disable from this pool")
    )

    def __init__(self, *args, **kwargs):
        super(DisableServiceForm, self).__init__(*args, **kwargs)
        self.fields["service_list"].choices = kwargs["initial"]["service_list"]

    def handle(self, request, data):

        counter = 0
        for service in data["service_list"]:
            try:
                action = iotronic.service_action(request, data["uuid"],
                                                 service, "ServiceDisable")

                # message_text = "Service(s) disabled successfully."
                message_text = action
                messages.success(request, _(message_text))

                if counter != len(data["service_list"]) - 1:
                    counter += 1
                else:
                    return True

            except Exception:
                message_text = "Unable to disable service."
                exceptions.handle(request, _(message_text))


class AttachPortForm(forms.SelfHandlingForm):

    uuid = forms.CharField(label=_("Board ID"), widget=forms.HiddenInput)

    name = forms.CharField(
        label=_('Board Name'),
        widget=forms.TextInput(attrs={'readonly': 'readonly'})
    )

    networks_list = forms.ChoiceField(
        label=_("Networks List"),
        help_text=_("Select network:subnet from the list")
    )

    def __init__(self, *args, **kwargs):

        super(AttachPortForm, self).__init__(*args, **kwargs)

        net_choices = kwargs["initial"]["networks_list"]
        self.fields["networks_list"].choices = net_choices

    def handle(self, request, data):
        array = data["networks_list"].split(':')
        LOG.debug(array)
        network_id = array[0]
        subnet_id = array[1]

        try:
            attach = iotronic.attach_port(request, data["uuid"],
                                          network_id, subnet_id)

            # LOG.debug("ATTACH: %s", attach)
            ip = attach._info["ip"]

            message_text = "Attached  port to ip " + str(ip) + \
                           " on board " + str(data["name"]) + \
                           " completed successfully"
            messages.success(request, _(message_text))
            return True

        except Exception:
            message_text = "Unable to attach port on board " + \
                           str(data["name"])

            exceptions.handle(request, _(message_text))


class DetachPortForm(forms.SelfHandlingForm):

    uuid = forms.CharField(label=_("Board ID"), widget=forms.HiddenInput)

    name = forms.CharField(
        label=_('Board Name'),
        widget=forms.TextInput(attrs={'readonly': 'readonly'})
    )

    port_list = forms.MultipleChoiceField(
        label=_("Ports List"),
        widget=forms.SelectMultiple(
            attrs={'class': 'switchable', 'data-slug': 'slug-detacj-ports'}),
        help_text=_("Select one or more of the following attached ports")
    )

    def __init__(self, *args, **kwargs):

        super(DetachPortForm, self).__init__(*args, **kwargs)
        self.fields["port_list"].choices = kwargs["initial"]["ports"]

    def handle(self, request, data):
        # LOG.debug("DATA: %s %s", data, len(data["port_list"]))

        counter = 0

        for port in data["port_list"]:
            try:
                iotronic.detach_port(request, data["uuid"], port)

                message_text = "Detach port " + str(port) + " from board " + \
                               str(data["name"]) + " completed successfully"
                messages.success(request, _(message_text))

                if counter != len(data["port_list"]) - 1:
                    counter += 1
                else:
                    return True

            except Exception:
                message_text = "Unable to detach port " + str(port) + \
                               " from board " + str(data["name"])

                exceptions.handle(request, _(message_text))


class EnableWebServiceForm(forms.SelfHandlingForm):

    uuid = forms.CharField(label=_("Board ID"), widget=forms.HiddenInput)

    name = forms.CharField(
        label=_('Board Name'),
        widget=forms.TextInput(attrs={'readonly': 'readonly'})
    )

    dns = forms.CharField(label=_("Domain Name Server"))
    zone = forms.CharField(label=_("Zone"))
    email = forms.CharField(label=_("Email"))

    def __init__(self, *args, **kwargs):
        super(EnableWebServiceForm, self).__init__(*args, **kwargs)

    def handle(self, request, data):

        try:
            iotronic.webservice_enable(request, data["uuid"],
                                       data["dns"], data["zone"],
                                       data["email"])

            messages.success(request, _("Web Service enabled on board " +
                                        str(data["name"]) + "."))
            return True

        except Exception:
            message_text = "Unable to enable web service."
            exceptions.handle(request, _(message_text))


class DisableWebServiceForm(forms.SelfHandlingForm):

    uuid = forms.CharField(label=_("Board ID"), widget=forms.HiddenInput)

    name = forms.CharField(
        label=_('Board Name'),
        widget=forms.TextInput(attrs={'readonly': 'readonly'})
    )

    def __init__(self, *args, **kwargs):
        super(DisableWebServiceForm, self).__init__(*args, **kwargs)

    def handle(self, request, data):

        try:
            iotronic.webservice_disable(request, data["uuid"])

            messages.success(request, _("Web Service disabled on board " +
                                        str(data["name"]) + "."))
            return True

        except Exception:
            message_text = "Unable to disable web service."
            exceptions.handle(request, _(message_text))


class RemovePluginsForm(forms.SelfHandlingForm):

    uuid = forms.CharField(label=_("Board ID"), widget=forms.HiddenInput)

    name = forms.CharField(
        label=_('Board Name'),
        widget=forms.TextInput(attrs={'readonly': 'readonly'})
    )

    plugin_list = forms.MultipleChoiceField(
        label=_("Plugins List"),
        widget=forms.SelectMultiple(
            attrs={'class': 'switchable', 'data-slug': 'slug-remove-plugins'}),
        help_text=_("Select plugins in this pool ")
    )

    def __init__(self, *args, **kwargs):

        super(RemovePluginsForm, self).__init__(*args, **kwargs)
        # input=kwargs.get('initial',{})
        self.fields["plugin_list"].choices = kwargs["initial"]["plugin_list"]

    def handle(self, request, data):

        counter = 0

        for plugin in data["plugin_list"]:
            for key, value in self.fields["plugin_list"].choices:
                if key == plugin:

                    try:
                        iotronic.plugin_remove(request, data["uuid"], key)

                        message_text = "Plugin " + str(value) + \
                                       " removed successfully."
                        messages.success(request, _(message_text))

                        if counter != len(data["plugin_list"]) - 1:
                            counter += 1
                        else:
                            return True

                    except Exception:
                        message_text = "Unable to remove plugin " \
                                       + str(value) + "."
                        exceptions.handle(request, _(message_text))

                    break
