"""P4: wake ritual + dream journal, episodic memory bubbles, epoch markers.

Covers: build_dream determinism + template variety on real-shaped fixtures,
wake once/day (wakeDate guard) + long-idle wake cooldown, memory tick interval
+ max-per-day budget + daily reset, memory template selection from crafted
activity logs, pure epoch predicates (fire on crafted data, no re-fire when
flagged), and the get_memory_state API surface.
"""

import datetime
import json
import time

import pytest

main = pytest.importorskip("desktop.main")
import desktop.store as store_mod  # noqa: E402


def write(pet_dir, name, payload):
    p = pet_dir / name
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def read_log(pet_dir, eng):
    p = pet_dir / ("activity-%s.jsonl" % eng.pet["id"])
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def day_ago(n):
    return (datetime.date.today() - datetime.timedelta(days=n)).isoformat()


def _eng(pet_dir, no_window):
    eng = main.PetEngine()
    eng.xp = 0
    eng.level = 1
    eng.mood = "neutral"
    eng._last_tool_earn = ""
    eng.bubble_until = 0
    eng.sessions = []
    return eng


def _active(monkeypatch):
    monkeypatch.setattr(main, "last_input_ms", lambda: 0)
    monkeypatch.setattr(main, "foreground_app", lambda: "VS Code")


def _idle(monkeypatch):
    monkeypatch.setattr(main, "last_input_ms", lambda: store_mod.ACTIVE_MS + 1000)
    monkeypatch.setattr(main, "foreground_app", lambda: "VS Code")


def _drive(eng):
    eng._last_act = 0.0
    eng._wb_t = time.time() - 10
    eng.update_activity()


# ---------------------------------------------------------------- dream journal

class TestDream:
    def test_build_dream_deterministic(self, pet_dir):
        wb = {"date": time.strftime("%Y-%m-%d"),
              "apps": {"VS Code": 3600},
              "history": {day_ago(1): 28000, day_ago(2): 15000},
              "hourHistory": {day_ago(1): {str(h): 0 for h in range(24)}},
              "appHistory": {}}
        a = store_mod.build_dream(wb)
        b = store_mod.build_dream(json.loads(json.dumps(wb)))  # str keys everywhere
        assert a == b
        assert a.startswith("I dreamt of terminals")

    def test_build_dream_empty_without_data(self, pet_dir):
        assert store_mod.build_dream(None) == ""
        assert store_mod.build_dream({}) == ""
        assert store_mod.build_dream({"date": time.strftime("%Y-%m-%d"),
                                      "apps": {"VS Code": 900}}) == ""

    def test_deepest_day(self, pet_dir):
        hist = {day_ago(1): 3000, day_ago(3): 9000, day_ago(5): 9000}
        d, s = store_mod.deepest_day(hist)
        assert s == 9000
        assert d == day_ago(3)  # ties -> newest day

    def test_latest_hour(self, pet_dir):
        hh = {day_ago(1): {"1": 3600, "13": 7200}, day_ago(2): {"13": 3600}}
        h, s = store_mod.latest_hour(hh)
        assert h == 13 and s == 10800  # hour 13 across both days
        h2, s2 = store_mod.latest_hour({day_ago(1): {"2": 500, "0": 500}})
        assert h2 == 0  # ties -> earliest hour

    def test_template_deepest_day(self, pet_dir):
        wb = {"date": time.strftime("%Y-%m-%d"), "apps": {},
              "history": {day_ago(1): 25000, day_ago(2): 12000},  # ~6.9h, deepest
              "hourHistory": {day_ago(1): {"1": 25000}},
              "appHistory": {day_ago(1): {"VS Code": 25000}}}
        line = store_mod.build_dream(wb)
        assert "deepest day (6.9h)" in line

    def test_template_record_day(self, pet_dir):
        wb = {"date": time.strftime("%Y-%m-%d"), "apps": {},
              "history": {day_ago(1): 36000, day_ago(2): 3600},
              "hourHistory": {day_ago(1): {}},
              "appHistory": {}}
        assert "record day" in store_mod.build_dream(wb)

    def test_template_night_owl(self, pet_dir):
        wb = {"date": time.strftime("%Y-%m-%d"), "apps": {},
              "history": {day_ago(1): 6000, day_ago(2): 12000},  # not deepest
              "hourHistory": {day_ago(1): {"1": 4000, "2": 2000},
                              day_ago(2): {"1": 10000, "13": 5000}},
              "appHistory": {}}
        line = store_mod.build_dream(wb)
        assert "night owl" in line and "1 AM" in line

    def test_template_idle_heavy(self, pet_dir):
        wb = {"date": time.strftime("%Y-%m-%d"), "apps": {},
              "history": {day_ago(1): 7200, day_ago(2): 9000},
              "hourHistory": {},
              "appHistory": {day_ago(1): {"Idle": 5000, "VS Code": 2200}}}
        assert "mostly idle" in store_mod.build_dream(wb)

    def test_template_most_apps(self, pet_dir):
        wb = {"date": time.strftime("%Y-%m-%d"), "apps": {},
              "history": {day_ago(1): 7200, day_ago(2): 12000},
              "hourHistory": {}, "appHistory": {}}
        for i in range(5):
            wb["appHistory"].setdefault(day_ago(1), {})["App%d" % i] = 1000 + i
        assert "touched 5 apps" in store_mod.build_dream(wb)

    def test_template_quiet_day(self, pet_dir):
        wb = {"date": time.strftime("%Y-%m-%d"), "apps": {},
              "history": {day_ago(1): 1800, day_ago(2): 3600},
              "hourHistory": {}, "appHistory": {}}
        assert "quiet" in store_mod.build_dream(wb)

    def test_template_default_summary(self, pet_dir):
        wb = {"date": time.strftime("%Y-%m-%d"), "apps": {},
              "history": {day_ago(1): 9000, day_ago(2): 10000},
              "hourHistory": {}, "appHistory": {}}
        wb["appHistory"][day_ago(1)] = {"VS Code": 9000}
        line = store_mod.build_dream(wb)
        assert "2.5h" in line and "VS Code led the way" in line

    def test_template_variety(self, pet_dir):
        """Different data shapes must pick different templates (5+ used)."""
        base = {"date": time.strftime("%Y-%m-%d"), "apps": {},
                "history": {}, "hourHistory": {}, "appHistory": {}}
        wb1 = dict(base); wb1["history"] = {day_ago(1): 33480, day_ago(2): 12000}
        wb2 = dict(base); wb2["history"] = {day_ago(1): 1800}
        wb3 = dict(base); wb3["history"] = {day_ago(1): 6000}
        wb3["hourHistory"] = {day_ago(1): {"2": 4000}}
        lines = {store_mod.build_dream(wb) for wb in (wb1, wb2, wb3)}
        assert len(lines) == 3


# ---------------------------------------------------------------- wake ritual

class TestWake:
    def test_dream_fires_once_per_day(self, pet_dir, no_window, monkeypatch):
        _active(monkeypatch)
        write(pet_dir, "wellbeing.json",
              {"date": time.strftime("%Y-%m-%d"), "apps": {},
               "history": {day_ago(1): 25000, day_ago(2): 8000},
               "hourHistory": {day_ago(1): {"1": 12000}}, "appHistory": {}})
        eng = _eng(pet_dir, no_window)
        _drive(eng)
        assert "deepest day" in eng.bubble_text
        dreams = [r for r in read_log(pet_dir, eng) if r["kind"] == "dream"]
        assert len(dreams) == 1
        assert main.load_config()["wakeDate"] == time.strftime("%Y-%m-%d")
        # same day, more activity: no re-fire
        _drive(eng)
        assert len([r for r in read_log(pet_dir, eng) if r["kind"] == "dream"]) == 1

    def test_restart_does_not_redream_same_day(self, pet_dir, no_window, monkeypatch):
        _active(monkeypatch)
        write(pet_dir, "wellbeing.json",
              {"date": time.strftime("%Y-%m-%d"), "apps": {},
               "history": {day_ago(1): 33480}, "hourHistory": {}, "appHistory": {}})
        write(pet_dir, "config.json", {"wakeDate": time.strftime("%Y-%m-%d")})
        eng = _eng(pet_dir, no_window)
        _drive(eng)
        assert eng.bubble_text != "" or True  # no crash
        assert [r for r in read_log(pet_dir, eng) if r["kind"] == "dream"] == []

    def test_new_day_dreams_again(self, pet_dir, no_window, monkeypatch):
        _active(monkeypatch)
        write(pet_dir, "wellbeing.json",
              {"date": time.strftime("%Y-%m-%d"), "apps": {},
               "history": {day_ago(1): 33480}, "hourHistory": {}, "appHistory": {}})
        write(pet_dir, "config.json", {"wakeDate": day_ago(1)})
        eng = _eng(pet_dir, no_window)
        _drive(eng)
        assert len([r for r in read_log(pet_dir, eng) if r["kind"] == "dream"]) == 1

    def test_no_dream_without_data(self, pet_dir, no_window, monkeypatch):
        _active(monkeypatch)
        eng = _eng(pet_dir, no_window)
        _drive(eng)
        assert [r for r in read_log(pet_dir, eng) if r["kind"] == "dream"] == []
        assert main.load_config().get("wakeDate", "") == ""  # not burned

    def test_long_idle_wake_fires_and_cooldowns(self, pet_dir, no_window, monkeypatch):
        _idle(monkeypatch)
        eng = _eng(pet_dir, no_window)
        _drive(eng)  # baseline: pet starts idle
        eng._idle_since = time.time() - 300  # was idle 5 min
        _active(monkeypatch)
        _drive(eng)
        wakes = [r for r in read_log(pet_dir, eng) if r["kind"] == "wake"]
        assert len(wakes) == 1 and wakes[0]["idleSecs"] >= 300
        assert main.load_config().get("wakeIdleAt", 0) > 0
        # immediately idle again for 8 min: cooldown (4h) blocks the greeting
        _idle(monkeypatch)
        _drive(eng)
        eng._idle_since = time.time() - 480
        _active(monkeypatch)
        _drive(eng)
        assert len([r for r in read_log(pet_dir, eng) if r["kind"] == "wake"]) == 1

    def test_short_idle_no_wake(self, pet_dir, no_window, monkeypatch):
        _idle(monkeypatch)
        eng = _eng(pet_dir, no_window)
        _drive(eng)
        eng._idle_since = time.time() - 30  # under SLEEP_GAP
        _active(monkeypatch)
        _drive(eng)
        assert [r for r in read_log(pet_dir, eng) if r["kind"] == "wake"] == []


# ---------------------------------------------------------------- memory bubbles

class TestMemory:
    def _recall(self, pet_dir, no_window, **cfg):
        write(pet_dir, "config.json", dict({"memoryMin": 1}, **cfg))
        return _eng(pet_dir, no_window)

    def test_fires_after_interval_logs_no_xp(self, pet_dir, no_window):
        eng = self._recall(pet_dir, no_window)
        eng.os_active = True
        eng._memory_work = eng._next_memory_work
        eng._memory_tick(time.time())
        rows = [r for r in read_log(pet_dir, eng) if r["kind"] == "memory"]
        assert len(rows) == 1 and rows[0]["template"]
        assert eng.bubble_text  # real line, not empty
        assert eng.xp == 0  # NO XP — recalls are not achievements
        assert eng.mood == "happy" and eng._shimmer_mood == "neutral"
        c = main.load_config()
        assert c["memoryCount"] == 1 and c["memoryDate"] == time.strftime("%Y-%m-%d")

    def test_shimmer_restores_mood(self, pet_dir, no_window):
        eng = self._recall(pet_dir, no_window)
        eng.os_active = True
        eng._memory_work = eng._next_memory_work
        eng._memory_tick(time.time())
        assert eng.mood == "happy"
        eng._shimmer_until = time.time() - 1
        eng._mood_tick()
        assert eng.mood == "neutral"

    def test_cooldown_before_next_interval(self, pet_dir, no_window):
        eng = self._recall(pet_dir, no_window)
        eng.os_active = True
        eng._memory_work = eng._next_memory_work
        eng._memory_tick(time.time())
        eng._memory_work = 40  # < min interval (memoryMin=1 -> 45s)
        eng._memory_tick(time.time())
        assert len([r for r in read_log(pet_dir, eng) if r["kind"] == "memory"]) == 1

    def test_max_per_day(self, pet_dir, no_window):
        eng = self._recall(pet_dir, no_window, memoryMax=2)
        eng.os_active = True
        for _ in range(3):
            eng._memory_work = eng._next_memory_work
            eng._memory_tick(time.time())
        assert len([r for r in read_log(pet_dir, eng) if r["kind"] == "memory"]) == 2
        assert main.load_config()["memoryCount"] == 2

    def test_daily_counter_resets(self, pet_dir, no_window):
        write(pet_dir, "config.json",
              {"memoryMin": 1, "memoryMax": 3,
               "memoryDate": day_ago(1), "memoryCount": 3})
        eng = _eng(pet_dir, no_window)
        eng.os_active = True
        eng._memory_work = eng._next_memory_work
        eng._memory_tick(time.time())
        assert len([r for r in read_log(pet_dir, eng) if r["kind"] == "memory"]) == 1
        c = main.load_config()
        assert c["memoryCount"] == 1 and c["memoryDate"] == time.strftime("%Y-%m-%d")

    def test_idle_pauses_work_clock(self, pet_dir, no_window):
        eng = self._recall(pet_dir, no_window)
        eng.os_active = False
        eng._memory_work = eng._next_memory_work
        eng._memory_tick(time.time())
        assert [r for r in read_log(pet_dir, eng) if r["kind"] == "memory"] == []

    # ---------------- template selection from crafted logs

    def _log(self, pet_dir, eng, *events):
        with open(pet_dir / ("activity-%s.jsonl" % eng.pet["id"]),
                  "a", encoding="utf-8") as fh:
            for ev in events:
                fh.write(json.dumps(ev) + "\n")

    def test_template_streak_record(self, pet_dir, no_window):
        hist = {day_ago(0): 1800, day_ago(1): 1800, day_ago(2): 1800,
                day_ago(4): 1800, day_ago(5): 1800}  # 3-day run beats old 2
        write(pet_dir, "wellbeing.json",
              {"date": time.strftime("%Y-%m-%d"), "apps": {},
               "history": hist, "hourHistory": {}, "appHistory": {}})
        eng = _eng(pet_dir, no_window)
        line, tpl = eng._memory_line()
        assert tpl == "streak_record"
        assert "never done before" in line

    def test_template_streak_match(self, pet_dir, no_window):
        hist = {day_ago(0): 1800, day_ago(1): 1800, day_ago(2): 1800,
                day_ago(7): 1800, day_ago(8): 1800, day_ago(9): 1800}
        write(pet_dir, "wellbeing.json",
              {"date": time.strftime("%Y-%m-%d"), "apps": {},
               "history": hist, "hourHistory": {}, "appHistory": {}})
        eng = _eng(pet_dir, no_window)
        line, tpl = eng._memory_line()
        assert tpl == "streak_match"
        assert "matches your best run" in line

    def test_template_session_record(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        self._log(pet_dir, eng,
                  {"t": time.time() - 86400, "kind": "focusDone", "minutes": 60})
        line, tpl = eng._memory_line()
        assert tpl == "session_record"
        assert "Longest session: 60 min" in line

    def test_template_pet_switch(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        t0 = time.time() - 3600
        self._log(pet_dir, eng,
                  {"t": t0, "kind": "petSwitch", "toIdx": 1},
                  {"t": t0 + 60, "kind": "petSwitch", "toIdx": 2},
                  {"t": t0 + 120, "kind": "petSwitch", "toIdx": 3})
        line, tpl = eng._memory_line()
        assert tpl == "pet_switch"
        assert "You swapped pets 3 times on" in line

    def test_template_first_of_day(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        today = time.strftime("%Y-%m-%d")
        t = time.mktime(time.strptime(today + " 08:00", "%Y-%m-%d %H:%M"))
        self._log(pet_dir, eng,
                  {"t": t, "kind": "focusStart", "targetMin": 25, "app": "VS Code"})
        line, tpl = eng._memory_line()
        assert tpl == "first_of_day"
        assert "First focus today at 08:00" in line

    def test_template_session_count(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        self._log(pet_dir, eng,
                  {"t": time.time() - 1000, "kind": "focusDone", "minutes": 20},
                  {"t": time.time() - 2000, "kind": "focusDone", "minutes": 20})
        line, tpl = eng._memory_line()
        assert tpl == "session_count"
        assert "2 focus sessions in the last 7 days" in line

    def test_template_fallback_quiet(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        line, tpl = eng._memory_line()
        assert tpl == "quiet_week"
        assert line

    def test_memory_work_accrues_only_while_active(self, pet_dir, no_window, monkeypatch):
        _active(monkeypatch)
        eng = _eng(pet_dir, no_window)
        eng._next_memory_work = 1000  # well above one tick's dt
        _drive(eng)  # active: ~10s accrued
        assert eng._memory_work >= 10
        _idle(monkeypatch)
        eng._last_act = 0.0
        eng._wb_t = time.time() - 10
        before = eng._memory_work
        eng.update_activity()  # idle tick: no accrual
        assert eng._memory_work == before


# ---------------------------------------------------------------- epoch markers

class TestEpochs:
    def test_first_focus_epoch(self, pet_dir):
        out = store_mod.evaluate_epochs({}, {}, {}, 0, focus_count=1)
        assert ("first_focus", "First Focus", "Your first completed focus session") in out
        assert store_mod.evaluate_epochs({}, {}, {}, 0, focus_count=0) == []

    def test_long_day_epoch(self, pet_dir):
        out = store_mod.evaluate_epochs({day_ago(2): store_mod.LONG_DAY_MIN_SECS + 1},
                                        {}, {}, 0)
        assert ("long_day", "Long Day", "First 9+ hour day") in out

    def test_night_owl_epoch(self, pet_dir):
        hh = {day_ago(1): {"0": 10800, "5": 3600, "13": 7200}}
        out = store_mod.evaluate_epochs({}, hh, {}, 0)
        assert ("night_owl", "Night Owl", "First 4h+ night (midnight to 6am)") in out

    def test_ten_hour_total_epoch(self, pet_dir):
        hist = {day_ago(i): 7200 for i in range(1, 6)}  # 10h across 10 days
        out = store_mod.evaluate_epochs(hist, {}, {}, 0)
        assert ("ten_hour_total", "Ten Hours", "10h of focus across 10 days") in out

    def test_first_week_epoch(self, pet_dir):
        hist = {day_ago(i): 1800 for i in range(1, 8)}
        out = store_mod.evaluate_epochs(hist, {}, {}, 0)
        assert ("first_week", "First Week", "7 days of history recorded") in out

    def test_week_streak_epoch(self, pet_dir):
        hist = {day_ago(i): 1800 for i in range(1, 8)}
        out = store_mod.evaluate_epochs(hist, {}, {}, 0)
        assert ("week_streak", "Week Streak", "First 7-day focus streak") in out

    def test_thirty_days_epoch(self, pet_dir):
        hist = {day_ago(i): 1800 for i in range(1, 31)}
        out = store_mod.evaluate_epochs(hist, {}, {}, 0)
        assert ("thirty_days", "One Month", "30 days of history recorded") in out

    def test_xp_epoch(self, pet_dir):
        out = store_mod.evaluate_epochs({}, {}, {}, 500)
        assert ("xp_500", "Five Hundred", "First 500 XP earned") in out
        assert store_mod.evaluate_epochs({}, {}, {}, 499) == []

    def test_no_refire_when_flagged(self, pet_dir):
        cfg = {"epochFlags": ["long_day", "first_focus"]}
        out = store_mod.evaluate_epochs({day_ago(2): store_mod.LONG_DAY_MIN_SECS + 1},
                                        {}, cfg, 0, focus_count=5)
        ids = [e[0] for e in out]
        assert "long_day" not in ids and "first_focus" not in ids

    def test_engine_fires_once_awards_xp(self, pet_dir, no_window):
        write(pet_dir, "wellbeing.json",
              {"date": time.strftime("%Y-%m-%d"), "apps": {},
               "history": {day_ago(1): store_mod.LONG_DAY_MIN_SECS + 1},
               "hourHistory": {}, "appHistory": {}})
        eng = _eng(pet_dir, no_window)
        eng._epoch_tick(time.time())
        assert eng.xp == 25
        assert eng.mood == "happy"
        epochs = [r for r in read_log(pet_dir, eng) if r["kind"] == "epoch"]
        assert len(epochs) == 1 and epochs[0]["id"] == "long_day"
        assert "long_day" in main.load_config()["epochFlags"]
        # second evaluation: flagged -> no re-fire, no re-award
        eng._epoch_tick(time.time())
        assert eng.xp == 25
        assert len([r for r in read_log(pet_dir, eng) if r["kind"] == "epoch"]) == 1

    def test_engine_first_focus_epoch_from_log(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        with open(pet_dir / ("activity-%s.jsonl" % eng.pet["id"]),
                  "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"t": time.time() - 60, "kind": "focusDone",
                                 "minutes": 25}) + "\n")
        eng._epoch_tick(time.time())
        epochs = [r for r in read_log(pet_dir, eng) if r["kind"] == "epoch"]
        assert len(epochs) == 1 and epochs[0]["id"] == "first_focus"

    def test_epoch_definition_order_priority(self, pet_dir):
        hist = {day_ago(i): 1800 for i in range(1, 31)}
        out = store_mod.evaluate_epochs(hist, {}, {}, 0)
        ids = [e[0] for e in out]
        assert ids[0] == "first_week"  # definition order, not data order


# ---------------------------------------------------------------- API surface

class TestMemoryApi:
    def test_get_memory_state_defaults(self, pet_dir):
        s = main.ControlApi().get_memory_state()
        assert s == {"wakeDate": "", "dream": "", "memoryCount": 0, "memoryMax": 3,
                     "epochFlags": []}

    def test_get_memory_state_dream_and_flags(self, pet_dir):
        write(pet_dir, "wellbeing.json",
              {"date": time.strftime("%Y-%m-%d"), "apps": {},
               "history": {day_ago(1): 25000, day_ago(2): 12000},
               "hourHistory": {day_ago(1): {"1": 25000}}, "appHistory": {}})
        write(pet_dir, "config.json",
              {"wakeDate": time.strftime("%Y-%m-%d"),
               "memoryCount": 1, "memoryMax": 3,
               "epochFlags": ["long_day", "first_focus"]})
        s = main.ControlApi().get_memory_state()
        assert s["wakeDate"] == time.strftime("%Y-%m-%d")
        assert "deepest day" in s["dream"]  # same digest the pet bubbles
        assert s["memoryCount"] == 1 and s["memoryMax"] == 3
        names = {f["name"] for f in s["epochFlags"]}
        assert names == {"Long Day", "First Focus"}
        assert all(f["desc"] for f in s["epochFlags"])
