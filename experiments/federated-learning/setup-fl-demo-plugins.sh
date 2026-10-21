#!/usr/bin/env bash
# Create FL client plugins (heart + PM) and inject heart on online boards (Ch.19 default).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PLUGIN="${ROOT}/experiments/federated-learning/fl_client_plugin.py"
DEFAULT_PLUGIN="${FL_DEFAULT_PLUGIN:-fl-client-heart}"

if [[ ! -f "$PLUGIN" ]]; then
  echo "Missing plugin source: $PLUGIN" >&2
  exit 1
fi

echo "=== FL lab plugins (fl-client-heart, fl-client-pm) ==="

docker exec iotronic-ui python2.7 -c "
import cPickle, json, urllib2
PLUGIN_PATH = '/opt/fl_lab/fl_client_plugin.py'
NAMES = ['fl-client-heart', 'fl-client-pm']
DEFAULT = '${DEFAULT_PLUGIN}'
CSV = {
    'fl-client-heart': {
        'board-alpha': '/opt/fl/heart_1.csv',
        'board-beta': '/opt/fl/heart_2.csv',
        'board-gamma': '/opt/fl/heart_3.csv',
    },
    'fl-client-pm': {
        'board-alpha': '/opt/fl/machine_1.csv',
        'board-beta': '/opt/fl/machine_2.csv',
        'board-gamma': '/opt/fl/machine_3.csv',
    },
}
body = json.dumps({'auth': {'identity': {'methods': ['password'], 'password': {'user': {'name': 'admin', 'domain': {'name': 'Default'}, 'password': 's4t'}}}, 'scope': {'project': {'name': 'admin', 'domain': {'name': 'Default'}}}}})
r = urllib2.urlopen(urllib2.Request('http://keystone:5000/v3/auth/tokens', body, {'Content-Type': 'application/json'}))
token = r.info().get('X-Subject-Token')
from iotronicclient.v1 import client
c = client.Client(token=token, endpoint='http://iotronic-conductor:8812/v1/')
code = open(PLUGIN_PATH).read().encode('ascii', 'replace').decode('ascii')
pickled = cPickle.dumps(str(code))
plugins = dict((p.name, p.uuid) for p in c.plugin.list(all_plugins=True))
for name in NAMES:
    if name in plugins:
        c.plugin.update(plugins[name], {'name': name, 'public': True, 'callable': False, 'code': pickled})
        print('[update]', name)
    else:
        p = c.plugin.create(name=name, public=True, callable=False, code=code, parameters={})
        plugins[name] = p.uuid
        print('[create]', name, p.uuid[:8])
legacy = 'fl-client'
if legacy in plugins:
    legacy_id = plugins[legacy]
    boards = dict((b.name, b.uuid) for b in c.board.list())
    for board_name, board_id in boards.items():
        try:
            on = c.plugin_injection.plugins_on_board(board_id)
            for inj in on:
                pid = inj._info.get('plugin') if hasattr(inj, '_info') else None
                if pid == legacy_id:
                    c.plugin_injection.plugin_remove(board_id, legacy_id)
                    print('[uninject]', legacy, 'from', board_name)
        except Exception as exc:
            print('[uninject-fail]', board_name, exc)
    try:
        c.plugin.delete(legacy_id)
        print('[delete]', legacy)
    except Exception as exc:
        print('[delete-fail]', legacy, exc)
boards = dict((b.name, b.uuid) for b in c.board.list() if b.status == 'online')
for board_name, board_id in sorted(boards.items()):
    for plugin_name in NAMES:
        inject_id = plugins.get(plugin_name)
        if not inject_id:
            print('[skip]', plugin_name, 'missing')
            continue
        try:
            c.plugin_injection.plugin_inject(board_id, inject_id, False)
            csv_hint = CSV.get(plugin_name, {}).get(board_name, 'default')
            print('[inject]', plugin_name, '->', board_name, '(csv', csv_hint + ')')
        except Exception as exc:
            print('[inject-fail]', board_name, plugin_name, exc)
print('OK — pick fl-client-pm in Horizon to switch to predictive maintenance')
"
