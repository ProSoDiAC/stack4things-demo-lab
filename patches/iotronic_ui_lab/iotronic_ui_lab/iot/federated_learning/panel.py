# -*- coding: utf-8 -*-
# Licensed under the Apache License, Version 2.0 (the "License").

from django.utils.translation import ugettext_lazy as _

import horizon

from iotronic_ui.iot import dashboard


class FederatedLearning(horizon.Panel):
    name = _("Federated Learning")
    slug = "federated_learning"


dashboard.Iot.register(FederatedLearning)
