# Stub: empty webservices panel replaced by iot_wot (Web Services).
from django.utils.translation import ugettext_lazy as _
import horizon
from iotronic_ui.iot import dashboard

class Webservices(horizon.Panel):
    name = _("Web Services")
    slug = "webservices"

# Intentionally NOT registering: dashboard.Iot.register(Webservices)
# The iot_wot panel replaces this entry in the menu.
