"""Config / status-file / wellbeing / ControlApi tests, all pointed at a
temp PET_DIR so nothing touches the real ~/.opencode/pet.
"""

import datetime
import json
import time

import pytest

main = pytest.importorskip("desktop.main")


def write(pet_dir, name, payload):
    p = pet_dir / name
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


# ---------------------------------------------------------------- config

class TestConfig:
    def test_defaults_when_missing(self, pet_dir):
        c = main.load_config()
        assert c["petIdx"] == 0
        assert c["alwaysOnTop"] is True
        assert c["walk"] == 100
        assert c["breakMin"] == 50

    def test_corrupt_config_falls_back_to_defaults(self, pet_dir):
        (pet_dir / "config.json").write_text("{ not json !!!", encoding="utf-8")
        c = main.load_config()
        assert c["petIdx"] == 0

    def test_save_load_roundtrip(self, pet_dir):
        main.save_config({"petIdx": 3, "walk": 40, "breakMin": 25})
        c = main.load_config()
        assert c["petIdx"] == 3
        assert c["walk"] == 40
        assert c["breakMin"] == 25

    def test_save_merges_with_existing(self, pet_dir):
        main.save_config({"petIdx": 1})
        main.save_config({"walk": 60})  # must not clobber petIdx
        c = main.load_config()
        assert c["petIdx"] == 1
        assert c["walk"] == 60

    def test_clear_command_removes_key(self, pet_dir):
        write(pet_dir, "config.json", {"petIdx": 2, "hidePet": 1})
        main.PetEngine._clear_command("hidePet")
        c = json.loads((pet_dir / "config.json").read_text(encoding="utf-8"))
        assert "hidePet" not in c
        assert c["petIdx"] == 2


# ---------------------------------------------------------------- status

class TestReadStatus:
    def _status(self, pet_dir, updated_at=None, state="busy"):
        write(pet_dir, "status-s1.json",
              {"sessionID": "s1", "state": state, "updatedAt": updated_at or
               int(time.time() * 1000)})

    def test_empty_dir(self, pet_dir):
        assert main.read_status() == []

    def test_missing_dir_returns_empty(self, pet_dir, monkeypatch):
        monkeypatch.setattr(main, "PET_DIR", str(pet_dir / "nope"))
        assert main.read_status() == []

    def test_fresh_not_stale(self, pet_dir):
        self._status(pet_dir)
        out = main.read_status()
        assert out and out[0]["stale"] is False

    def test_old_is_stale(self, pet_dir):
        self._status(pet_dir, updated_at=int(time.time() * 1000) - 60000)
        out = main.read_status()
        assert out and out[0]["stale"] is True

    def test_corrupt_file_skipped(self, pet_dir):
        self._status(pet_dir)
        (pet_dir / "status-broken.json").write_text("<<<", encoding="utf-8")
        out = main.read_status()
        assert len(out) == 1

    def test_sorted_newest_first(self, pet_dir):
        now = int(time.time() * 1000)
        write(pet_dir, "status-old.json", {"sessionID": "a", "updatedAt": now - 5000})
        write(pet_dir, "status-new.json", {"sessionID": "b", "updatedAt": now})
        out = main.read_status()
        assert [s["sessionID"] for s in out] == ["b", "a"]

    def test_non_status_files_ignored(self, pet_dir):
        (pet_dir / "config.json").write_text("{}", encoding="utf-8")
        assert main.read_status() == []


# ---------------------------------------------------------------- wellbeing

class TestWellbeing:
    def test_save_and_load_same_date(self, pet_dir):
        main.PetEngine._wb = {}  # reset module-ish state
        d = {"date": time.strftime("%Y-%m-%d"), "apps": {"VS Code": 120}}
        write(pet_dir, "wellbeing.json", d)
        eng = object.__new__(main.PetEngine)
        eng._wb = {}
        eng._wb_date = time.strftime("%Y-%m-%d")
        eng._load_wellbeing()
        assert eng._wb == {"VS Code": 120}

    def test_old_date_retained_for_rollover(self, pet_dir):
        """A previous-day file is kept (date + apps) so the first
        _track_app_time folds that day into history instead of dropping it."""
        write(pet_dir, "wellbeing.json", {"date": "2000-01-01", "apps": {"X": 1}})
        eng = object.__new__(main.PetEngine)
        eng._wb = {"keep": 5}
        eng._wb_date = time.strftime("%Y-%m-%d")
        eng._history = {}
        eng._load_wellbeing()
        assert eng._wb_date == "2000-01-01"
        assert eng._wb == {"X": 1}

    def test_save_creates_file(self, pet_dir):
        eng = object.__new__(main.PetEngine)
        eng._wb = {"Terminal": 42}
        eng._wb_date = time.strftime("%Y-%m-%d")
        eng._save_wellbeing()
        d = json.loads((pet_dir / "wellbeing.json").read_text(encoding="utf-8"))
        assert d["apps"] == {"Terminal": 42}

    def test_history_persists_through_save(self, pet_dir):
        eng = object.__new__(main.PetEngine)
        eng._wb = {"Terminal": 42}
        eng._wb_date = time.strftime("%Y-%m-%d")
        eng._history = {"2026-07-25": 3600}
        eng._save_wellbeing()
        d = json.loads((pet_dir / "wellbeing.json").read_text(encoding="utf-8"))
        assert d["history"] == {"2026-07-25": 3600}

    def test_corrupt_apps_values_do_not_crash_rollover(self, pet_dir):
        """A corrupt wellbeing.json (non-numeric app values) must not let a
        TypeError reach _track_app_time/_rollover_wellbeing and kill the
        render loop — non-numeric entries are dropped on load."""
        write(pet_dir, "wellbeing.json",
              {"date": time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400)),
               "apps": {"VS Code": "7200", "Terminal": None}})
        eng = object.__new__(main.PetEngine)
        eng._wb = {}
        eng._wb_date = time.strftime("%Y-%m-%d")
        eng._wb_app = ""
        eng._wb_t = time.time()
        eng._last_wb_save = 0.0
        eng._history = {}
        eng.os_active = True
        eng.os_app = "VS Code"
        eng._load_wellbeing()  # must not raise; drops the junk values
        assert eng._wb == {}
        eng._track_app_time()  # rollover path — must not raise
        assert eng._wb_date == time.strftime("%Y-%m-%d")

    def test_rollover_folds_previous_day_into_history(self, pet_dir):
        eng = object.__new__(main.PetEngine)
        eng._wb = {"VS Code": 7200}
        eng._wb_date = time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400))
        eng._wb_app = ""
        eng._wb_t = time.time()
        eng._last_wb_save = 0.0
        eng._history = {}
        eng.os_active = True
        eng.os_app = "VS Code"
        eng._track_app_time()
        assert eng._wb_date == time.strftime("%Y-%m-%d")
        yesterday = time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400))
        assert eng._history.get(yesterday) == 7200

    def test_hour_buckets_fold_on_rollover(self, pet_dir):
        """The per-hour focus buckets land in hourHistory at rollover and
        survive a save/load round trip (the best-time analysis's data)."""
        eng = object.__new__(main.PetEngine)
        eng._wb = {}
        eng._wb_date = time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400))
        eng._wb_app = ""
        eng._wb_t = time.time()
        eng._last_wb_save = 0.0
        eng._history = {}
        eng._hour_today = {9: 1800, 10: 3600}
        eng._hour_history = {}
        eng.os_active = True
        eng.os_app = "VS Code"
        eng._track_app_time()  # triggers rollover
        yesterday = time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400))
        assert eng._hour_history.get(yesterday) == {9: 1800, 10: 3600}
        # new day: hour_today reset, history preserved through save
        assert eng._hour_today == {}
        eng._save_wellbeing()
        d = json.loads((pet_dir / "wellbeing.json").read_text(encoding="utf-8"))
        # JSON stringifies dict keys; the load path re-normalizes them to int.
        assert d["hourHistory"][yesterday] == {"9": 1800, "10": 3600}

    def test_hour_today_survives_load(self, pet_dir):
        """Today's live hour buckets are restored from the file so the
        analysis sees them without waiting for rollover."""
        today = time.strftime("%Y-%m-%d")
        write(pet_dir, "wellbeing.json",
              {"date": today, "apps": {}, "hourToday": {14: 900, 15: 2700}})
        eng = object.__new__(main.PetEngine)
        eng._wb = {}
        eng._wb_date = today
        eng._load_wellbeing()
        assert eng._hour_today.get(15) == 2700

    def test_cross_midnight_restart_keeps_hour_buckets(self, pet_dir):
        """A restart on a NEW day must not lose the previous day's hour
        distribution: hourToday from the file folds into hourHistory at load
        (the pet process was closed before the rollover could run)."""
        yesterday = time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400))
        write(pet_dir, "wellbeing.json",
              {"date": yesterday, "apps": {"VS Code": 3600},
               "hourToday": {9: 1800, 10: 3600},
               "hourHistory": {}})
        eng = object.__new__(main.PetEngine)
        eng._wb = {}
        eng._wb_date = time.strftime("%Y-%m-%d")  # engine boots on the new day
        eng._hour_history = {}
        eng._load_wellbeing()
        assert eng._wb_date == yesterday  # first _track_app_time folds the day
        assert eng._hour_today == {}  # live buckets are no longer "today"
        # the previous day's shape is preserved for the peaks analysis
        assert eng._hour_history.get(yesterday) == {9: 1800, 10: 3600}

    def test_corrupt_hour_buckets_do_not_crash(self, pet_dir):
        """Non-numeric hour values must be dropped on load, never crash the
        render loop."""
        today = time.strftime("%Y-%m-%d")
        write(pet_dir, "wellbeing.json",
              {"date": today, "apps": {},
               "hourToday": {"8": "3600", "9": None},
               "hourHistory": {"2026-01-01": {"x": 1}}})
        eng = object.__new__(main.PetEngine)
        eng._wb = {}
        eng._wb_date = today
        eng._load_wellbeing()
        assert eng._hour_today == {}  # junk dropped
        eng._save_wellbeing()  # must not raise


# ---------------------------------------------------------------- ControlApi

class TestControlApi:
    def _api(self, pet_dir):
        return main.ControlApi()

    def test_get_config_shape(self, pet_dir):
        c = self._api(pet_dir).get_config()
        assert c["petIdx"] == 0
        assert c["pets"] == [p["name"] for p in main.PETS]
        assert "petVisible" in c
        assert "petName" in c
        assert c["state"] == "idle"

    def test_get_config_state_from_fresh_session(self, pet_dir):
        write(pet_dir, "status-a.json",
              {"sessionID": "a", "state": "busy",
               "updatedAt": int(time.time() * 1000)})
        c = self._api(pet_dir).get_config()
        assert c["state"] == "busy"

    def test_get_config_stale_session_is_idle(self, pet_dir):
        write(pet_dir, "status-a.json",
              {"sessionID": "a", "state": "busy",
               "updatedAt": int(time.time() * 1000) - 120000})
        c = self._api(pet_dir).get_config()
        assert c["state"] == "idle"

    def test_get_sessions_filters_idle_and_stale(self, pet_dir):
        now = int(time.time() * 1000)
        write(pet_dir, "status-busy.json", {"sessionID": "b", "state": "busy", "updatedAt": now})
        write(pet_dir, "status-think.json", {"sessionID": "t", "state": "thinking", "updatedAt": now})
        write(pet_dir, "status-idle.json", {"sessionID": "i", "state": "idle", "updatedAt": now})
        write(pet_dir, "status-stale.json",
              {"sessionID": "s", "state": "error", "updatedAt": now - 120000})
        out = self._api(pet_dir).get_sessions()
        ids = sorted(s["sessionID"] for s in out)
        assert ids == ["b", "t"]

    def test_get_logs_empty_when_no_file(self, pet_dir):
        assert self._api(pet_dir).get_logs() == []

    def test_get_logs_reads_current_pet_file(self, pet_dir):
        log = pet_dir / "activity-capvolt.jsonl"
        log.write_text(
            json.dumps({"t": time.time(), "kind": "state", "state": "busy"}) + "\n"
            + "garbage line\n"
            + json.dumps({"t": time.time(), "kind": "poke"}) + "\n",
            encoding="utf-8",
        )
        out = self._api(pet_dir).get_logs(limit=10)
        assert len(out) == 2
        assert out[0]["kind"] == "state"

    def test_get_logs_respects_limit(self, pet_dir):
        log = pet_dir / "activity-capvolt.jsonl"
        lines = "".join(
            json.dumps({"t": time.time() + i, "kind": "state", "state": "busy"}) + "\n"
            for i in range(50)
        )
        log.write_text(lines, encoding="utf-8")
        out = self._api(pet_dir).get_logs(limit=5)
        assert len(out) == 5

    def test_next_prev_pet_wraparound(self, pet_dir):
        api = self._api(pet_dir)
        api.next_pet()
        assert main.load_config()["petIdx"] == 1
        # from 1, 5 more nexts wraps to 0
        for _ in range(5):
            api.next_pet()
        assert main.load_config()["petIdx"] == 0
        api.prev_pet()
        assert main.load_config()["petIdx"] == len(main.PETS) - 1

    def test_save_config_merges(self, pet_dir):
        api = self._api(pet_dir)
        api.save_config({"walk": 33})
        c = main.load_config()
        assert c["walk"] == 33
        assert c["petIdx"] == 0

    def test_hide_show_pet_write_commands(self, pet_dir):
        api = self._api(pet_dir)
        api.hide_pet()
        c = json.loads((pet_dir / "config.json").read_text(encoding="utf-8"))
        assert c.get("hidePet")
        api.show_pet()
        c = json.loads((pet_dir / "config.json").read_text(encoding="utf-8"))
        assert c.get("showPet")  # _cmd merges; engine clears applied commands

    def test_get_wellbeing_top_apps(self, pet_dir):
        write(pet_dir, "wellbeing.json",
              {"date": time.strftime("%Y-%m-%d"),
               "apps": {"Terminal": 600, "VS Code": 300, "tiny": 10}})
        out = self._api(pet_dir).get_wellbeing()
        assert [w["app"] for w in out] == ["Terminal", "VS Code"]
        assert out[0]["seconds"] == 600

    def test_get_wellbeing_history_empty(self, pet_dir):
        """No wellbeing file -> a contiguous zero-filled window, not []: the
        chart contract is always an N-day series (see the web bridge too)."""
        out = self._api(pet_dir).get_wellbeing_history(7)
        assert len(out) == 7
        assert all(h["seconds"] == 0 for h in out)
        assert out[-1]["date"] == time.strftime("%Y-%m-%d")

    def test_get_wellbeing_history_seven_days(self, pet_dir):
        today = time.strftime("%Y-%m-%d")
        hist = {}
        for i in range(10):
            day = time.strftime("%Y-%m-%d", time.localtime(time.time() - i * 86400))
            hist[day] = (i + 1) * 600
        write(pet_dir, "wellbeing.json", {"date": today, "apps": {}, "history": hist})
        out = self._api(pet_dir).get_wellbeing_history(7)
        assert len(out) == 7
        dates = [d["date"] for d in out]
        assert dates == sorted(dates)  # ascending
        assert out[-1]["date"] == today
        # window is the last 7 stored days: (i+1)*600 for i in 6..0
        assert out[0]["seconds"] == 4200
        assert out[-1]["seconds"] == 600

    def test_get_wellbeing_history_includes_live_today(self, pet_dir):
        today = time.strftime("%Y-%m-%d")
        write(pet_dir, "wellbeing.json",
              {"date": today, "apps": {"VS Code": 1800}, "history": {}})
        out = self._api(pet_dir).get_wellbeing_history(7)
        assert out[-1]["date"] == today
        assert out[-1]["seconds"] == 1800

    def test_get_wellbeing_history_old_format(self, pet_dir):
        """A pre-history wellbeing.json (date + apps only) must still chart."""
        today = time.strftime("%Y-%m-%d")
        write(pet_dir, "wellbeing.json", {"date": today, "apps": {"Terminal": 900}})
        out = self._api(pet_dir).get_wellbeing_history(3)
        assert len(out) == 3
        assert out[-1]["seconds"] == 900
        assert out[0]["seconds"] == 0

    def test_get_wellbeing_history_days_clamped(self, pet_dir):
        today = time.strftime("%Y-%m-%d")
        write(pet_dir, "wellbeing.json", {"date": today, "apps": {}, "history": {}})
        assert len(self._api(pet_dir).get_wellbeing_history(999)) <= 90  # heatmap window
        assert len(self._api(pet_dir).get_wellbeing_history(0)) == 1

    # ------------------------------------------------- insights
    def test_get_wellbeing_insights_empty(self, pet_dir):
        ins = self._api(pet_dir).get_wellbeing_insights()
        assert ins["weekSeconds"] == 0
        assert ins["prevWeekSeconds"] == 0
        assert ins["deltaPct"] is None
        assert ins["bestDay"] is None
        assert ins["topApp"] is None
        assert ins["todaySeconds"] == 0

    def test_get_wellbeing_insights_week_comparison(self, pet_dir):
        """Current week 4h/day, previous week 2h/day -> week/prev/delta all
        computed, best day = today (4h + today's running), top app today."""
        today = datetime.date.today()
        hist = {}
        for i in range(7):
            hist[(today - datetime.timedelta(days=i)).isoformat()] = 4 * 3600
        for i in range(7, 14):
            hist[(today - datetime.timedelta(days=i)).isoformat()] = 2 * 3600
        write(pet_dir, "wellbeing.json",
              {"date": today.isoformat(), "apps": {"VS Code": 1800}, "history": hist})
        ins = self._api(pet_dir).get_wellbeing_insights()
        assert ins["weekSeconds"] == 7 * 4 * 3600 + 1800
        assert ins["prevWeekSeconds"] == 7 * 2 * 3600
        # (102600 - 50400) / 50400 = 103.57% -> 104
        assert ins["deltaPct"] == 104
        assert ins["bestDay"] == {"date": today.isoformat(), "seconds": 4 * 3600 + 1800}
        assert ins["topApp"] == {"app": "VS Code", "seconds": 1800}

    def test_get_wellbeing_insights_delta_none_without_baseline(self, pet_dir):
        today = datetime.date.today().isoformat()
        write(pet_dir, "wellbeing.json",
              {"date": today, "apps": {"Terminal": 900}, "history": {}})
        ins = self._api(pet_dir).get_wellbeing_insights()
        assert ins["weekSeconds"] == 900
        assert ins["prevWeekSeconds"] == 0
        assert ins["deltaPct"] is None
        assert ins["topApp"] == {"app": "Terminal", "seconds": 900}

    def test_get_wellbeing_insights_flat_week(self, pet_dir):
        today = datetime.date.today()
        hist = {}
        for i in range(14):
            hist[(today - datetime.timedelta(days=i)).isoformat()] = 3600
        write(pet_dir, "wellbeing.json",
              {"date": today.isoformat(), "apps": {}, "history": hist})
        ins = self._api(pet_dir).get_wellbeing_insights()
        assert ins["deltaPct"] == 0
        assert ins["weekSeconds"] == ins["prevWeekSeconds"]


# ---------------------------------------------------------------- growth / focus

class TestGrowth:
    """XP, leveling, mood, focus sessions, streak — the companion layer."""

    def test_xp_curve_linear(self):
        assert main.PetEngine._xp_needed(1) == 100
        assert main.PetEngine._xp_needed(7) == 400

    def test_award_xp_levels_up(self, pet_dir, no_window):
        eng = main.PetEngine()
        eng.xp = 90
        eng.level = 1
        eng.mood = "neutral"
        eng._last_tool_earn = ""
        eng.bubble_until = 0
        eng._award_xp(50, "focus")
        # 90 + 50 = 140 -> level 2 with 40 leftover
        assert eng.level == 2
        assert eng.xp == 40
        assert eng.mood == "happy"  # leveled up
        # persisted to config
        c = main.load_config()
        assert c["level"] == 2 and c["xp"] == 40

    def test_award_xp_no_level_still_saves(self, pet_dir, no_window):
        eng = main.PetEngine()
        eng.xp = 10
        eng.level = 1
        eng.mood = "neutral"
        eng._last_tool_earn = ""
        eng.bubble_until = 0
        eng._award_xp(20, "tool")
        assert eng.level == 1 and eng.xp == 30
        c = main.load_config()
        assert c["xp"] == 30

    def test_focus_session_completes_awards_xp(self, pet_dir, no_window):
        eng = main.PetEngine()
        eng.xp = 0
        eng.level = 1
        eng.mood = "neutral"
        eng._last_tool_earn = ""
        eng.bubble_until = 0
        eng.focus_target_min = 25
        eng.focus_wilted = False
        eng._focus_app = "VS Code"
        # start a session, then fast-forward past the target
        eng.start_focus(25)
        eng.focus_started = time.time() - 25 * 60 - 1
        eng._focus_tick()
        assert eng.focus_active is False
        assert eng.xp == 50  # completion bonus
        assert eng.mood == "happy"

    def test_focus_session_wilts_on_app_switch(self, pet_dir, no_window):
        eng = main.PetEngine()
        eng.xp = 0
        eng.level = 1
        eng.mood = "neutral"
        eng._last_tool_earn = ""
        eng.bubble_until = 0
        eng.focus_target_min = 25
        eng.focus_wilted = False
        eng._focus_app = "VS Code"
        eng.start_focus(25)
        eng.os_active = True
        eng.os_app = "Chrome"
        eng._focus_tick()
        assert eng.focus_wilted is True
        assert eng.focus_active is True  # still running, just wilted

    def test_streak_days_counts_consecutive_30min_days(self, pet_dir, no_window):
        eng = main.PetEngine()
        eng._history = {}
        today = datetime.date.today()
        for back in range(5):
            day = (today - datetime.timedelta(days=back)).isoformat()
            eng._history[day] = 45 * 60
        eng._history[(today - datetime.timedelta(days=5)).isoformat()] = 5 * 60
        assert eng._streak_days() == 5


class TestFocusApi:
    def _api(self, pet_dir):
        return main.ControlApi()

    def test_get_focus_state_idle_shape(self, pet_dir):
        fs = self._api(pet_dir).get_focus_state()
        assert fs["active"] is False
        assert "progress" in fs and "targetMin" in fs

    def test_get_focus_state_reads_real_file(self, pet_dir):
        write(pet_dir, "focus.json",
              {"active": True, "startedAt": time.time() - 600,
               "targetMin": 25, "wilted": False, "app": "VS Code",
               "progress": 0.4})
        fs = self._api(pet_dir).get_focus_state()
        assert fs["active"] is True
        assert fs["targetMin"] == 25
        assert fs["progress"] > 0

    def test_focus_one_shot_commands(self, pet_dir):
        self._api(pet_dir).start_focus(45)
        c = json.loads((pet_dir / "config.json").read_text(encoding="utf-8"))
        assert c.get("focusStart") == 45
        self._api(pet_dir).stop_focus()
        c = json.loads((pet_dir / "config.json").read_text(encoding="utf-8"))
        assert c.get("focusStop") == 1

    def test_pet_profile_defaults(self, pet_dir):
        p = self._api(pet_dir).get_pet_profile()
        assert p["level"] == 1 and p["xp"] == 0
        assert p["xpNext"] == 100
        assert p["mood"] == "neutral"
        assert p["streak"] == 0

    def test_pet_profile_from_config(self, pet_dir):
        write(pet_dir, "config.json", {"xp": 64, "level": 7, "mood": "happy"})
        p = self._api(pet_dir).get_pet_profile()
        assert p["level"] == 7 and p["xp"] == 64
        assert p["xpNext"] == 400
        assert p["mood"] == "happy"

    def test_weekly_wrapped_empty(self, pet_dir):
        w = self._api(pet_dir).get_weekly_wrapped()
        assert w["weekSeconds"] == 0
        assert w["bestDay"] is None
        assert w["topApp"] is None
        assert w["focusSessions"] == 0
        assert w["prevWeekSeconds"] == 0

    def test_weekly_wrapped_with_history(self, pet_dir):
        today = time.strftime("%Y-%m-%d")
        hist = {}
        for i in range(10):
            day = time.strftime("%Y-%m-%d", time.localtime(time.time() - i * 86400))
            hist[day] = 3600
        write(pet_dir, "wellbeing.json", {"date": today, "apps": {}, "history": hist})
        w = self._api(pet_dir).get_weekly_wrapped()
        assert w["weekSeconds"] == 7 * 3600
        assert w["prevWeekSeconds"] == 3 * 3600
        assert w["bestDay"]["seconds"] == 3600
        assert w["focusSessions"] == 0

    def test_weekly_wrapped_counts_focus_sessions(self, pet_dir):
        log = pet_dir / "activity-capvolt.jsonl"
        log.write_text(json.dumps({"t": time.time() - 3600, "kind": "focusDone",
                                   "minutes": 25}) + "\n"
                       + json.dumps({"t": time.time() - 3600 * 24 * 10,
                                     "kind": "focusDone", "minutes": 25}) + "\n",
                       encoding="utf-8")
        w = self._api(pet_dir).get_weekly_wrapped()
        assert w["focusSessions"] == 1  # only the recent one

    def test_week_apps_aggregates_history(self, pet_dir):
        today = time.strftime("%Y-%m-%d")
        hist = {}
        app_hist = {}
        for i in range(3):
            day = time.strftime("%Y-%m-%d", time.localtime(time.time() - i * 86400))
            hist[day] = 3600
            app_hist[day] = {"VS Code": 1800, "Terminal": 1800}
        write(pet_dir, "wellbeing.json",
              {"date": today, "apps": {"Chrome": 120},
               "history": hist, "appHistory": app_hist})
        rows = self._api(pet_dir).get_week_apps(7)
        apps = {r["app"]: r["seconds"] for r in rows}
        assert apps.get("VS Code") == 5400  # 3 x 1800
        assert apps.get("Terminal") == 5400
        assert apps.get("Chrome") == 120  # today's live apps folded in
        assert rows == sorted(rows, key=lambda r: -r["seconds"])

    def test_week_apps_filters_sub_minute(self, pet_dir):
        today = time.strftime("%Y-%m-%d")
        write(pet_dir, "wellbeing.json",
              {"date": today, "apps": {"Chrome": 30},
               "history": {}, "appHistory": {}})
        assert self._api(pet_dir).get_week_apps(7) == []  # < 60s dropped

    def test_week_apps_days_clamped(self, pet_dir):
        # days outside 1..30 must not crash; result is a list
        assert isinstance(self._api(pet_dir).get_week_apps(0), list)

    def test_focus_peaks_empty(self, pet_dir):
        pk = self._api(pet_dir).get_focus_peaks(7)
        assert pk["totalSeconds"] == 0
        assert pk["best"] is None
        assert len(pk["hours"]) == 24
        assert all(h["seconds"] == 0 for h in pk["hours"])

    def test_focus_peaks_aggregates_hours(self, pet_dir):
        """Hour buckets across the window are summed per hour-of-day."""
        today = datetime.date.today()
        hour_hist = {}
        for back in range(3):
            day = (today - datetime.timedelta(days=back)).isoformat()
            hour_hist[day] = {9: 3600, 10: 1800}
        write(pet_dir, "wellbeing.json",
              {"date": today.isoformat(), "apps": {},
               "history": {}, "hourHistory": hour_hist})
        pk = self._api(pet_dir).get_focus_peaks(7)
        assert pk["totalSeconds"] == 3 * (3600 + 1800)
        by_hour = {h["hour"]: h["seconds"] for h in pk["hours"]}
        assert by_hour[9] == 3 * 3600
        assert by_hour[10] == 3 * 1800
        assert pk["best"]["hour"] == 9
        assert pk["best"]["label"] == "9 AM"
        assert pk["best"]["pct"] == 67
        assert pk["runnerUp"]["hour"] == 10

    def test_focus_peaks_folds_live_today(self, pet_dir):
        """Today's running hour buckets add into the window immediately."""
        today = datetime.date.today()
        write(pet_dir, "wellbeing.json",
              {"date": today.isoformat(), "apps": {},
               "history": {}, "hourHistory": {},
               "hourToday": {15: 5400}})
        pk = self._api(pet_dir).get_focus_peaks(7)
        assert pk["best"]["hour"] == 15
        assert pk["best"]["label"] == "3 PM"
        assert pk["totalSeconds"] == 5400

    def test_focus_peaks_ties_prefer_earliest_hour(self, pet_dir):
        """Ties resolve to the earliest hour (same rule as bestDay)."""
        today = datetime.date.today()
        write(pet_dir, "wellbeing.json",
              {"date": today.isoformat(), "apps": {},
               "history": {}, "hourHistory": {},
               "hourToday": {8: 3600, 20: 3600}})
        pk = self._api(pet_dir).get_focus_peaks(7)
        assert pk["best"]["hour"] == 8

    def test_focus_peaks_days_clamped(self, pet_dir):
        pk = self._api(pet_dir).get_focus_peaks(999)
        assert pk["days"] == 30
        pk = self._api(pet_dir).get_focus_peaks(0)
        assert pk["days"] == 1

    def test_evolution_stage_thresholds(self):
        assert main.evolution_stage(1)["id"] == "stage1"
        assert main.evolution_stage(7)["name"] == "Growing"
        assert main.evolution_stage(8)["id"] == "stage2"
        assert main.evolution_stage(12)["name"] == "Evolved"
        assert main.evolution_stage(15)["id"] == "stage3"
        # each stage carries a programmatic aura + a real-art sheet suffix
        assert all("aura" in s and "suffix" in s for s in map(main.evolution_stage, [1, 8, 15]))

    def test_pet_profile_includes_stage(self, pet_dir):
        write(pet_dir, "config.json", {"level": 12})
        p = self._api(pet_dir).get_pet_profile()
        assert p["stage"]["name"] == "Evolved"
        assert p["stage"]["emoji"]

    def test_engine_aura_renders_without_error(self, pet_dir, no_window):
        """The evolution aura glow builds for any level without crashing."""
        eng = main.PetEngine()
        eng.level = 1
        aura = eng._stage_aura()
        assert aura is not None and aura.size[0] > 0
        eng.level = 16
        assert eng._stage_aura() is not None


# ---------------------------------------------------------------- engine config watch

class TestConfigWatch:
    def test_quit_command(self, pet_dir, no_window, monkeypatch):
        eng = main.PetEngine()
        write(pet_dir, "config.json", {"quit": 1})
        exited = {}
        monkeypatch.setattr(main.os, "_exit", lambda code: exited.setdefault("code", code))
        eng.config_watch()
        assert "code" in exited

    def test_pet_switch_command(self, pet_dir, no_window):
        eng = main.PetEngine()
        write(pet_dir, "config.json", {"petIdx": 2})
        eng.config_watch()
        assert eng.pet["id"] == main.PETS[2]["id"]

    def test_walk_change(self, pet_dir, no_window):
        eng = main.PetEngine()
        write(pet_dir, "config.json", {"walk": 0})
        eng.config_watch()
        assert eng.walk_factor == 0.0

    def test_break_min_change(self, pet_dir, no_window):
        eng = main.PetEngine()
        write(pet_dir, "config.json", {"breakMin": 90})
        eng.config_watch()
        assert eng.break_min == 90

    def test_always_on_top_toggle(self, pet_dir, no_window, monkeypatch):
        eng = main.PetEngine()
        toggles = []
        monkeypatch.setattr(eng.win, "set_topmost", lambda on: toggles.append(on))
        write(pet_dir, "config.json", {"alwaysOnTop": False})
        eng.config_watch()
        assert toggles == [False]

    def test_hide_show_pet_commands(self, pet_dir, no_window, monkeypatch):
        eng = main.PetEngine()
        vis = []
        monkeypatch.setattr(eng.win, "show", lambda: vis.append(True))
        monkeypatch.setattr(eng.win, "hide", lambda: vis.append(False))
        write(pet_dir, "config.json", {"hidePet": 1})
        eng.config_watch()
        write(pet_dir, "config.json", {"showPet": 1})
        eng.config_watch()
        assert vis == [False, True]

    def test_corrupt_config_no_crash(self, pet_dir, no_window):
        eng = main.PetEngine()
        (pet_dir / "config.json").write_text("!!!", encoding="utf-8")
        eng.config_watch()  # must not raise
