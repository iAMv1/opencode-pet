"""State-machine tests: how sessions map to pet emotions and animations.

Covers the known emotion-system bugs (EMOTION_BUGS.md) that are fixed in code,
plus the stale-emotion capture path in update_sessions().
"""

import time

import pytest

main = pytest.importorskip("desktop.main")
from conftest import make_sessions  # noqa: E402


def make_engine(pet_idx=0, sessions=None, os_active=False, **kw):
    eng = object.__new__(main.PetEngine)
    eng.pet = main.PETS[pet_idx]
    eng.sessions = sessions if sessions is not None else []
    eng.os_active = os_active
    eng._stale_emotion = kw.get("stale_emotion")
    eng.attention_until = kw.get("attention_until", 0.0)
    eng.phys = kw.get("phys") or {
        "x": 0, "y": 0, "vx": 0, "vy": 0,
        "grounded": True, "mode": "idle", "t": 0, "walkT": 0, "spawned": True,
    }
    return eng


# ---------------------------------------------------------------- _state()

class TestState:
    def test_fresh_session_returns_raw_state(self):
        eng = make_engine(sessions=make_sessions("thinking"))
        assert eng._state() == "thinking"

    def test_fresh_error_state(self):
        eng = make_engine(sessions=make_sessions("error"))
        assert eng._state() == "error"

    def test_stale_session_uses_preserved_emotion(self):
        eng = make_engine(sessions=make_sessions("error", stale=True),
                          stale_emotion="error")
        assert eng._state() == "error"

    def test_no_sessions_os_active_is_busy(self):
        assert make_engine(os_active=True)._state() == "busy"

    def test_no_sessions_os_idle_is_idle(self):
        """With no driving session and the screen idle, the pet settles into a
        calm idle rest (not the restless 'waiting' gait)."""
        assert make_engine(os_active=False)._state() == "idle"

    def test_null_state_maps_to_idle(self):
        eng = make_engine(sessions=[{"state": None, "stale": False,
                                     "updatedAt": int(time.time() * 1000)}])
        assert eng._state() == "idle"

    def test_stale_top_session_preserves_emotion_through_transition(self, no_window, pet_dir):
        """BUG-3 regression: a fresh->stale transition must NOT collapse to
        busy/waiting. The pet should keep showing the last real emotion."""
        eng = main.PetEngine()
        fresh = make_sessions("error")[0]
        eng.update_sessions([fresh])
        assert eng._state() == "error"
        # same session object, now flagged stale by read_status()
        stale = dict(fresh, stale=True)
        eng.update_sessions([stale])
        assert eng._state() == "error", (
            "stale transition lost the error emotion (falls back to busy/waiting)"
        )

    def test_new_fresh_session_clears_preserved_emotion(self, no_window, pet_dir):
        eng = main.PetEngine()
        eng.update_sessions([make_sessions("error")[0]])
        eng.update_sessions([dict(make_sessions("error")[0], stale=True)])
        assert eng._state() == "error"
        eng.update_sessions([make_sessions("busy")[0]])
        assert eng._state() == "busy"

    def test_session_deleted_preserves_emotion(self, no_window, pet_dir):
        eng = main.PetEngine()
        eng.update_sessions([make_sessions("error")[0]])
        eng.update_sessions([])  # file pruned entirely
        assert eng._state() == "error"


# ---------------------------------------------------------------- _anim_id()

class TestAnimId:
    def test_idle_maps_to_idle(self):
        eng = make_engine(sessions=make_sessions("idle"))
        assert eng._anim_id() == "idle"

    def test_no_sessions_os_idle_shows_idle(self):
        """Screen idle + no session => the pet rests in its idle animation."""
        assert make_engine(os_active=False)._anim_id() == "idle"

    def test_busy_maps_to_walking_for_standard_pet(self):
        eng = make_engine(sessions=make_sessions("busy"))
        assert eng._anim_id() == "walking"

    def test_error_maps_to_failed(self):
        eng = make_engine(sessions=make_sessions("error"))
        assert eng._anim_id() == "failed"

    def test_success_maps_to_jumping(self):
        eng = make_engine(sessions=make_sessions("success"))
        assert eng._anim_id() == "jumping"

    def test_thinking_maps_to_review(self):
        eng = make_engine(sessions=make_sessions("thinking"))
        assert eng._anim_id() == "review"

    def test_waiting_maps_to_waiting(self):
        eng = make_engine(sessions=make_sessions("waiting"))
        assert eng._anim_id() == "waiting"

    def test_unknown_state_falls_back_to_idle(self):
        eng = make_engine(sessions=make_sessions("weird-state"))
        assert eng._anim_id() == "idle"

    def test_busy_direction_left(self):
        eng = make_engine(sessions=make_sessions("busy", direction="left"))
        assert eng._anim_id() == "running-left"

    def test_busy_direction_right(self):
        eng = make_engine(sessions=make_sessions("busy", direction="right"))
        assert eng._anim_id() == "running-right"

    def test_airborne_uses_jumping_for_standard_pet(self):
        phys = {"x": 0, "y": 0, "vx": 0, "vy": -1, "grounded": False,
                "mode": "idle", "t": 0, "walkT": 0, "spawned": True}
        eng = make_engine(sessions=make_sessions("idle"), phys=phys)
        assert eng._anim_id() == "jumping"

    def test_lpc_airborne_never_uses_jumping(self):
        """BUG-1 regression: LPC cat has no jumping row; must not return 'jumping'."""
        phys = {"x": 0, "y": 0, "vx": 0, "vy": -1, "grounded": False,
                "mode": "idle", "t": 0, "walkT": 0, "spawned": True}
        eng = make_engine(pet_idx=5, sessions=make_sessions("idle"), phys=phys)
        assert eng._anim_id() != "jumping"

    def test_lpc_walking_left_uses_running_left(self):
        """LPC cat declares a running-left row (row 2), so leftward walking
        must animate rather than falling back to idle (BUG-2 regression)."""
        phys = {"x": 0, "y": 0, "vx": -1, "vy": 0, "grounded": True,
                "mode": "walk", "t": 0, "walkT": 0, "spawned": True}
        eng = make_engine(pet_idx=5, sessions=make_sessions("idle"), phys=phys)
        assert eng._anim_id() == "running-left"

    def test_pet_without_running_left_falls_back_to_map(self):
        """The vx<0 guard must only fire when the pet actually has the row."""
        pet = dict(main.PETS[0])
        pet["states"] = [
            {"id": "idle", "row": 0, "frames": 6, "durationMs": 1100},
            {"id": "running-right", "row": 1, "frames": 8, "durationMs": 1060},
        ]
        phys = {"x": 0, "y": 0, "vx": -1, "vy": 0, "grounded": True,
                "mode": "walk", "t": 0, "walkT": 0, "spawned": True}
        eng = make_engine(sessions=make_sessions("idle"), phys=phys)
        eng.pet = pet
        assert eng._anim_id() != "running-left"

    def test_attention_waving_for_standard_pet(self):
        eng = make_engine(sessions=make_sessions("idle"),
                          attention_until=time.time() + 2)
        assert eng._anim_id() == "waving"

    def test_attention_waving_ignored_for_pet_without_waving(self):
        eng = make_engine(pet_idx=5, sessions=make_sessions("idle"),
                          attention_until=time.time() + 2)
        assert eng._anim_id() != "waving"
