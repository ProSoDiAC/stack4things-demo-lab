# Lab extension - IoT Metrics panel in IoT sidebar.

PANEL = 'iot_metrics'
PANEL_DASHBOARD = 'iot'
PANEL_GROUP = ''
DEFAULT_PANEL = ''

ADD_INSTALLED_APPS = [
    'iotronic_ui_lab.iot.iot_metrics',
]

ADD_PANEL = 'iotronic_ui_lab.iot.iot_metrics.panel.IotMetrics'
