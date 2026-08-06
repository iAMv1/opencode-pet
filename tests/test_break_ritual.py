"""P3b: break snooze + ritual, stretch nudge, session tags, native chimes.

Mirrors the patterns in test_pomodoro.py / test_goal.py: plain pytest,
pet_dir fixture redirects the store constants, engine ticks are driven
directly (no window, no real OS polling). The autouse _silent_chimes fixture
records winsound.Beep into desktop.sounds._TEST_BEEPS instead of beeping.
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


def _beeps():
    import desktop.sounds as sounds
    return list(getattr(sounds, "_TEST_BEEPS", []) or [])


# ---------------------------------------------------------------- break snooze

class TestBreakSnooze:
    def test_config_watch_consumes_snooze_key_once(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        write(pet_dir, "config.json", {"breakSnooze": 5})
        eng.config_watch()
        assert eng._snooze_min == 5
        c = json.loads((pet_dir / "config.json").read_text(encoding="utf-8"))
        assert "breakSnooze" not in c  # one-shot: deleted after consume

    def test_snooze_postpones_nudge_and_logs(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        eng.break_min = 1
        write(pet_dir, "config.json", {"breakSnooze": 5})
        eng.config_watch()
        eng.os_active = True
        eng.break_track_start = time.time() - 61  # nudge is due
        now = time.time()
        eng._break_nudge(now)
        # deferred, not nudged: no break log, no mood flip, bubble is the deferral
        assert "Snoozed 5 min" in eng.bubble_text
        assert eng._snooze_min == 0
        assert eng.mood != "tired"
        rows = read_log(pet_dir, eng)
        snoozes = [r for r in rows if r["kind"] == "breakSnooze"]
        assert len(snoozes) == 1 and snoozes[0]["mins"] == 5
        assert not [r for r in rows if r["kind"] == "break"]
        # clock re-armed: still quiet just before the snooze window ends
        eng._break_nudge(now + 240)
        assert [r for r in read_log(pet_dir, eng) if r["kind"] == "break"] == []
        # nudge finally fires after the snooze window (5 min + cooldown margin)
        eng._break_nudge(now + 361)
        assert [r for r in read_log(pet_dir, eng) if r["kind"] == "break"]
        assert "Time for a break" in eng.bubble_text

    def test_snooze_does_not_retrigger_next_tick(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        eng.break_min = 1
        write(pet_dir, "config.json", {"breakSnooze": 5})
        eng.config_watch()
        eng.os_active = True
        eng.break_track_start = time.time() - 61
        now = time.time()
        eng._break_nudge(now)
        eng._break_nudge(now + 1.0)  # immediately after: still deferred
        assert not [r for r in read_log(pet_dir, eng) if r["kind"] == "break"]

    def test_snooze_arms_from_control_save(self, pet_dir, no_window):
        """The control UI writes the one-shot via save_config; the pet's own
        merged saves must not clobber it before config_watch consumes it."""
        api = main.ControlApi()
        api.save_config({"breakSnooze": 5})
        c = json.loads((pet_dir / "config.json").read_text(encoding="utf-8"))
        assert c.get("breakSnooze") == 5


# ---------------------------------------------------------------- stretch nudge

class TestStretch:
    def _active(self, pet_dir, no_window, stretch_min=45):
        eng = _eng(pet_dir, no_window)
        eng.stretch_min = stretch_min
        return eng

    def test_fires_at_threshold_awards_xp_and_logs(self, pet_dir, no_window):
        eng = self._active(pet_dir, no_window, stretch_min=1)
        eng.os_active = True
        eng._stretch_start = time.time() - 61  # 1 min of continuous work
        eng._last_break = 0.0
        eng._stretch_nudge(time.time())
        assert eng.bubble_text == "Stretch! Neck + shoulders \U0001f9d8"
        assert eng.xp == 2
        stretch = [r for r in read_log(pet_dir, eng) if r["kind"] == "stretch"]
        assert len(stretch) == 1 and stretch[0]["mins"] == 1

    def test_does_not_fire_before_threshold(self, pet_dir, no_window):
        eng = self._active(pet_dir, no_window, stretch_min=45)
        eng.os_active = True
        eng._stretch_start = time.time() - 60  # 1 min < 45 min
        eng._stretch_nudge(time.time())
        assert eng.xp == 0
        assert not [r for r in read_log(pet_dir, eng) if r["kind"] == "stretch"]

    def test_cooldown_limits_to_one_per_30min(self, pet_dir, no_window):
        eng = self._active(pet_dir, no_window, stretch_min=1)
        eng.os_active = True
        eng._stretch_start = time.time() - 61
        eng._stretch_nudge(time.time())
        assert eng.xp == 2
        # threshold met again but the 30-min cooldown is active
        eng._stretch_start = time.time() - 61
        eng._stretch_nudge(time.time())
        assert eng.xp == 2
        assert len([r for r in read_log(pet_dir, eng) if r["kind"] == "stretch"]) == 1
        # cooldown elapsed -> fires again
        eng._last_stretch = time.time() - 1801
        eng._stretch_start = time.time() - 61
        eng._stretch_nudge(time.time())
        assert eng.xp == 4
        assert len([r for r in read_log(pet_dir, eng) if r["kind"] == "stretch"]) == 2

    def test_off_when_zero(self, pet_dir, no_window):
        eng = self._active(pet_dir, no_window, stretch_min=0)
        eng.os_active = True
        eng._stretch_start = time.time() - 7200
        eng._stretch_nudge(time.time())
        assert eng.xp == 0
        assert eng.bubble_text == ""

    def test_idle_resets_clock(self, pet_dir, no_window):
        eng = self._active(pet_dir, no_window, stretch_min=1)
        eng.os_active = True
        eng._stretch_start = time.time() - 61
        eng.os_active = False
        eng._stretch_nudge(time.time())
        assert eng._stretch_start is None  # idle: clock cleared

    def test_config_watch_syncs_stretch_min(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        write(pet_dir, "config.json", {"stretchMin": 90})
        eng.config_watch()
        assert eng.stretch_min == 90
        write(pet_dir, "config.json", {"stretchMin": 0})
        eng.config_watch()
        assert eng.stretch_min == 0


# ---------------------------------------------------------------- session tags

class TestSessionTags:
    def _api(self, pet_dir):
        return main.ControlApi()

    def test_set_tag_writes_focus_json_when_active(self, pet_dir, no_window):
        api = self._api(pet_dir)
        eng = _eng(pet_dir, no_window)
        eng.start_focus(25)
        assert api.set_focus_tag("Study") is True
        d = json.loads((pet_dir / "focus.json").read_text(encoding="utf-8"))
        assert d["tag"] == "Study"
        fs = api.get_focus_state()
        assert fs["active"] is True and fs["tag"] == "Study"

    def test_set_tag_refused_when_inactive(self, pet_dir, no_window):
        api = self._api(pet_dir)
        assert api.set_focus_tag("Work") is False
        fs = api.get_focus_state()
        assert fs["active"] is False and fs["tag"] == ""

    def test_focus_done_log_uses_stored_tag(self, pet_dir, no_window):
        api = self._api(pet_dir)
        eng = _eng(pet_dir, no_window)
        eng.start_focus(25)
        api.set_focus_tag("Write")
        eng.focus_started = time.time() - 25 * 60 - 1
        eng._focus_tick()
        done = [r for r in read_log(pet_dir, eng) if r["kind"] == "focusDone"]
        assert len(done) == 1
        assert done[0]["tag"] == "Write"

    def test_tag_resets_on_end(self, pet_dir, no_window):
        api = self._api(pet_dir)
        eng = _eng(pet_dir, no_window)
        eng.start_focus(25)
        api.set_focus_tag("Work")
        eng.stop_focus()
        fs = api.get_focus_state()
        assert fs["active"] is False and fs["tag"] == ""
        d = json.loads((pet_dir / "focus.json").read_text(encoding="utf-8"))
        assert d["tag"] == ""

    def test_new_session_starts_untagged(self, pet_dir, no_window):
        api = self._api(pet_dir)
        eng = _eng(pet_dir, no_window)
        eng.start_focus(25)
        api.set_focus_tag("Work")
        eng.stop_focus()
        eng.start_focus(25)  # fresh session must not inherit the old tag
        d = json.loads((pet_dir / "focus.json").read_text(encoding="utf-8"))
        assert d["active"] is True and d["tag"] == ""

    def test_default_tag_is_app(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        eng.start_focus(25)
        eng.focus_started = time.time() - 25 * 60 - 1
        eng._focus_tick()
        done = [r for r in read_log(pet_dir, eng) if r["kind"] == "focusDone"]
        assert done[0]["tag"] == "Desktop"  # no tag set -> falls back to the app


# ---------------------------------------------------------------- native chimes

class TestChimes:
    def test_play_patterns_per_event(self, pet_dir, no_window):
        import desktop.sounds as sounds
        sounds.play("start")
        assert _beeps() == [(523, 80), (784, 80)]
        sounds.play("complete")
        assert _beeps() == [(523, 80), (784, 80), (523, 80), (659, 80), (784, 120)]
        sounds.play("break")
        assert _beeps()[-1] == (262, 120)
        sounds.play("stretch")
        assert _beeps()[-1] == (440, 100)
        sounds.play("unknown-kind")  # silently ignored
        assert len(_beeps()) == 7

    def test_start_focus_chimes(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        eng.start_focus(25)
        assert _beeps() == [(523, 80), (784, 80)]

    def test_complete_chimes(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        eng.start_focus(25)
        eng.focus_started = time.time() - 25 * 60 - 1
        eng._focus_tick()
        assert _beeps()[-3:] == [(523, 80), (659, 80), (784, 120)]

    def test_break_nudge_chimes(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        eng.break_min = 1
        eng.os_active = True
        eng.break_track_start = time.time() - 61
        eng._break_nudge(time.time())
        assert _beeps()[-1] == (262, 120)

    def test_stretch_chimes(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        eng.stretch_min = 1
        eng.os_active = True
        eng._stretch_start = time.time() - 61
        eng._stretch_nudge(time.time())
        assert _beeps()[-1] == (440, 100)

    def test_disabled_by_config(self, pet_dir, no_window):
        write(pet_dir, "config.json", {"chimes": False})
        eng = main.PetEngine()
        assert eng.chimes_on is False
        eng.start_focus(25)
        eng.focus_started = time.time() - 25 * 60 - 1
        eng._focus_tick()
        assert _beeps() == []  # no tones at all

    def test_config_watch_syncs_chimes(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        write(pet_dir, "config.json", {"chimes": False})
        eng.config_watch()
        assert eng.chimes_on is False
        write(pet_dir, "config.json", {"chimes": True})
        eng.config_watch()
        assert eng.chimes_on is True
