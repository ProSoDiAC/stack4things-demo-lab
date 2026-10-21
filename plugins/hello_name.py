from iotronic_lightningrod.modules.plugins import Plugin
from oslo_log import log as logging

LOG = logging.getLogger(__name__)


class Worker(Plugin.Plugin):
    """HelloNamePlugin — LR 0.4.17 requires class name Worker."""

    def __init__(self, uuid, name, q_result, params=None):
        super(Worker, self).__init__(uuid, name, q_result, params)

    def run(self):
        person_name = self.params.get('name', 'User')
        message = f"Hello {person_name}"
        LOG.info(message)
        self.q_result.put(message)
