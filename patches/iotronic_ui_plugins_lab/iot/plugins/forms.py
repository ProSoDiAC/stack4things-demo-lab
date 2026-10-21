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

import cPickle
import json
import logging

from django.utils.translation import ugettext_lazy as _

from horizon import exceptions
# START FROM HERE !!!!!!! openstack_dashboard/api/nova.py
# from iotronicclient.common.apiclient import exceptions as iot_exceptions

from horizon import forms
from horizon import messages

from openstack_dashboard.api import iotronic
from openstack_dashboard import policy

try:
    from iotronic_ui_lab.iot.iot_metrics import metrics_helpers
except ImportError:
    metrics_helpers = None

LOG = logging.getLogger(__name__)


def _default_measurement_for_plugin(plugin_name):
    name = (plugin_name or "").lower()
    if "environment" in name or "env" in name or "ch15" in name:
        return "environmental_data"
    return "iot_stream"


def _plugin_needs_cloud_metrics(plugin_name):
    """Lab plugins that are useless without metrics gateway credentials."""
    name = (plugin_name or "").lower()
    return any(
        key in name
        for key in ("environment", "environmental", "enviromental", "ch15", "metrics")
    ) or name in ("env", "environmentaldemo")


def _merge_cloud_metrics_params(request, board_uuid, board_name, plugin_uuid, plugin_name, params):
    if metrics_helpers is None:
        return params
    payload = {
        "board_uuid": board_uuid,
        "board_name": board_name,
        "plugin_uuid": plugin_uuid,
        "plugin_name": plugin_name,
        "measurement": _default_measurement_for_plugin(plugin_name),
        "field_schema": ["Temperature", "Humidity", "PM10", "PM25"],
    }
    result = metrics_helpers.provision_stream(payload)
    merged = dict(params or {})
    merged.update(
        {
            "metrics_url": result.get("metrics_url"),
            "metrics_token": result.get("metrics_token"),
            "metrics_stream": result.get("metrics_stream"),
        }
    )
    return merged


class CreatePluginForm(forms.SelfHandlingForm):
    name = forms.CharField(
        label=_("Plugin Name"),
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'my-plugin'}),
    )

    """
    public = forms.ChoiceField(
        label=_("Public"),
        choices =[('false', _('False')), ('true', _('True'))],
        widget=forms.Select(
            attrs={'class': 'switchable', 'data-slug': 'slug-public'},
        )
    )
    """

    public = forms.BooleanField(label=_("Public"), required=False)
    callable = forms.BooleanField(
        label=_("Callable (synchronous)"),
        required=False,
        initial=True,
        help_text=_(
            "ON = sync: Use Call (PluginCall RPC). Implement run() once and "
            "self.q_result.put(result). "
            "OFF = async: Use Start/Stop (PluginStart/PluginStop). Loop with "
            "while self._is_running in run(). "
            "Do not implement methods named PluginStart/PluginCall/PluginStop."
        ),
    )

    code = forms.CharField(
        label=_("Code"),
        widget=forms.Textarea(
            attrs={
                'class': 'plugin-ide-code-source form-control',
                'rows': 18,
                'style': 'font-family: monospace; font-size: 13px;',
            })
    )

    parameters = forms.CharField(
        label=_("Parameters"),
        required=False,
        widget=forms.Textarea(
            attrs={
                'class': 'plugin-ide-params-source form-control',
                'rows': 6,
                'style': 'font-family: monospace; font-size: 12px;',
            }),
        help_text=_("Default plugin parameters (JSON object)")
    )

    def handle(self, request, data):

        if not data["parameters"]:
            data["parameters"] = {}
        else:
            data["parameters"] = json.loads(data["parameters"])

        try:
            iotronic.plugin_create(request, data["name"],
                                   data["public"], data["callable"],
                                   data["code"], data["parameters"])

            messages.success(request, _("Plugin created successfully."))

            return True
        # except iot_exceptions.ClientException:
        except Exception:
            # LOG.debug("API REQ EXC: %s", request)
            # LOG.debug("API REQ (DICT): %s", exceptions.__dict__)
            exceptions.handle(request, _('Unable to create plugin.'))


class InjectPluginForm(forms.SelfHandlingForm):

    uuid = forms.CharField(label=_("Plugin ID"), widget=forms.HiddenInput)

    name = forms.CharField(
        label=_('Plugin Name'),
        widget=forms.TextInput(attrs={'readonly': 'readonly'})
    )

    onboot = forms.BooleanField(label=_("On Boot"), required=False)

    board_list = forms.MultipleChoiceField(
        label=_("Boards List"),
        widget=forms.SelectMultiple(
            attrs={'class': 'switchable', 'data-slug': 'slug-inject-plugin'}),
        help_text=_("Select boards in this pool ")
    )

    def __init__(self, *args, **kwargs):

        super(InjectPluginForm, self).__init__(*args, **kwargs)
        # input=kwargs.get('initial',{})

        boardslist_length = len(kwargs["initial"]["board_list"])

        self.fields["board_list"].choices = kwargs["initial"]["board_list"]
        self.fields["board_list"].max_length = boardslist_length

    def handle(self, request, data):

        counter = 0

        for board in data["board_list"]:
            for key, value in self.fields["board_list"].choices:
                if key == board:

                    try:
                        inject = iotronic.plugin_inject(request, key,
                                                        data["uuid"],
                                                        data["onboot"])
                        # LOG.debug("API: %s %s", plugin, request)
                        message_text = inject
                        messages.success(request, _(message_text))

                        if counter != len(data["board_list"]) - 1:
                            counter += 1
                        else:
                            return True

                    except Exception:
                        message_text = "Unable to inject plugin on board " \
                                       + str(value) + "."
                        exceptions.handle(request, _(message_text))

                    break


class StartPluginForm(forms.SelfHandlingForm):

    uuid = forms.CharField(label=_("Plugin ID"), widget=forms.HiddenInput)

    name = forms.CharField(
        label=_('Plugin Name'),
        widget=forms.TextInput(attrs={'readonly': 'readonly'})
    )

    board_list = forms.MultipleChoiceField(
        label=_("Boards List"),
        widget=forms.SelectMultiple(
            attrs={'class': 'switchable',
                   'data-slug': 'slug-start-boards'}),
        help_text=_("Select boards in this pool ")
    )

    parameters = forms.CharField(
        label=_("Parameters"),
        required=False,
        widget=forms.Textarea(
            attrs={'class': 'switchable',
                   'data-slug': 'slug-startplugin-json'}),
        help_text=_("Plugin parameters")
    )

    enable_cloud_metrics = forms.BooleanField(
        label=_("Enable cloud metrics (auto-provision on start)"),
        required=False,
        initial=True,
        help_text=_(
            "Provision a metrics stream and inject gateway URL/token into start "
            "parameters. Enabled by default; required for EnvironmentalDemo."
        ),
    )

    def __init__(self, *args, **kwargs):

        super(StartPluginForm, self).__init__(*args, **kwargs)
        # input=kwargs.get('initial',{})

        boardslist_length = len(kwargs["initial"]["board_list"])

        self.fields["board_list"].choices = kwargs["initial"]["board_list"]
        self.fields["board_list"].max_length = boardslist_length
        # Always show checked unless explicitly posted unchecked (env plugins ignore uncheck).
        if "enable_cloud_metrics" not in self.data:
            self.fields["enable_cloud_metrics"].initial = True
        plugin_name = kwargs.get("initial", {}).get("name") or ""
        if _plugin_needs_cloud_metrics(plugin_name):
            self.fields["enable_cloud_metrics"].initial = True
            self.fields["enable_cloud_metrics"].help_text = _(
                "Required for this plugin: stream credentials are always injected on start."
            )

    def handle(self, request, data):

        counter = 0

        if not data["parameters"]:
            data["parameters"] = {}
        else:
            data["parameters"] = json.loads(data["parameters"])

        plugin_name = data.get("name") or ""
        force_metrics = _plugin_needs_cloud_metrics(plugin_name)
        want_metrics = bool(data.get("enable_cloud_metrics")) or force_metrics

        for board in data["board_list"]:
            for key, value in self.fields["board_list"].choices:
                if key == board:

                    try:
                        params = dict(data["parameters"])
                        if want_metrics:
                            try:
                                params = _merge_cloud_metrics_params(
                                    request,
                                    key,
                                    unicode(value),
                                    data["uuid"],
                                    plugin_name,
                                    params,
                                )
                            except Exception as exc:
                                LOG.warning("cloud metrics provision failed: %s", exc)
                                if force_metrics:
                                    messages.error(
                                        request,
                                        _(
                                            "Cannot start {0} on {1}: cloud metrics "
                                            "required but provision failed ({2})."
                                        ).format(
                                            plugin_name or "plugin",
                                            value,
                                            unicode(exc)[:120],
                                        ),
                                    )
                                    continue
                                messages.warning(
                                    request,
                                    _("Cloud metrics provision failed for {0}: {1}").format(
                                        value, unicode(exc)[:120]
                                    ),
                                )

                        if force_metrics and not (
                            params.get("metrics_url") and params.get("metrics_token")
                        ):
                            messages.error(
                                request,
                                _(
                                    "Cannot start {0} without metrics_url/token "
                                    "(Enable cloud metrics)."
                                ).format(plugin_name or "plugin"),
                            )
                            continue

                        action = iotronic.plugin_action(request, key,
                                                        data["uuid"],
                                                        "PluginStart",
                                                        params)
                        # LOG.debug("API: %s %s", plugin, request)
                        message_text = action
                        messages.success(request, _(message_text))

                        if counter != len(data["board_list"]) - 1:
                            counter += 1
                        else:
                            return True

                    except Exception:
                        message_text = "Unable to start plugin on board " \
                                       + str(value) + "."
                        exceptions.handle(request, _(message_text))

                    break


class StopPluginForm(forms.SelfHandlingForm):

    uuid = forms.CharField(label=_("Plugin ID"), widget=forms.HiddenInput)

    name = forms.CharField(
        label=_('Plugin Name'),
        widget=forms.TextInput(attrs={'readonly': 'readonly'})
    )

    delay = forms.IntegerField(
        label=_("Delay in secs"),
        required=False,
        help_text=_("OPTIONAL: seconds to wait before stopping the plugin")
    )

    board_list = forms.MultipleChoiceField(
        label=_("Boards List"),
        widget=forms.SelectMultiple(
            attrs={'class': 'switchable', 'data-slug': 'slug-stop-boards'}),
        help_text=_("Select boards in this pool ")
    )

    def __init__(self, *args, **kwargs):

        super(StopPluginForm, self).__init__(*args, **kwargs)
        # input=kwargs.get('initial',{})

        boardslist_length = len(kwargs["initial"]["board_list"])

        self.fields["board_list"].choices = kwargs["initial"]["board_list"]
        self.fields["board_list"].max_length = boardslist_length

    def handle(self, request, data):

        counter = 0

        if not data["delay"]:
            data["delay"] = {}
        else:
            data["delay"] = {"delay": data["delay"]}

        for board in data["board_list"]:
            for key, value in self.fields["board_list"].choices:
                if key == board:

                    try:
                        action = iotronic.plugin_action(request, key,
                                                        data["uuid"],
                                                        "PluginStop",
                                                        data["delay"])
                        # LOG.debug("API: %s %s", plugin, request)
                        message_text = action
                        messages.success(request, _(message_text))

                        if counter != len(data["board_list"]) - 1:
                            counter += 1
                        else:
                            return True

                    except Exception:
                        message_text = "Unable to stop plugin on board " \
                                       + str(value) + "."
                        exceptions.handle(request, _(message_text))

                    break


class CallPluginForm(forms.SelfHandlingForm):

    uuid = forms.CharField(label=_("Plugin ID"), widget=forms.HiddenInput)

    name = forms.CharField(
        label=_('Plugin Name'),
        widget=forms.TextInput(attrs={'readonly': 'readonly'})
    )

    board_list = forms.MultipleChoiceField(
        label=_("Boards List"),
        widget=forms.SelectMultiple(
            attrs={'class': 'switchable', 'data-slug': 'slug-call-boards'}),
        help_text=_("Select boards in this pool ")
    )

    parameters = forms.CharField(
        label=_("Parameters"),
        required=False,
        widget=forms.Textarea(
            attrs={'class': 'switchable',
                   'data-slug': 'slug-callplugin-json'}),
        help_text=_("Plugin parameters")
    )

    def __init__(self, *args, **kwargs):

        super(CallPluginForm, self).__init__(*args, **kwargs)
        # input=kwargs.get('initial',{})

        boardslist_length = len(kwargs["initial"]["board_list"])

        self.fields["board_list"].choices = kwargs["initial"]["board_list"]
        self.fields["board_list"].max_length = boardslist_length

    def handle(self, request, data):

        counter = 0

        if not data["parameters"]:
            data["parameters"] = {}
        else:
            data["parameters"] = json.loads(data["parameters"])

        for board in data["board_list"]:
            for key, value in self.fields["board_list"].choices:
                if key == board:

                    try:
                        action = iotronic.plugin_action(request, key,
                                                        data["uuid"],
                                                        "PluginCall",
                                                        data["parameters"])

                        message_text = action
                        messages.success(request, _(message_text))

                        if counter != len(data["board_list"]) - 1:
                            counter += 1
                        else:
                            return True

                    except Exception:
                        message_text = "Unable to call plugin on board " \
                                       + str(value) + "."
                        exceptions.handle(request, _(message_text))

                    break


class RemovePluginForm(forms.SelfHandlingForm):

    uuid = forms.CharField(label=_("Plugin ID"), widget=forms.HiddenInput)

    name = forms.CharField(
        label=_('Plugin Name'),
        widget=forms.TextInput(attrs={'readonly': 'readonly'})
    )

    board_list = forms.MultipleChoiceField(
        label=_("Boards List"),
        widget=forms.SelectMultiple(
            attrs={'class': 'switchable', 'data-slug': 'slug-remove-boards'}),
        help_text=_("Select boards in this pool ")
    )

    def __init__(self, *args, **kwargs):

        super(RemovePluginForm, self).__init__(*args, **kwargs)
        # input=kwargs.get('initial',{})

        boardslist_length = len(kwargs["initial"]["board_list"])

        self.fields["board_list"].choices = kwargs["initial"]["board_list"]
        self.fields["board_list"].max_length = boardslist_length

    def handle(self, request, data):

        counter = 0

        for board in data["board_list"]:
            for key, value in self.fields["board_list"].choices:
                if key == board:

                    try:
                        iotronic.plugin_remove(request,
                                               key,
                                               data["uuid"])
                        # LOG.debug("API: %s %s", plugin, request)
                        message_text = "Plugin removed successfully from" \
                                       + " board " + str(value) + "."
                        messages.success(request, _(message_text))

                        if counter != len(data["board_list"]) - 1:
                            counter += 1
                        else:
                            return True

                    except Exception:
                        message_text = "Unable to remove plugin from board " \
                                       + str(value) + "."
                        exceptions.handle(request, _(message_text))

                    break


class UpdatePluginForm(forms.SelfHandlingForm):

    uuid = forms.CharField(label=_("Plugin ID"), widget=forms.HiddenInput)
    owner = forms.CharField(label=_("Owner"), widget=forms.HiddenInput)
    name = forms.CharField(
        label=_("Plugin Name"),
        widget=forms.TextInput(attrs={'class': 'form-control'}),
    )
    public = forms.BooleanField(label=_("Public"), required=False)
    callable = forms.BooleanField(
        label=_("Callable (synchronous)"),
        required=False,
        help_text=_(
            "ON = sync Call (PluginCall). OFF = async Start/Stop. "
            "Always implement run() on Worker(Plugin.Plugin)."
        ),
    )

    code = forms.CharField(
        label=_("Code"),
        widget=forms.Textarea(
            attrs={
                'class': 'plugin-ide-code-source form-control',
                'rows': 18,
                'style': 'font-family: monospace; font-size: 13px;',
            })
    )

    def __init__(self, *args, **kwargs):

        super(UpdatePluginForm, self).__init__(*args, **kwargs)

        # Admin
        if policy.check((("iot", "iot:update_plugins"),), self.request):
            pass

        # Admin_iot_project
        elif policy.check((("iot", "iot:update_project_plugins"),),
                          self.request):

            if self.request.user.id != kwargs["initial"]["owner"]:
                self.fields["name"].widget.attrs = {'readonly': 'readonly', 'class': 'form-control'}
                self.fields["public"].widget.attrs = {'disabled': 'disabled'}
                self.fields["callable"].widget.attrs = {'disabled': 'disabled'}
                self.fields["code"].widget.attrs = {'readonly': 'readonly'}

        # Other users
        else:
            if self.request.user.id != kwargs["initial"]["owner"]:
                self.fields["name"].widget.attrs = {'readonly': 'readonly', 'class': 'form-control'}
                self.fields["public"].widget.attrs = {'disabled': 'disabled'}
                self.fields["callable"].widget.attrs = {'disabled': 'disabled'}
                self.fields["code"].widget.attrs = {'readonly': 'readonly'}

    def handle(self, request, data):
        try:

            data["code"] = cPickle.dumps(str(data["code"]))

            iotronic.plugin_update(request, data["uuid"],
                                   {"name": data["name"],
                                    "public": data["public"],
                                    "callable": data["callable"],
                                    "code": data["code"]})

            messages.success(request, _("Plugin " + str(data["name"]) +
                                        " updated successfully."))
            return True

        except Exception:
            exceptions.handle(request, _('Unable to update plugin.'))
