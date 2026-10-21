# Lab IoT dashboard panel order (sidebar).
# Mounted over /opt/build/iotronic-ui/iotronic_ui/iot/dashboard.py
from django.utils.translation import ugettext_lazy as _
import horizon


class Iot(horizon.Dashboard):
    name = _("IoT")
    slug = "iot"
    panels = (
        "boards",
        "plugins",
        "services",
        "fleets",
        "iot_wot",
        "iot_metrics",
        "federated_learning",
    )
    default_panel = "boards"


horizon.register(Iot)
