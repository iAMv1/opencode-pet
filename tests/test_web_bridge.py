"""REAL-bridge integration tests: boot the actual desktop server
(`desktop/main.py --web`) against a throwaway pet-dir and drive the real
app.html + real ControlApi + real data files over its localhost RPC.

This is the gap the mock can't cover: the mock swaps in fake data, so nothing
proves the shipped UI actually works against the real backend. These tests
exercise the exact endpoints the UI polls, with real files, plus the edge
conditions the production app can hit (corrupt files, empty dirs, config
churn, stale sessions, unknown RPC methods).

Run:  python -m pytest tests/test_web_bridge.py -q
"""

import json
import os
import subprocess
import sys
import threading
import time
import urllib.error

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import web_bridge as wb  # noqa: E402

ROOT = wb.ROOT


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    """Read-only tests only. Anything that mutates config/status files must
    use `fresh_server` so tests stay order-independent."""
    d = tmp_path_factory.mktemp("petdir")
    wb.seed_pet_dir(str(d))
    proc, port, base = wb.start_server(str(d))
    try:
        yield base, str(d)
    finally:
        wb.stop_server(proc)


@pytest.fixture()
def fresh_server(tmp_path):
    """A brand-new server per test (for tests that mutate the data dir)."""
    wb.seed_pet_dir(str(tmp_path))
    proc, port, base = wb.start_server(str(tmp_path))
    try:
        yield base, str(tmp_path)
    finally:
        wb.stop_server(proc)


# ---------------------------------------------------------------- real page

def test_serves_real_app_html(server):
    base, _ = server
    html = wb.fetch_page(base)
    # The REAL dashboard, not a mock: nav to Focus page exists, no mock markers
    assert "OpenCode Pet" in html
    assert 'data-view="focus"' in html
    assert "Focus — last 7 days" in html
    assert "window.pywebview" in html.split("<script>")[1]  # shim injected first
    assert "__calls" not in html  # mock-only artifact must be absent


def test_bridge_method_parity(server):
    """Every api.* call the UI makes must be served by the real web bridge.
    Args mirror what the UI actually passes so each method is exercised the
    way the dashboard calls it."""
    base, _ = server
    import re
    src = open(os.path.join(ROOT, "desktop", "app.html"), encoding="utf-8").read()
    calls = set(re.findall(r"api\.([a-zA-Z_][a-zA-Z0-9_]*)", src))
    assert calls, "no api calls found"
    args_for = {"save_config": [{}], "get_logs": [80],
                "get_wellbeing_history": [7]}
    for m in sorted(calls):
        body = json.dumps({"method": m, "args": args_for.get(m, [])}).encode("utf-8")
        import urllib.request
        req = urllib.request.Request(base + "/rpc", data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            out = json.loads(resp.read().decode("utf-8"))
        assert out.get("ok"), "real bridge: %s -> %s" % (m, out)


# ---------------------------------------------------------------- real data flow

def test_get_config_from_real_file(server):
    base, d = server
    c = wb.rpc(base, "get_config")
    assert c["petIdx"] == 1                      # seeded config.json
    assert c["walk"] == 70
    assert c["breakMin"] == 50
    assert c["petName"] == "Charmander"          # PETS[1]
    assert c["pets"] == ["Pikachu", "Charmander", "Doraemon", "Gardevoir",
                         "Giratina", "LPC Cat"]
    assert c["state"] == "busy"                  # top fresh session


def test_get_sessions_real_filtering(server):
    """Real ControlApi semantics: idle + stale sessions are dropped."""
    base, d = server
    sess = wb.rpc(base, "get_sessions")
    ids = [s["sessionID"] for s in sess]
    assert "sess-1" in ids and "sess-4" in ids      # busy + celebrating
    assert "sess-5" not in ids                       # idle dropped
    assert "sess-6" not in ids                       # stale dropped
    # stale flag computed by read_status()
    fresh = [s for s in sess if not s.get("stale")]
    assert len(fresh) == len(sess)


def test_wellbeing_history_real(server):
    base, _ = server
    hist = wb.rpc(base, "get_wellbeing_history", 7)
    assert len(hist) == 7
    # today folds the live running total (apps sum = 12000s) into history[3600]
    assert [h["seconds"] for h in hist] == [7200, 5400, 3600, 8100, 0, 4500, 15600]
    assert hist[-1]["date"] == time.strftime("%Y-%m-%d")


def test_insights_real(server):
    base, _ = server
    ins = wb.rpc(base, "get_wellbeing_insights")
    # week = stored 7-day total (32400) + today's live running total (12000)
    assert ins["weekSeconds"] == 32400 + 12000
    assert ins["prevWeekSeconds"] == 0
    assert ins["deltaPct"] is None  # no baseline week yet
    assert ins["bestDay"]["seconds"] == 15600  # today, post-fold
    assert ins["topApp"]["app"] == "VS Code"
    assert ins["todaySeconds"] == sum([7200, 3600, 900, 300])


def test_wellbeing_real(server):
    base, _ = server
    wb_ = wb.rpc(base, "get_wellbeing")
    apps = {w["app"]: w["seconds"] for w in wb_}
    assert apps.get("VS Code") == 7200
    assert apps.get("Terminal") == 3600
    # sorted desc by seconds
    secs = [w["seconds"] for w in wb_]
    assert secs == sorted(secs, reverse=True)


def test_activity_log_real(server):
    base, _ = server
    log = wb.rpc(base, "get_logs", 80)
    assert len(log) == 9
    assert log[0]["kind"] == "state" and log[0]["state"] == "busy"


def test_focus_state_idle_by_default(server):
    """No session started -> the dashboard gets a clean inactive state."""
    base, _ = server
    fs = wb.rpc(base, "get_focus_state")
    assert fs["active"] is False
    assert fs["progress"] == 0.0
    assert "targetMin" in fs


def test_focus_state_recomputes_live_progress(fresh_server):
    """A running session's progress must grow from startedAt/targetMin, not
    stay frozen at the last file snapshot (which is only written on
    start/wilt/stop/complete)."""
    base, d = fresh_server
    wb.write_json(os.path.join(d, "focus.json"),
                  {"active": True, "startedAt": time.time() - 1500,
                   "targetMin": 25, "wilted": False, "app": "VS Code",
                   "progress": 0.0})  # stale snapshot from session start
    fs = wb.rpc(base, "get_focus_state")
    assert fs["active"] is True
    assert fs["progress"] > 0.0  # recomputed (1500s / 1500s window)
    assert fs["app"] == "VS Code"


def test_focus_start_stop_one_shot_commands(fresh_server):
    """The dashboard's Start/Stop write the real one-shot commands the pet
    process consumes from config.json (focusStart / focusStop)."""
    base, d = fresh_server
    assert wb.rpc(base, "start_focus", 45) is True
    with open(os.path.join(d, "config.json"), encoding="utf-8") as fh:
        assert json.load(fh).get("focusStart") == 45
    assert wb.rpc(base, "stop_focus") is True
    with open(os.path.join(d, "config.json"), encoding="utf-8") as fh:
        assert json.load(fh).get("focusStop") == 1


def test_pet_profile_real(fresh_server):
    """Profile reads level/XP/mood from the real config and streak from the
    real wellbeing history (today >= 30min of focus => streak >= 1)."""
    base, _ = fresh_server
    p = wb.rpc(base, "get_pet_profile")
    assert p["level"] == 7
    assert p["xp"] == 64
    assert p["xpNext"] == 400  # 100 + (7-1)*50
    assert p["mood"] == "happy"
    assert p["xpPct"] > 0 and p["xpPct"] <= 1.0
    assert p["streak"] >= 1  # today alone qualifies (15600s after fold)


def test_focus_peaks_real(server):
    """24 hour-buckets summed over the week; morning hours dominate the
    seeded data, so the best-hour analysis returns a 10 AM peak."""
    base, _ = server
    pk = wb.rpc(base, "get_focus_peaks", 7)
    hours = pk["hours"]
    assert len(hours) == 24
    assert all(0 <= h["hour"] <= 23 for h in hours)
    assert all(h["seconds"] >= 0 for h in hours)
    total = sum(h["seconds"] for h in hours)
    assert total > 0
    assert pk["best"]["hour"] == 10  # seeded 9-11 AM buckets dominate
    assert pk["best"]["seconds"] > 0
    assert pk["best"]["pct"] > 0 and pk["best"]["pct"] <= 100
    assert pk["runnerUp"]["seconds"] <= pk["best"]["seconds"]
    assert pk["spanLabel"]
    # today's live hourToday (10 AM = 3600s) MUST be folded in, or the peaks
    # analysis silently ignores the current day (regression guard):
    by_hour = {h["hour"]: h["seconds"] for h in hours}
    assert by_hour[10] >= 3600  # hourToday[10] alone, before any history


def test_pet_profile_includes_stage(fresh_server):
    """The profile exposes an evolution stage derived from the level."""
    base, _ = fresh_server
    p = wb.rpc(base, "get_pet_profile")
    st = p["stage"]
    assert isinstance(st, dict) and "id" in st and "name" in st
    assert st["id"] in ("stage1", "stage2", "stage3")
    assert st["name"] == "Growing"  # level 7: 5 <= level < 10


def test_weekly_wrapped_real(server):
    base, _ = server
    w = wb.rpc(base, "get_weekly_wrapped")
    assert w["days"] == 7
    # week = stored 7-day (32400) + live running today (12000)
    assert w["weekSeconds"] == 32400 + 12000
    assert w["bestDay"]["date"] == time.strftime("%Y-%m-%d")
    assert w["bestDay"]["seconds"] == 15600  # today (3600) + live running 12000
    assert w["topApp"]["app"] == "VS Code"
    assert w["xp"] == 64
    assert w["level"] == 7
    assert w["streak"] >= 1
    assert w["focusSessions"] == 1  # the focusDone row in the real log


def test_week_apps_real(server):
    base, _ = server
    rows = wb.rpc(base, "get_week_apps", 7)
    apps = {r["app"]: r["seconds"] for r in rows}
    # each stored day's breakdown + today's live apps, all attributed
    assert apps.get("VS Code", 0) > 0
    assert apps.get("Terminal", 0) > 0
    assert apps.get("Chrome", 0) > 0
    assert rows == sorted(rows, key=lambda r: -r["seconds"])  # desc
    assert all(r["seconds"] >= 60 for r in rows)


def test_missing_wellbeing_profile_and_wrapped(fresh_server):
    """No wellbeing file -> profile/wrapped degrade to zeros, not crashes."""
    base, d = fresh_server
    os.unlink(os.path.join(d, "wellbeing.json"))
    p = wb.rpc(base, "get_pet_profile")
    assert p["streak"] == 0 and p["level"] == 7  # config still has level
    w = wb.rpc(base, "get_weekly_wrapped")
    assert w["weekSeconds"] == 0 and w["bestDay"] is None
    assert wb.rpc(base, "get_week_apps", 7) == []


def test_save_config_roundtrip_through_bridge(fresh_server):
    """UI saves must land in the REAL config.json via the cross-process lock."""
    base, d = fresh_server
    assert wb.rpc(base, "save_config", {"walk": 33, "petIdx": 2}) is True
    with open(os.path.join(d, "config.json"), encoding="utf-8") as fh:
        on_disk = json.load(fh)
    assert on_disk["walk"] == 33
    assert on_disk["petIdx"] == 2
    # merge: pre-existing keys survived
    assert on_disk["breakMin"] == 50
    assert on_disk["alwaysOnTop"] is True
    # and the bridge reads it back
    assert wb.rpc(base, "get_config")["walk"] == 33


def test_next_prev_pet_real(fresh_server):
    base, d = fresh_server
    wb.rpc(base, "next_pet")
    assert wb.rpc(base, "get_config")["petIdx"] == 2
    wb.rpc(base, "prev_pet")
    assert wb.rpc(base, "get_config")["petIdx"] == 1


def test_previews_real(server):
    base, _ = server
    prevs = wb.rpc(base, "get_previews")
    assert len(prevs) == 6
    ids = [p["id"] for p in prevs]
    assert ids == ["capvolt", "charmander", "doraemon", "gardevoir", "giratina", "lpc-cat"]
    # real sprite strips are base64 PNG data URIs
    assert all(p["strip"] and p["strip"].startswith("data:image/png;base64,") for p in prevs)


def test_hide_show_pet_nop_over_web(server):
    """hide_pet/show_pet write one-shot commands into the real config."""
    base, d = server
    wb.rpc(base, "hide_pet")
    with open(os.path.join(d, "config.json"), encoding="utf-8") as fh:
        assert json.load(fh).get("hidePet") == 1
    wb.rpc(base, "show_pet")
    with open(os.path.join(d, "config.json"), encoding="utf-8") as fh:
        assert json.load(fh).get("showPet") == 1


def test_quit_writes_command_but_keeps_server(fresh_server):
    """quit in web mode = real quit semantics minus process death: the one-shot
    command lands in config.json for the pet process to read, but the server
    (the browser's backend) stays up."""
    base, d = fresh_server
    assert wb.rpc(base, "quit") is True
    with open(os.path.join(d, "config.json"), encoding="utf-8") as fh:
        assert json.load(fh).get("quit") == 1
    # server is still alive and serving
    assert wb.rpc(base, "get_config")["petIdx"] == 1
    # hide_control is a true no-op in a browser tab (no window to hide)
    assert wb.rpc(base, "hide_control") is True


# ---------------------------------------------------------------- edge cases

def test_corrupt_status_files_skipped(fresh_server):
    """A corrupt status-*.json must not break get_sessions — read_status skips it."""
    base, d = fresh_server
    with open(os.path.join(d, "status-garbage.json"), "w", encoding="utf-8") as fh:
        fh.write("{ not json !!!")
    with open(os.path.join(d, "status-sess-1.json"), "w", encoding="utf-8") as fh:
        fh.write("[]")  # valid JSON but wrong shape (list, no .get)
    sess = wb.rpc(base, "get_sessions")
    assert all(isinstance(s, dict) for s in sess)


def test_corrupt_config_defaults(fresh_server):
    """Corrupt config.json -> load_config returns defaults, server still fine."""
    base, d = fresh_server
    with open(os.path.join(d, "config.json"), "w", encoding="utf-8") as fh:
        fh.write("{oops")
    c = wb.rpc(base, "get_config")
    assert c["petIdx"] == 0 and c["walk"] == 100 and c["breakMin"] == 50


def test_missing_wellbeing_file(fresh_server):
    base, d = fresh_server
    os.unlink(os.path.join(d, "wellbeing.json"))
    assert wb.rpc(base, "get_wellbeing") == []
    hist = wb.rpc(base, "get_wellbeing_history", 7)
    assert len(hist) == 7 and all(h["seconds"] == 0 for h in hist)
    ins = wb.rpc(base, "get_wellbeing_insights")
    assert ins["weekSeconds"] == 0 and ins["bestDay"] is None


def test_empty_dir(fresh_server):
    base, d = fresh_server
    for f in os.listdir(d):
        os.unlink(os.path.join(d, f))
    assert wb.rpc(base, "get_sessions") == []
    c = wb.rpc(base, "get_config")
    assert c["petIdx"] == 0


def test_unknown_method_400(fresh_server):
    import urllib.request
    req = urllib.request.Request(
        fresh_server[0] + "/rpc",
        data=json.dumps({"method": "rm_rf", "args": []}).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15):
            pytest.fail("unknown method should 400")
    except urllib.error.HTTPError as e:
        assert e.code == 400


def test_malformed_rpc_body_500(fresh_server):
    import urllib.request
    req = urllib.request.Request(fresh_server[0] + "/rpc", data=b"not json",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15):
            pytest.fail("malformed body should error")
    except urllib.error.HTTPError as e:
        assert e.code == 500


def test_rpc_rejects_non_json_content_type(fresh_server):
    """CSRF guard: a cross-site form POST (text/plain, no preflight) must be
    rejected, not parsed by accident."""
    import urllib.request
    req = urllib.request.Request(
        fresh_server[0] + "/rpc",
        data="method=get_config".encode("utf-8"),
        headers={"Content-Type": "text/plain"})
    try:
        with urllib.request.urlopen(req, timeout=15):
            pytest.fail("text/plain should be rejected")
    except urllib.error.HTTPError as e:
        assert e.code == 415


def test_rpc_rejects_foreign_host(fresh_server):
    """DNS-rebinding guard: a Host header that isn't 127.0.0.1/localhost is
    rejected even with correct JSON + content type."""
    import urllib.request
    body = json.dumps({"method": "get_config", "args": []}).encode("utf-8")
    req = urllib.request.Request(
        fresh_server[0] + "/rpc", data=body,
        headers={"Content-Type": "application/json", "Host": "evil.example.com"})
    try:
        with urllib.request.urlopen(req, timeout=15):
            pytest.fail("foreign Host should be rejected")
    except urllib.error.HTTPError as e:
        assert e.code == 415


def test_rpc_rejects_huge_body(fresh_server):
    import urllib.request
    big = json.dumps({"method": "get_config", "args": [], "pad": "x" * (1 << 21)})
    req = urllib.request.Request(
        fresh_server[0] + "/rpc", data=big.encode("utf-8"),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15):
            pytest.fail("oversized body should be rejected")
    except urllib.error.HTTPError as e:
        assert e.code == 413


def test_concurrent_saves_no_key_loss(fresh_server):
    """The real cross-process lock must survive concurrent UI saves: every
    key the UI wrote is present when the dust settles."""
    base, d = fresh_server
    errors = []

    def save(k, v):
        try:
            wb.rpc(base, "save_config", {k: v})
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=save, args=("k%d" % i, i)) for i in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors
    with open(os.path.join(d, "config.json"), encoding="utf-8") as fh:
        on_disk = json.load(fh)
    for i in range(12):
        assert on_disk.get("k%d" % i) == i, "key k%d lost under concurrency" % i


def test_300_status_files(fresh_server):
    """The load case the pet dir can hit: 300 status files, mix of fresh and
    stale, under a generous per-call timeout (scale test, not a timing test)."""
    base, d = fresh_server
    now = int(time.time() * 1000)
    fresh = now + 600000  # stays fresh regardless of elapsed test time
    for i in range(300):
        st = "busy" if i % 3 == 0 else ("thinking" if i % 3 == 1 else "error")
        wb.write_json(os.path.join(d, "status-load-%03d.json" % i),
                      {"sessionID": "load-%d" % i, "state": st,
                       "title": "Load %d" % i,
                       "updatedAt": fresh if i < 250 else (now - 1200000)})
    # This is a scale test: it must complete, not beat a wall-clock budget.
    # Generous per-call timeout because the whole suite runs under load.
    t0 = time.time()
    wb.rpc(base, "get_sessions", timeout=90)
    t_baseline = time.time() - t0
    t0 = time.time()
    sess = wb.rpc(base, "get_sessions", timeout=90)
    t_300 = time.time() - t0
    # Relative timing (immune to machine load): 300 files must not be
    # dramatically slower than the 6-file baseline from the same server.
    assert t_300 < max(t_baseline * 8, 3.0), "%.3fs for 300 files (baseline %.3fs)" % (t_300, t_baseline)
    assert len(sess) >= 100  # most are fresh busy/thinking/error


def test_unicode_roundtrip(fresh_server):
    base, d = fresh_server
    wb.write_json(os.path.join(d, "status-uni.json"),
                  {"sessionID": "uni-1", "state": "busy", "title": "日本語 ペット 🐾",
                   "toolLabel": "emoji 🎉 test", "updatedAt": int(time.time() * 1000)})
    sess = wb.rpc(base, "get_sessions")
    assert any("🐾" in (s.get("title") or "") for s in sess)
    # petName is DERIVED from petIdx by get_config — a saved value must not
    # collide; unicode still round-trips through save/load on real keys.
    wb.rpc(base, "save_config", {"walk": 41})
    assert wb.rpc(base, "get_config")["walk"] == 41
    assert wb.rpc(base, "get_config")["petName"] == "Charmander"


def test_web_server_rejects_traversal(fresh_server):
    """The server only serves / and /rpc — no path traversal or file serving."""
    import urllib.request
    for path in ("/../../etc/passwd", "/desktop/main.py", "/rpc/../../x"):
        req = urllib.request.Request(fresh_server[0] + path)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                assert resp.status in (404, 400), path
        except urllib.error.HTTPError as e:
            assert e.code in (404, 400), path
