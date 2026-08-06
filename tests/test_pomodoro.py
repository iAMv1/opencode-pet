"""Pomodoro cycle (P3a): focus-end logging and the tomato counter.

Mirrors the patterns in test_goal.py / test_config_status.py: plain pytest,
pet_dir fixture redirects the store constants, engine ticks are driven
directly (no window, no real OS polling).
"""

import json
import time

import pytest

main = pytest.importorskip("desktop.main")


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


def _eng(pet_dir, no_window):
    eng = main.PetEngine()
    eng.xp = 0
    eng.level = 1
    eng.mood = "neutral"
    eng._last_tool_earn = ""
    eng.bubble_until = 0
    return eng


def _complete(eng, minutes=25):
    eng.start_focus(minutes)
    eng.focus_started = time.time() - minutes * 60 - 1
    eng._focus_tick()


def kinds(rows):
    return [r["kind"] for r in rows]


# ---------------------------------------------------------------- focus-end logging

class TestFocusEndLogging:
    def test_complete_logs_focus_done_with_minutes_and_tag(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        _complete(eng, 25)
        done = [r for r in read_log(pet_dir, eng) if r["kind"] == "focusDone"]
        assert len(done) == 1
        assert done[0]["minutes"] == 25
        assert done[0]["tag"] == "Desktop"  # start_focus defaults to Desktop

    def test_manual_stop_logs_focus_end(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        eng.start_focus(45)
        eng.stop_focus()
        end = [r for r in read_log(pet_dir, eng) if r["kind"] == "focusEnd"]
        assert len(end) == 1
        assert end[0]["minutes"] == 45
        assert end[0]["completed"] is False

    def test_wilted_stop_logs_focus_wilt(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        eng.start_focus(25)
        eng.focus_wilted = True  # _focus_tick would have set this on app switch
        eng.stop_focus()
        wilt = [r for r in read_log(pet_dir, eng) if r["kind"] == "focusWilt"]
        assert len(wilt) == 1
        assert wilt[0]["minutes"] == 25

    def test_stop_after_complete_no_double_log(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        _complete(eng, 25)
        assert eng.stop_focus() is False  # session already ended
        done = [r for r in read_log(pet_dir, eng) if r["kind"] == "focusDone"]
        assert len(done) == 1

    def test_complete_via_stop_focus_logs_once(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        eng.start_focus(25)
        eng.stop_focus(completed=True)
        done = [r for r in read_log(pet_dir, eng) if r["kind"] == "focusDone"]
        assert len(done) == 1
        assert done[0]["minutes"] == 25


# ---------------------------------------------------------------- pomodoro cycle

class TestPomodoroCycle:
    def test_count_increments_on_complete(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        _complete(eng, 25)
        c = main.load_config()
        assert c["pomoCount"] == 1
        assert c["pomoDate"] == time.strftime("%Y-%m-%d")

    def test_no_increment_on_wilt_or_manual_stop(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        eng.start_focus(25)
        eng.focus_wilted = True
        eng.stop_focus()
        eng.start_focus(25)
        eng.stop_focus()
        assert main.load_config()["pomoCount"] == 0

    def test_rollover_resets_count(self, pet_dir, no_window):
        yesterday = time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400))
        write(pet_dir, "config.json", {"pomoCount": 7, "pomoDate": yesterday})
        eng = _eng(pet_dir, no_window)
        _complete(eng, 25)
        c = main.load_config()
        assert c["pomoCount"] == 1  # fresh day, cycle restarts
        assert c["pomoDate"] == time.strftime("%Y-%m-%d")

    def test_same_day_keeps_count(self, pet_dir, no_window):
        write(pet_dir, "config.json",
              {"pomoCount": 3, "pomoDate": time.strftime("%Y-%m-%d")})
        eng = _eng(pet_dir, no_window)
        _complete(eng, 25)
        assert main.load_config()["pomoCount"] == 4

    def test_fourth_gets_long_break_bubble(self, pet_dir, no_window):
        write(pet_dir, "config.json",
              {"pomoCount": 3, "pomoDate": time.strftime("%Y-%m-%d")})
        eng = _eng(pet_dir, no_window)
        _complete(eng, 25)
        assert main.load_config()["pomoCount"] == 4
        assert eng.bubble_text == "Pomodoro 4 done! Take a long break"

    def test_mid_cycle_gets_short_break_bubble(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        _complete(eng, 25)
        assert eng.bubble_text == "Pomodoro 1 done! Take a short break"

    def test_five_in_a_row_starts_new_cycle(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        for _ in range(5):
            _complete(eng, 25)
            eng.start_focus(25)
        assert main.load_config()["pomoCount"] == 5
        assert eng.bubble_text == "Pomodoro 5 done! Take a short break"


# ---------------------------------------------------------------- API

class TestPomoApi:
    def _api(self, pet_dir):
        return main.ControlApi()

    def test_pomo_state_defaults(self, pet_dir):
        p = self._api(pet_dir).get_pomo_state()
        assert p == {"count": 0, "nextIsLong": False,
                     "pomoMin": 25, "pomoShort": 5, "pomoLong": 15}

    def test_pomo_state_reflects_config(self, pet_dir):
        write(pet_dir, "config.json",
              {"pomoCount": 3, "pomoDate": time.strftime("%Y-%m-%d"),
               "pomoMin": 40, "pomoShort": 7, "pomoLong": 20})
        p = self._api(pet_dir).get_pomo_state()
        assert p["count"] == 3
        assert p["nextIsLong"] is True   # break after the 4th is long
        assert p["pomoMin"] == 40 and p["pomoShort"] == 7 and p["pomoLong"] == 20

    def test_pomo_next_long_parity(self, pet_dir):
        # every 4th completed session -> long break after the NEXT one
        for count in range(12):
            assert main.pomo_next_long(count) == ((count + 1) % 4 == 0)
        assert main.pomo_next_long(3) is True   # 4th -> long
        assert main.pomo_next_long(4) is False  # 5th -> short

    def test_pomo_state_parity_with_engine(self, pet_dir, no_window):
        """The dashboard's nextIsLong must agree with the engine's bubble rule
        after a completion."""
        write(pet_dir, "config.json",
              {"pomoCount": 3, "pomoDate": time.strftime("%Y-%m-%d")})
        eng = _eng(pet_dir, no_window)
        _complete(eng, 25)
        p = self._api(pet_dir).get_pomo_state()
        assert p["count"] == 4
        assert p["nextIsLong"] is False  # 5th's break is short again
        assert main.pomo_next_long(4) == p["nextIsLong"]
        assert "long break" in eng.bubble_text
