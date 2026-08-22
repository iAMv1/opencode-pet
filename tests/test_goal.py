"""Daily focus goal (F1): config keys, get_goal_state API, and the pet's
once-per-day celebration. Mirrors the patterns in test_config_status.py.
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


def _drive(eng):
    """One update_activity tick with deterministic OS state."""
    eng._last_act = 0.0  # bypass the 0.5s throttle so consecutive ticks run
    eng._wb_t = time.time() - 10
    eng.update_activity()


def _active_engine(pet_dir, no_window, monkeypatch):
    monkeypatch.setattr(main, "last_input_ms", lambda: 0)
    monkeypatch.setattr(main, "foreground_app", lambda: "VS Code")
    eng = main.PetEngine()
    eng.xp = 0
    eng.level = 1
    eng.mood = "neutral"
    eng._last_act = 0.0
    eng.sessions = []
    eng.bubble_until = 0
    eng._wb = {"VS Code": 7500}  # > 120min goal (7200s)
    return eng


# ---------------------------------------------------------------- config

class TestGoalConfig:
    def test_defaults_when_missing(self, pet_dir):
        c = main.load_config()
        assert c["goalMin"] == 120
        assert c["lastGoalDate"] == ""

    def test_save_load_roundtrip(self, pet_dir):
        main.save_config({"goalMin": 45, "lastGoalDate": "2026-08-05"})
        c = main.load_config()
        assert c["goalMin"] == 45
        assert c["lastGoalDate"] == "2026-08-05"

    def test_engine_loads_goal_from_config(self, pet_dir, no_window):
        write(pet_dir, "config.json", {"goalMin": 45, "lastGoalDate": "2026-08-05"})
        eng = main.PetEngine()
        assert eng.goal_min == 45
        assert eng._last_goal_date == "2026-08-05"

    def test_config_watch_syncs_goal_min(self, pet_dir, no_window):
        eng = main.PetEngine()
        write(pet_dir, "config.json", {"goalMin": 45})
        eng.config_watch()
        assert eng.goal_min == 45


# ---------------------------------------------------------------- API

class TestGoalApi:
    def _api(self, pet_dir):
        return main.ControlApi()

    def test_goal_state_defaults(self, pet_dir):
        g = self._api(pet_dir).get_goal_state()
        assert g == {"goalMin": 120, "todaySeconds": 0, "met": False, "streak": 0}

    def test_goal_state_folds_today(self, pet_dir):
        write(pet_dir, "wellbeing.json",
              {"date": time.strftime("%Y-%m-%d"),
               "apps": {"VS Code": 8000}, "history": {}})
        g = self._api(pet_dir).get_goal_state()
        assert g["todaySeconds"] == 8000
        assert g["met"] is True

    def test_goal_state_not_met(self, pet_dir):
        write(pet_dir, "wellbeing.json",
              {"date": time.strftime("%Y-%m-%d"),
               "apps": {"VS Code": 3600}, "history": {}})
        g = self._api(pet_dir).get_goal_state()
        assert g["todaySeconds"] == 3600
        assert g["met"] is False

    def test_goal_state_uses_config_goal_min(self, pet_dir):
        write(pet_dir, "config.json", {"goalMin": 30})
        write(pet_dir, "wellbeing.json",
              {"date": time.strftime("%Y-%m-%d"),
               "apps": {"VS Code": 1800}, "history": {}})
        g = self._api(pet_dir).get_goal_state()
        assert g["goalMin"] == 30
        assert g["met"] is True  # 1800s >= 30*60

    def test_goal_state_missing_wellbeing(self, pet_dir):
        g = self._api(pet_dir).get_goal_state()
        assert g["todaySeconds"] == 0 and g["met"] is False

    def test_goal_streak_counts_goal_days(self, pet_dir):
        today = datetime.date.today()
        hist = {}
        for back in range(1, 4):
            hist[(today - datetime.timedelta(days=back)).isoformat()] = 7200
        hist[(today - datetime.timedelta(days=4)).isoformat()] = 3600  # below goal: breaks chain
        write(pet_dir, "wellbeing.json",
              {"date": today.isoformat(), "apps": {"VS Code": 8000},
               "history": hist})
        g = self._api(pet_dir).get_goal_state()
        assert g["streak"] == 4  # today + 3 prior goal days

    def test_streak_threshold_default_unchanged(self, pet_dir):
        """Parameterizing streak_from_history must not change the 30min rule."""
        today = datetime.date.today()
        hist = {day.isoformat(): 1800 for day in
                [today, today - datetime.timedelta(days=1)]}
        assert main.streak_from_history(hist) == 2  # 30min days count at default
        assert main.streak_from_history(hist, 30 * 60) == 2
        assert main.streak_from_history(hist, 7200) == 0  # ...but not for a 2h goal

    def test_fold_today_returns_copy(self, pet_dir):
        history = {"2026-08-04": 3600}
        d = {"date": time.strftime("%Y-%m-%d"), "apps": {"VS Code": 1800}}
        folded = main._fold_today(history, d)
        assert folded != history  # new dict, caller's history untouched
        assert history == {"2026-08-04": 3600}
        assert folded[time.strftime("%Y-%m-%d")] == 1800

    def test_fold_today_skips_previous_day(self, pet_dir):
        history = {"2026-08-04": 3600}
        d = {"date": "2026-08-04", "apps": {"VS Code": 1800}}
        assert main._fold_today(history, d) == history


# ---------------------------------------------------------------- engine celebration

class TestGoalEngine:
    def test_met_awards_xp_once(self, pet_dir, no_window, monkeypatch):
        eng = _active_engine(pet_dir, no_window, monkeypatch)
        _drive(eng)
        assert eng.xp == 20
        assert eng.bubble_text == "Daily goal met!"
        assert main.load_config()["lastGoalDate"] == time.strftime("%Y-%m-%d")
        # second tick: same day, no re-award
        _drive(eng)
        assert eng.xp == 20

    def test_not_met_no_award(self, pet_dir, no_window, monkeypatch):
        eng = _active_engine(pet_dir, no_window, monkeypatch)
        eng._wb = {"VS Code": 3600}  # under the 2h goal
        _drive(eng)
        assert eng.xp == 0
        assert "Daily goal met!" not in eng.bubble_text

    def test_restart_with_yesterday_goal_met_awards(self, pet_dir, no_window, monkeypatch):
        """Simulated restart: config says the goal was met yesterday, so today
        is a fresh chance — the pet must celebrate again."""
        yesterday = time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400))
        write(pet_dir, "config.json", {"goalMin": 120, "lastGoalDate": yesterday})
        eng = _active_engine(pet_dir, no_window, monkeypatch)
        assert eng._last_goal_date == yesterday
        _drive(eng)
        assert eng.xp == 20
        assert main.load_config()["lastGoalDate"] == time.strftime("%Y-%m-%d")

    def test_restart_with_today_goal_met_no_reaward(self, pet_dir, no_window, monkeypatch):
        """Simulated restart after the goal was already met today: the
        lastGoalDate guard must survive the restart."""
        write(pet_dir, "config.json",
              {"goalMin": 120, "lastGoalDate": time.strftime("%Y-%m-%d")})
        eng = _active_engine(pet_dir, no_window, monkeypatch)
        _drive(eng)
        assert eng.xp == 0
        assert "Daily goal met!" not in eng.bubble_text

    def test_goal_celebration_sets_cast_flash(self, pet_dir, no_window, monkeypatch):
        eng = _active_engine(pet_dir, no_window, monkeypatch)
        # Freeze the clock: the cast flash lasts GOAL_CAST_SECS (1s), so a slow
        # tick under load can otherwise let it expire before we assert.
        frozen = time.time()
        monkeypatch.setattr(time, "time", lambda: frozen)
        _drive(eng)
        assert eng.cast is not None and eng.cast.get("until", 0) > frozen
        assert eng.mood == "happy"
