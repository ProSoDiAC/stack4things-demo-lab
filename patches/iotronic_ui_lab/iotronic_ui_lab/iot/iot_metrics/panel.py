# -*- coding: utf-8 -*-

from django.utils.translation import ugettext_lazy as _

import horizon

from iotronic_ui.iot import dashboard


class IotMetrics(horizon.Panel):
    name = _("Metrics")
    slug = "iot_metrics"


dashboard.Iot.register(IotMetrics)
