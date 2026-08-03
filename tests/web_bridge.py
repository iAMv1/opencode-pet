"""Real-bridge test helpers: seed a realistic pet data dir and boot the REAL
desktop server (`desktop/main.py --web`) as a subprocess, then drive it over
its localhost RPC — the same page, backend and data files the desktop app uses.

The mock (`tests/make_mock_page.py`) exercises the UI with fake data; these
helpers prove the REAL path works: real app.html + real ControlApi + real
config.json/status-*.json/wellbeing.json/activity logs.
"""

import json
import os
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAIN = os.path.join(ROOT, "desktop", "main.py")

ACTIVE_STATES = ("busy", "thinking", "error", "retry", "celebrating")


def write_json(path, obj):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh)


def seed_pet_dir(d):
    """Create a realistic ~/.opencode/pet-style directory. Returns the path."""
    os.makedirs(d, exist_ok=True)
    now_ms = int(time.time() * 1000)

    # Live sessions exactly as the server plugin writes them. Ordering matters:
    # get_config()['state'] reads the NEWEST session, so sess-1 (busy) must be
    # the most recent.
    #
    # Fresh sessions get FUTURE timestamps (now + 10 min). Staleness is a
    # wall-clock boundary (STALE_MS = 25s) and a browser run happens SECONDS
    # after seeding — an updatedAt near `now` tips the session over the line
    # mid-test under load (caught by the double-run). These integration tests
    # verify the real pipeline, not staleness timing (that's unit-tested with
    # controlled clocks), so fresh must mean "stays fresh for the whole run".
    fresh = now_ms + 600000
    sessions = [
        {"sessionID": "sess-1", "state": "busy", "title": "Refactor engine",
         "toolLabel": "edit main.py (12 chars)", "message": "Rewriting the state machine",
         "direction": "right", "cwd": "C:\\proj\\opencode-pet", "updatedAt": fresh},
        {"sessionID": "sess-3", "state": "error", "title": "Sprite pipeline",
         "toolLabel": "bash", "message": "Something went wrong", "direction": "right",
         "cwd": "C:\\proj\\sprites", "updatedAt": fresh - 1000},
        {"sessionID": "sess-2", "state": "thinking", "title": "Debug watcher thread",
         "toolLabel": "", "message": "Thread is deadlocking on", "direction": "left",
         "cwd": "C:\\proj\\watcher", "updatedAt": fresh - 2000},
        {"sessionID": "sess-4", "state": "celebrating", "title": "UI polish",
         "toolLabel": "", "message": "Done!", "direction": "left",
         "cwd": "C:\\proj\\ui", "updatedAt": fresh - 3000},
        # idle + old: real ControlApi.get_sessions() drops idle AND stale
        {"sessionID": "sess-5", "state": "idle", "title": "Docs",
         "toolLabel": "", "message": "", "direction": "left",
         "cwd": "C:\\proj\\docs", "updatedAt": fresh - 4000},
        {"sessionID": "sess-6", "state": "busy", "title": "Dead session",
         "toolLabel": "", "message": "", "direction": "right",
         "cwd": "C:\\proj\\old", "updatedAt": now_ms - 1200000},  # stale (>25s)
    ]
    for s in sessions:
        write_json(os.path.join(d, "status-%s.json" % s["sessionID"]), s)

    write_json(os.path.join(d, "config.json"),
               {"petIdx": 1, "walk": 70, "alwaysOnTop": True,
                "petVisible": True, "breakMin": 50,
                "xp": 64, "level": 7, "mood": "happy"})

    today = time.strftime("%Y-%m-%d")
    hist = {}
    app_hist = {}
    hour_hist = {}
    week_vals = [7200, 5400, 3600, 8100, 0, 4500, 3600]
    for i in range(90):  # 90-day trail for the focus-calendar heatmap
        day = time.strftime("%Y-%m-%d", time.localtime(time.time() - (89 - i) * 86400))
        if i >= 83:
            # current week: the exact 7-day rhythm the older tests assert on
            secs = week_vals[6 - (89 - i)]
        elif i >= 76:
            secs = 0  # prior week empty -> "first week" semantics preserved
        else:
            secs = max(0, (i * 137 + 900) % 7200)  # older synthetic trail
        hist[day] = secs
        if secs > 0:
            app_hist[day] = {"VS Code": secs * 6 // 10,
                             "Terminal": secs * 3 // 10,
                             "Chrome": secs // 10}
            hour_hist[day] = {9: secs // 4, 10: secs // 2, 14: secs // 8}
    write_json(os.path.join(d, "wellbeing.json"),
               {"date": today,
                "apps": {"VS Code": 7200, "Terminal": 3600, "Chrome": 900, "Explorer": 300},
                "history": hist, "appHistory": app_hist,
                "hourToday": {9: 1800, 10: 3600, 14: 720},
                "hourHistory": {day: {9: 1800, 10: 2700, 14: 900}
                                 for day in hist}})

    # activity log for the CURRENT pet (petIdx 1 -> charmander)
    rows = [
        {"t": time.time() - 5, "kind": "state", "state": "busy"},
        {"t": time.time() - 20, "kind": "tool", "tool": "edit main.py"},
        {"t": time.time() - 40, "kind": "state", "state": "thinking"},
        {"t": time.time() - 90, "kind": "active", "app": "VS Code"},
        {"t": time.time() - 120, "kind": "poke"},
        {"t": time.time() - 180, "kind": "break", "mins": 52},
        {"t": time.time() - 300, "kind": "levelUp", "level": 7},
        {"t": time.time() - 800, "kind": "focusDone", "minutes": 25},
        {"t": time.time() - 2000, "kind": "state", "state": "success"},
    ]
    with open(os.path.join(d, "activity-charmander.jsonl"), "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")

    return d


def start_server(pet_dir, extra_args=None, timeout=30):
    """Boot the REAL desktop server. Returns (proc, port, base_url)."""
    cmd = [sys.executable, MAIN, "--web", "--pet-dir", pet_dir]
    if extra_args:
        cmd += extra_args
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, cwd=ROOT)
    port = None
    deadline = time.time() + timeout
    line = ""
    while time.time() < deadline:
        line = proc.stdout.readline().strip()
        if line.startswith("OPENCODE_PET_WEB_PORT="):
            port = int(line.split("=", 1)[1])
            break
        if proc.poll() is not None:
            raise RuntimeError("server died: %r" % line)
    if port is None:
        proc.kill()
        raise RuntimeError("no port line from server; saw %r" % line)
    return proc, port, "http://127.0.0.1:%d" % port


def stop_server(proc):
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def rpc(base_url, method, *args, timeout=15):
    """Call one real RPC method over the fetch bridge. Returns the result."""
    body = json.dumps({"method": method, "args": list(args)}).encode("utf-8")
    req = urllib.request.Request(base_url + "/rpc", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        out = json.loads(resp.read().decode("utf-8"))
    assert out.get("ok"), "rpc %s failed: %s" % (method, out)
    return out["result"]


def fetch_page(base_url, timeout=15):
    """GET the real served dashboard HTML."""
    with urllib.request.urlopen(base_url + "/", timeout=timeout) as resp:
        return resp.read().decode("utf-8")
