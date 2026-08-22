"""Random-idea features: weekday spirit + time-warp echo."""

import datetime
import time

from desktop import api, main, store


def _engine(pet_dir, no_window, monkeypatch):
    monkeypatch.setattr(main, "last_input_ms", lambda: 0)
    monkeypatch.setattr(main, "foreground_app", lambda: "VS Code")
    eng = main.PetEngine()
    eng.xp = 0
    eng.level = 1
    eng.mood = "neutral"
    eng.bubble_until = 0
    eng.sessions = []
    return eng


class TestWeekdayLine:
    def test_line_exists_for_every_weekday(self):
        for w in range(7):
            assert store.weekday_line(w)

    def test_unknown_weekday_is_none(self):
        assert store.weekday_line(99) is None


class TestWeekdayTick:
    def test_fires_once_per_day(self, pet_dir, no_window, monkeypatch):
        eng = _engine(pet_dir, no_window, monkeypatch)
        eng._weekday_tick(1000.0)
        assert eng.bubble_text == store.weekday_line(time.localtime().tm_wday)
        eng.bubble_text = ""
        eng._weekday_tick(1000.5)
        assert eng.bubble_text == ""  # in-memory guard: once per day

    def test_logs_weekday_kind(self, pet_dir, no_window, monkeypatch, tmp_path):
        eng = _engine(pet_dir, no_window, monkeypatch)
        eng._weekday_tick(1000.0)
        log = eng._read_memory_events(50)
        assert any(e.get("kind") == "weekday" for e in log)


class TestEchoTick:
    def _echo_engine(self, pet_dir, no_window, monkeypatch):
        eng = _engine(pet_dir, no_window, monkeypatch)
        eng.os_active = True
        key = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
        eng._hour_history = {key: {time.localtime().tm_hour: 1800}}
        eng._app_history = {key: {"Terminal": 1200, "Brave": 600}}
        eng._echo_at = 0
        return eng

    def test_fires_with_seven_day_old_data(self, pet_dir, no_window, monkeypatch):
        eng = self._echo_engine(pet_dir, no_window, monkeypatch)
        eng._echo_tick(1000.0)
        assert eng.bubble_text and "Terminal" in eng.bubble_text
        assert "This time last week" in eng.bubble_text

    def test_silent_without_data(self, pet_dir, no_window, monkeypatch):
        eng = self._echo_engine(pet_dir, no_window, monkeypatch)
        eng._hour_history = {}
        eng._app_history = {}
        eng._echo_tick(1000.0)
        assert eng.bubble_text == ""

    def test_silent_below_min_seconds(self, pet_dir, no_window, monkeypatch):
        eng = self._echo_engine(pet_dir, no_window, monkeypatch)
        key = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
        eng._hour_history = {key: {time.localtime().tm_hour: 60}}
        eng._echo_tick(1000.0)
        assert eng.bubble_text == ""

    def test_cooldown(self, pet_dir, no_window, monkeypatch):
        eng = self._echo_engine(pet_dir, no_window, monkeypatch)
        eng._echo_tick(1000.0)
        assert eng.bubble_text
        eng.bubble_text = ""
        eng._echo_tick(1000.0 + 3600)
        assert eng.bubble_text == ""  # 1h < ECHO_COOLDOWN_SECS (2h)

    def test_echo_after_cooldown(self, pet_dir, no_window, monkeypatch):
        eng = self._echo_engine(pet_dir, no_window, monkeypatch)
        eng._echo_tick(1000.0)
        eng.bubble_text = ""
        eng._echo_tick(1000.0 + 14400)
        assert eng.bubble_text

    def test_silent_when_idle(self, pet_dir, no_window, monkeypatch):
        eng = self._echo_engine(pet_dir, no_window, monkeypatch)
        eng.os_active = False
        eng._echo_tick(1000.0)
        assert eng.bubble_text == ""
