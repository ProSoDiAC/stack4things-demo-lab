#!/usr/bin/env python3
"""Fleet-panel workflow: create a board, provision a Lightning-Rod for it through lr-log-proxy,
wait for it to come online, delete the (online) board — exercises the conductor delete patch — and clean up."""
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import bootstrap as b  # noqa: E402

PROXY = "http://127.0.0.1:8092"
NAME, CODE = "board-ci-test", "board-ci-test-lab"
container = None


def proxy(path, payload):
    req = urllib.request.Request(PROXY + path, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        return json.loads(urllib.request.urlopen(req, timeout=300).read())
    except urllib.error.HTTPError as exc:
        return json.loads(exc.read())


def main() -> int:
    global container
    token = b.keystone_token()
    board = b.ensure_board(token, NAME, CODE)
    res = proxy("/provision", {"board_name": NAME, "registration_code": CODE})
    print("provision:", {k: res.get(k) for k in ("ok", "container", "operative", "error")})
    if not res.get("ok"):
        return 1
    container = res["container"]
    for _ in range(40):
        status = next(x for x in b.list_boards(token) if x["name"] == NAME)["status"]
        if status == "online":
            break
        time.sleep(5)
    print("board status:", status)
    if status != "online":
        return 1
    code, _ = b.api(token, "DELETE", "/v1/boards/" + board["uuid"])
    print("DELETE online board -> HTTP", code)
    gone = not any(x["name"] == NAME for x in b.list_boards(token))
    print("board removed:", gone)
    return 0 if code == 204 and gone else 1


if __name__ == "__main__":
    rc = 1
    try:
        rc = main()
    finally:
        if container:
            proxy("/deprovision", {"container": container})
        try:
            t = b.keystone_token()
            for x in b.list_boards(t):
                if x["name"] == NAME:
                    b.api(t, "DELETE", "/v1/boards/" + x["uuid"])
        except Exception:
            pass
    print("RESULT:", "PASS" if rc == 0 else "FAIL")
    sys.exit(rc)
