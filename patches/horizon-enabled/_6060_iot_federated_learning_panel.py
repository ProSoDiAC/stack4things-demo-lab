# Lab extension - Federated Learning panel in IoT sidebar.

PANEL = 'federated_learning'
PANEL_DASHBOARD = 'iot'
PANEL_GROUP = ''
DEFAULT_PANEL = ''

ADD_INSTALLED_APPS = [
    'iotronic_ui_lab.iot.federated_learning',
]

ADD_PANEL = 'iotronic_ui_lab.iot.federated_learning.panel.FederatedLearning'
