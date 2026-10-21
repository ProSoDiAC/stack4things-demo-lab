# -*- coding: utf-8 -*-

from django.utils.translation import ugettext_lazy as _

import horizon

from iotronic_ui.iot import dashboard


class IotWot(horizon.Panel):
    name = _("Web Services")
    slug = "iot_wot"


dashboard.Iot.register(IotWot)
