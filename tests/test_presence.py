"""P9: Companion Presence — the pet lives WITH the user's real workflow.

The pet already reads OS signals (last_input_ms, foreground_app) and agent
status files; P9 makes it REACT to them: typing-burst bounces, cursor-dwell
glances, app-change perch chatter, agent-state mirroring, and idle sitting.
Every reaction is config-gated (reactTyping / reactCursor / perchChatter /
agentMirror / wanderIdle) with cooldowns so it stays companionable, not
needy.
"""

import json
import time

import pytest

main = pytest.importorskip("desktop.main")
import desktop.engine as engine_mod  # noqa: E402
from conftest import make_sessions  # noqa: E402


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


def kinds(pet_dir, eng):
    return [e.get("kind") for e in read_log(pet_dir, eng)]


def _eng(pet_dir, no_window):
    eng = main.PetEngine()
    eng.xp = 0
    eng.level = 1
    eng.mood = "neutral"
    eng.bubble_until = 0
    eng.sessions = []
    return eng


# ---------------------------------------------------------------- typing burst

class TestTypingBurst:
    def _eng(self, pet_dir, no_window):
        return _eng(pet_dir, no_window)

    def test_no_fire_when_input_stale(self, pet_dir, no_window):
        eng = self._eng(pet_dir, no_window)
        eng._input_ms = engine_mod.TYPING_DELTA_MS + 1
        eng._typing_tick(1000.0)
        assert eng.mood == "neutral"
        assert eng.cast is None
        assert "typingBurst" not in kinds(pet_dir, eng)

    def test_no_fire_below_sustain_window(self, pet_dir, no_window):
        eng = self._eng(pet_dir, no_window)
        eng._input_ms = 100
        eng._typing_tick(1000.0)          # burst window opens
        eng._typing_tick(1000.0 + 10)     # only 10s sustained
        assert eng.mood == "neutral"
        assert eng._typing_burst is False

    def test_fires_after_sustained_burst(self, pet_dir, no_window, monkeypatch):
        monkeypatch.setattr(engine_mod.random, "random", lambda: 0.5)  # no bounce
        eng = self._eng(pet_dir, no_window)
        eng._input_ms = 100
        eng._typing_tick(1000.0)
        eng._typing_tick(1000.0 + engine_mod.TYPING_SUSTAIN_SECS + 1)
        assert eng._typing_burst is True
        assert eng.mood == "busy"
        assert eng.cast is None  # 0.5 >= 0.10 chance: no bounce this tick

    def test_bounce_fires_on_chance_with_cooldown(self, pet_dir, no_window, monkeypatch):
        monkeypatch.setattr(engine_mod.random, "random", lambda: 0.0)  # force the 10%
        eng = self._eng(pet_dir, no_window)
        eng._input_ms = 100
        eng._typing_tick(1000.0)
        eng._typing_tick(1000.0 + engine_mod.TYPING_SUSTAIN_SECS + 1)
        assert eng.cast is not None
        assert "typingBurst" in kinds(pet_dir, eng)
        log = [e for e in read_log(pet_dir, eng) if e.get("kind") == "typingBurst"]
        assert log[0]["secs"] >= engine_mod.TYPING_SUSTAIN_SECS

    def test_bounce_respects_two_minute_cooldown(self, pet_dir, no_window, monkeypatch):
        monkeypatch.setattr(engine_mod.random, "random", lambda: 0.0)
        eng = self._eng(pet_dir, no_window)
        eng._input_ms = 100
        eng._typing_tick(1000.0)
        eng._typing_tick(1000.0 + engine_mod.TYPING_SUSTAIN_SECS + 1)
        assert eng.cast is not None
        fired = eng._last_typing_bounce
        eng.cast = None
        eng._typing_tick(fired + 10)  # still bursting, inside the 2-min cooldown
        assert eng.cast is None
        assert len([e for e in read_log(pet_dir, eng)
                    if e.get("kind") == "typingBurst"]) == 1

    def test_burst_breaks_when_typing_stops(self, pet_dir, no_window):
        eng = self._eng(pet_dir, no_window)
        eng._input_ms = 100
        eng._typing_tick(1000.0)
        eng._typing_tick(1000.0 + engine_mod.TYPING_SUSTAIN_SECS + 1)
        assert eng._typing_burst is True
        eng._input_ms = 5000  # typing stops
        eng._typing_tick(2000.0)
        assert eng._typing_burst is False

    def test_disabled_config_is_silent(self, pet_dir, no_window):
        eng = self._eng(pet_dir, no_window)
        eng.cfg["reactTyping"] = False
        eng._input_ms = 100
        eng._typing_tick(1000.0)
        eng._typing_tick(1000.0 + engine_mod.TYPING_SUSTAIN_SECS + 1)
        assert eng.mood == "neutral"
        assert "typingBurst" not in kinds(pet_dir, eng)


# ---------------------------------------------------------------- cursor dwell

class TestCursorDwell:
    def _eng(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        eng.phys["x"], eng.phys["y"] = 100, 100
        eng.os_active = True
        return eng

    def _center(self, eng):
        w = eng.pet["frameW"] * eng.pet["scale"]
        h = eng.pet["frameH"] * eng.pet["scale"]
        return (int(eng.phys["x"] + w / 2), int(eng.phys["y"] + h / 2))

    def test_dwell_fires_after_five_seconds(self, pet_dir, no_window):
        eng = self._eng(pet_dir, no_window)
        cx, cy = self._center(eng)
        eng._cursor = (cx, cy)
        now = 1000.0
        eng._cursor_tick(now)                      # dwell starts
        eng._cursor_tick(now + engine_mod.CURSOR_DWELL_SECS + 1)
        assert eng._look_until > now               # the glance fired
        eng._look_until = time.time() + 5          # deterministic flip check
        assert eng._state() == "thinking"
        assert "cursorLook" in kinds(pet_dir, eng)

    def test_far_away_never_fires(self, pet_dir, no_window):
        eng = self._eng(pet_dir, no_window)
        eng._cursor = (5000, 5000)                 # miles away
        now = 1000.0
        eng._cursor_tick(now)
        eng._cursor_tick(now + engine_mod.CURSOR_DWELL_SECS + 1)
        assert eng._look_until == 0
        assert "cursorLook" not in kinds(pet_dir, eng)

    def test_once_per_three_minutes(self, pet_dir, no_window):
        eng = self._eng(pet_dir, no_window)
        cx, cy = self._center(eng)
        eng._cursor = (cx, cy)
        now = 1000.0
        eng._cursor_tick(now)
        eng._cursor_tick(now + engine_mod.CURSOR_DWELL_SECS + 1)
        assert eng._look_until > now
        fired = eng._last_cursor_look
        eng._look_until = 0
        eng._cursor_near_since = None              # re-dwell
        eng._cursor_tick(fired + 10)
        eng._cursor_tick(fired + engine_mod.CURSOR_DWELL_SECS + 11)
        assert eng._look_until == 0                # cooldown holds
        eng._cursor_tick(fired + engine_mod.CURSOR_LOOK_COOLDOWN + 1)
        eng._cursor_tick(fired + engine_mod.CURSOR_LOOK_COOLDOWN
                         + engine_mod.CURSOR_DWELL_SECS + 1)
        assert eng._look_until > 0                 # cooldown elapsed
        assert len([e for e in read_log(pet_dir, eng)
                    if e.get("kind") == "cursorLook"]) == 2

    def test_disabled_config_never_looks(self, pet_dir, no_window):
        eng = self._eng(pet_dir, no_window)
        eng.cfg["reactCursor"] = False
        cx, cy = self._center(eng)
        eng._cursor = (cx, cy)
        now = 1000.0
        eng._cursor_tick(now)
        eng._cursor_tick(now + engine_mod.CURSOR_DWELL_SECS + 1)
        assert eng._look_until == 0
        assert "cursorLook" not in kinds(pet_dir, eng)


# ---------------------------------------------------------------- perch chatter

class TestPerch:
    NOW = 1000000.0  # big base time: cooldowns are relative, not absolute

    def _eng(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        eng._perch_app = "Terminal"
        eng.os_app = "Terminal"
        return eng

    def test_app_change_bubbles_line_with_app_slot(self, pet_dir, no_window):
        eng = self._eng(pet_dir, no_window)
        eng.os_app = "VS Code"
        eng._perch_tick(self.NOW)
        assert eng.bubble_text and "VS Code" in eng.bubble_text
        assert eng.bubble_until > 0
        assert "perch" in kinds(pet_dir, eng)
        assert any("%s" in line for line in engine_mod.PetEngine.PERCH_LINES)

    def test_max_once_per_thirty_minutes(self, pet_dir, no_window):
        eng = self._eng(pet_dir, no_window)
        eng.os_app = "VS Code"
        eng._perch_tick(self.NOW)
        assert eng.bubble_text
        first = eng._last_perch
        eng.bubble_text = ""
        eng.os_app = "Chrome"                      # another app switch
        eng._perch_tick(first + 60)
        assert eng.bubble_text == ""               # inside the 30-min cooldown
        eng.os_app = "Edge"
        eng._perch_tick(first + engine_mod.PERCH_COOLDOWN_SECS + 1)
        assert eng.bubble_text and "Edge" in eng.bubble_text
        assert len([e for e in read_log(pet_dir, eng)
                    if e.get("kind") == "perch"]) == 2

    def test_same_app_never_rechatters(self, pet_dir, no_window):
        eng = self._eng(pet_dir, no_window)
        eng._perch_tick(self.NOW)                  # same app: nothing
        assert eng.bubble_text == ""
        assert "perch" not in kinds(pet_dir, eng)

    def test_disabled_config_is_silent(self, pet_dir, no_window):
        eng = self._eng(pet_dir, no_window)
        eng.cfg["perchChatter"] = False
        eng.os_app = "VS Code"
        eng._perch_tick(self.NOW)
        assert eng.bubble_text == ""
        assert "perch" not in kinds(pet_dir, eng)

    def test_first_observation_is_baseline(self, pet_dir, no_window):
        """The pet never chatters at boot: the first app seen is the baseline."""
        eng = _eng(pet_dir, no_window)
        eng.os_app = "VS Code"
        eng._perch_tick(self.NOW)
        assert eng.bubble_text == ""
        assert "perch" not in kinds(pet_dir, eng)


# ---------------------------------------------------------------- agent mirror

class TestAgentMirror:
    def _eng(self, pet_dir, no_window):
        return _eng(pet_dir, no_window)

    def test_error_transition_fires_concern(self, pet_dir, no_window):
        eng = self._eng(pet_dir, no_window)
        eng.update_sessions(make_sessions("busy"))
        eng.update_sessions(make_sessions("error"))
        assert eng.bubble_text in engine_mod.PetEngine.AGENT_ERROR_LINES
        assert eng.mood == "tired"
        assert "agentError" in kinds(pet_dir, eng)
        assert eng._state() == "error"             # the dot mirrors the agent

    def test_error_concern_max_once_per_fifteen_minutes(self, pet_dir, no_window):
        eng = self._eng(pet_dir, no_window)
        eng.update_sessions(make_sessions("busy"))
        eng.update_sessions(make_sessions("error"))
        assert "agentError" in kinds(pet_dir, eng)
        # within the cooldown: the generic reaction still bubbles, no new log
        eng.update_sessions(make_sessions("busy"))
        eng.update_sessions(make_sessions("error"))
        assert eng.bubble_text in engine_mod.PetEngine.REACTIONS["error"]
        assert len([e for e in read_log(pet_dir, eng)
                    if e.get("kind") == "agentError"]) == 1
        # past the cooldown: concern line again
        eng._last_agent_error = time.time() - engine_mod.AGENT_ERROR_COOLDOWN_SECS - 1
        eng.update_sessions(make_sessions("busy"))
        eng.update_sessions(make_sessions("error"))
        assert eng.bubble_text in engine_mod.PetEngine.AGENT_ERROR_LINES
        assert len([e for e in read_log(pet_dir, eng)
                    if e.get("kind") == "agentError"]) == 2

    def test_success_mirrors_with_cast_and_mood(self, pet_dir, no_window):
        eng = self._eng(pet_dir, no_window)
        eng.update_sessions(make_sessions("busy"))
        eng.update_sessions(make_sessions("success"))
        assert eng.mood == "happy"
        assert eng.cast is not None
        assert "agentSuccess" in kinds(pet_dir, eng)

    def test_disabled_mirror_keeps_old_reactions(self, pet_dir, no_window):
        eng = self._eng(pet_dir, no_window)
        eng.cfg["agentMirror"] = False
        eng.update_sessions(make_sessions("busy"))
        eng.update_sessions(make_sessions("error"))
        assert eng.bubble_text in engine_mod.PetEngine.REACTIONS["error"]
        assert eng.mood == "neutral"               # no mood mirror
        assert "agentError" not in kinds(pet_dir, eng)
        eng.update_sessions(make_sessions("busy"))
        eng.update_sessions(make_sessions("success"))
        assert eng.cast is None
        assert eng.mood == "neutral"
        assert "agentSuccess" not in kinds(pet_dir, eng)

    def test_thinking_lines_are_mirror_copy(self, pet_dir, no_window):
        eng = self._eng(pet_dir, no_window)
        eng._last_bubble_state = None
        line = eng._personality("thinking", now=time.time())
        assert line in engine_mod.PetEngine.AGENT_MIRROR_LINES
        eng.cfg["agentMirror"] = False
        eng._last_bubble_state = None
        line = eng._personality("thinking", now=time.time())
        assert line in engine_mod.PetEngine.BUBBLES["thinking"]
        assert line not in engine_mod.PetEngine.AGENT_MIRROR_LINES


# ---------------------------------------------------------------- wander idle

class TestWanderIdle:
    def _eng(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        eng.sessions = []
        return eng

    def test_sits_waiting_after_two_minutes_idle(self, pet_dir, no_window):
        eng = self._eng(pet_dir, no_window)
        eng.os_active = False
        eng._idle_since = time.time() - engine_mod.WANDER_IDLE_SIT_SECS - 1
        assert eng._state() == "waiting"

    def test_active_never_sits(self, pet_dir, no_window):
        eng = self._eng(pet_dir, no_window)
        eng.os_active = True
        eng._idle_since = time.time() - 10000
        assert eng._state() == "busy"

    def test_short_idle_keeps_idle_pose(self, pet_dir, no_window):
        eng = self._eng(pet_dir, no_window)
        eng.os_active = False
        eng._idle_since = time.time() - 10
        assert eng._state() == "idle"

    def test_disabled_wander_keeps_idle_pose(self, pet_dir, no_window):
        eng = self._eng(pet_dir, no_window)
        eng.cfg["wanderIdle"] = False
        eng.os_active = False
        eng._idle_since = time.time() - engine_mod.WANDER_IDLE_SIT_SECS - 1
        assert eng._state() == "idle"

    def test_app_change_walk_steps_toward_side(self, pet_dir, no_window, monkeypatch):
        monkeypatch.setattr(engine_mod.random, "random", lambda: 0.0)   # fire the 20%
        monkeypatch.setattr(engine_mod.random, "choice", lambda seq: 1)
        eng = self._eng(pet_dir, no_window)
        eng._perch_app = "Terminal"
        eng.os_app = "Terminal"
        eng.phys["vx"] = 0
        eng.os_app = "VS Code"
        eng._perch_tick(1000.0)
        assert eng.phys["mode"] == "walk"
        assert eng.phys["vx"] > 0
        assert "wanderSide" in kinds(pet_dir, eng)

    def test_app_change_walk_flips_direction(self, pet_dir, no_window, monkeypatch):
        monkeypatch.setattr(engine_mod.random, "random", lambda: 0.0)
        eng = self._eng(pet_dir, no_window)
        eng._perch_app = "Terminal"
        eng.os_app = "Terminal"
        eng.phys["vx"] = 3.0                       # walking right
        eng.os_app = "VS Code"
        eng._perch_tick(1000.0)
        assert eng.phys["vx"] < 0                  # flipped toward the other side

    def test_app_change_walk_skipped_when_no_wander(self, pet_dir, no_window, monkeypatch):
        monkeypatch.setattr(engine_mod.random, "random", lambda: 0.0)
        eng = self._eng(pet_dir, no_window)
        eng.cfg["wanderIdle"] = False
        eng._perch_app = "Terminal"
        eng.os_app = "Terminal"
        eng.phys["vx"] = 0
        eng.os_app = "VS Code"
        eng._perch_tick(1000.0)
        assert eng.phys["mode"] != "walk"
        assert "wanderSide" not in kinds(pet_dir, eng)

    def test_app_change_walk_respects_walk_factor(self, pet_dir, no_window, monkeypatch):
        monkeypatch.setattr(engine_mod.random, "random", lambda: 0.0)
        eng = self._eng(pet_dir, no_window)
        eng.walk_factor = 0.0                      # user set walking to 0%
        eng._perch_app = "Terminal"
        eng.os_app = "Terminal"
        eng.phys["vx"] = 0
        eng.os_app = "VS Code"
        eng._perch_tick(1000.0)
        assert eng.phys["mode"] != "walk"


# ---------------------------------------------------------------- toggles + wiring

class TestTogglesAndWiring:
    def test_config_defaults(self, pet_dir):
        c = main.load_config()
        for k in ("reactTyping", "reactCursor", "perchChatter", "agentMirror", "wanderIdle"):
            assert c.get(k) is True

    def test_config_watch_applies_toggles_live(self, pet_dir, no_window):
        eng = main.PetEngine()
        write(pet_dir, "config.json", {"reactTyping": False, "agentMirror": False})
        eng.config_watch()
        assert eng.cfg["reactTyping"] is False
        assert eng.cfg["agentMirror"] is False
        write(pet_dir, "config.json", {"reactTyping": True})
        eng.config_watch()
        assert eng.cfg["reactTyping"] is True

    def test_update_activity_feeds_presence_signals(self, pet_dir, no_window, monkeypatch):
        monkeypatch.setattr(main, "last_input_ms", lambda: 100)
        monkeypatch.setattr(main, "foreground_app", lambda: "VS Code")
        monkeypatch.setattr(main, "cursor_pos", lambda: (300, 400))
        eng = main.PetEngine()
        eng._last_act = 0.0
        eng._wb_t = time.time() - 10
        eng.update_activity()
        assert eng._input_ms == 100
        assert eng._cursor == (300, 400)
        assert eng._perch_app == "VS Code"         # baseline captured

    def test_all_log_kinds_written(self, pet_dir, no_window, monkeypatch):
        """Every P9 reaction leaves a log line for the dashboard."""
        monkeypatch.setattr(engine_mod.random, "random", lambda: 0.0)
        monkeypatch.setattr(engine_mod.random, "choice", lambda seq: seq[0])
        eng = _eng(pet_dir, no_window)
        now = 1000000.0
        # typing burst
        eng._input_ms = 100
        eng._typing_tick(now)
        eng._typing_tick(now + engine_mod.TYPING_SUSTAIN_SECS + 1)
        # cursor look
        eng.os_active = True
        eng.phys["x"], eng.phys["y"] = 100, 100
        w = eng.pet["frameW"] * eng.pet["scale"]
        h = eng.pet["frameH"] * eng.pet["scale"]
        eng._cursor = (int(100 + w / 2), int(100 + h / 2))
        eng._cursor_tick(now + 1000)
        eng._cursor_tick(now + 1000 + engine_mod.CURSOR_DWELL_SECS + 1)
        # perch + app-change walk
        eng._perch_app = "Terminal"
        eng.os_app = "VS Code"
        eng._perch_tick(now + 2000)
        # agent error + success
        eng.update_sessions(make_sessions("busy"))
        eng.update_sessions(make_sessions("error"))
        eng._last_agent_error = time.time() - engine_mod.AGENT_ERROR_COOLDOWN_SECS - 1
        eng.update_sessions(make_sessions("busy"))
        eng.update_sessions(make_sessions("success"))
        got = kinds(pet_dir, eng)
        for k in ("typingBurst", "cursorLook", "perch", "wanderSide",
                  "agentError", "agentSuccess"):
            assert k in got, "missing log kind %r in %r" % (k, got)
