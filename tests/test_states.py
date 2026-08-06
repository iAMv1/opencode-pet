"""State-machine user-control tests: config eventMap wiring, directional
movement (walk_toward / follow-cursor / arrow keys), and the live pet-state
introspection API (get_pet_state + engine snapshot).
"""

import json
import time

import pytest

main = pytest.importorskip("desktop.main")
import desktop.engine as engine_mod  # noqa: E402
import desktop.store as store  # noqa: E402
import desktop.win32 as win32  # noqa: E402
from conftest import make_sessions  # noqa: E402


def write(pet_dir, name, payload):
    p = pet_dir / name
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def make_engine(pet_idx=0, sessions=None, os_active=False, event_map=None, **kw):
    eng = object.__new__(main.PetEngine)
    eng.pet = main.PETS[pet_idx]
    eng.sessions = sessions if sessions is not None else []
    eng.os_active = os_active
    eng._stale_emotion = kw.get("stale_emotion")
    eng.attention_until = kw.get("attention_until", 0.0)
    eng.cfg = kw.get("cfg") or {}
    eng.mood = kw.get("mood", "neutral")
    eng.dragging = kw.get("dragging", False)
    eng.walk_factor = kw.get("walk_factor", 1.0)
    eng.phys = kw.get("phys") or {
        "x": 0, "y": 0, "vx": 0, "vy": 0,
        "grounded": True, "mode": "idle", "t": 0, "walkT": 0, "spawned": True,
    }
    anims = [a["id"] for a in main.pet_states(eng.pet)]
    m = event_map if event_map is not None else eng.cfg.get("eventMap")
    m = store.sanitize_event_map(m, anims)
    # mirror engine._init_event_map: partial config maps merge over the
    # pet's own native map instead of shadowing it
    base = dict(eng.pet.get("map") or main.DEFAULT_MAP)
    if m:
        base.update(m)
        m = base
    eng._event_map = m
    return eng


# ---------------------------------------------------------------- sanitizer

class TestSanitizeEventMap:
    def test_keeps_only_valid_semantic_keys_and_anims(self):
        anims = [s["id"] for s in main.PET_STATES]
        m = store.sanitize_event_map(
            {"busy": "waving", "bogus": "jumping", "idle": "no-such"}, anims)
        assert m == {"busy": "waving"}

    def test_non_dict_returns_none(self):
        assert store.sanitize_event_map(None, ["idle"]) is None
        assert store.sanitize_event_map([1, 2], ["idle"]) is None
        assert store.sanitize_event_map("x", ["idle"]) is None

    def test_all_semantic_keys_accepted(self):
        anims = [s["id"] for s in main.PET_STATES]
        m = store.sanitize_event_map(
            {"idle": "idle", "busy": "walking", "thinking": "review",
             "error": "failed", "success": "jumping", "waiting": "waiting",
             "stale": "idle", "celebrating": "waving", "retry": "review"}, anims)
        assert set(m) == {"idle", "busy", "thinking", "error", "success",
                          "waiting", "stale", "celebrating", "retry"}

    def test_unknown_anim_ids_dropped(self):
        m = store.sanitize_event_map({"busy": "walking"}, ["idle", "waving"])
        assert m == {}

    def test_empty_map_returns_empty(self):
        assert store.sanitize_event_map({}, ["idle"]) == {}


# ---------------------------------------------------------------- eventMap wiring

class TestEventMap:
    def test_config_map_overrides_default(self):
        eng = make_engine(sessions=make_sessions("busy"),
                          event_map={"busy": "waving"})
        assert eng._anim_id() == "waving"

    def test_invalid_value_dropped_falls_back_to_default(self):
        eng = make_engine(sessions=make_sessions("busy"),
                          event_map={"busy": "no-such-anim"})
        assert eng._anim_id() == "walking"

    def test_invalid_value_dropped_keeps_other_entries(self):
        eng = make_engine(sessions=make_sessions("thinking"),
                          event_map={"busy": "no-such", "thinking": "idle"})
        assert eng._anim_id() == "idle"

    def test_non_dict_map_falls_back_to_default(self):
        eng = make_engine(sessions=make_sessions("error"),
                          event_map=["error", "failed"])
        assert eng._anim_id() == "failed"

    def test_unknown_semantic_key_dropped(self):
        eng = make_engine(sessions=make_sessions("idle"),
                          event_map={"bogus": "waving"})
        assert eng._anim_id() == "idle"

    def test_map_validated_against_pet_anims(self):
        """LPC cat has no walking row: config busy:walking is dropped, so its
        own map (busy -> running-right) wins."""
        eng = make_engine(pet_idx=5, sessions=make_sessions("busy"),
                          event_map={"busy": "walking"})
        assert eng._anim_id() == "running-right"

    def test_partial_config_map_merges_over_pet_map(self):
        """Regression: a partial config map must not shadow the pet's own
        native map for unmapped semantics (lpc-cat busy -> running-right)."""
        eng = make_engine(pet_idx=5, sessions=make_sessions("busy"),
                          event_map={"idle": "idle", "waiting": "waiting"})
        assert eng._anim_id() == "running-right"

    def test_full_engine_init_resolves_config_map(self, no_window, pet_dir):
        write(pet_dir, "config.json", {"eventMap": {"busy": "waving"}})
        eng = main.PetEngine()
        eng.sessions = make_sessions("busy")
        assert eng._anim_id() == "waving"

    def test_config_watch_live_swaps_map(self, no_window, pet_dir):
        eng = main.PetEngine()
        eng.sessions = make_sessions("busy")
        write(pet_dir, "config.json", {"eventMap": {"busy": "waving"}})
        eng.config_watch()
        assert eng._anim_id() == "waving"
        write(pet_dir, "config.json", {"eventMap": {"busy": "idle"}})
        eng.config_watch()
        assert eng._anim_id() == "idle"

    def test_config_watch_live_applies_movement_toggles(self, no_window, pet_dir):
        eng = main.PetEngine()
        write(pet_dir, "config.json", {"arrows": False, "followCursor": False})
        eng.config_watch()
        assert eng.cfg["arrows"] is False
        assert eng.cfg["followCursor"] is False
        write(pet_dir, "config.json", {"arrows": True})
        eng.config_watch()
        assert eng.cfg["arrows"] is True


# ---------------------------------------------------------------- walk_toward

class TestWalkToward:
    def test_left(self):
        eng = make_engine()
        eng.walk_toward("left")
        assert eng.phys["mode"] == "walk"
        assert eng.phys["vx"] < 0
        assert eng.phys["walkT"] == 0

    def test_right(self):
        eng = make_engine()
        eng.walk_toward("right")
        assert eng.phys["mode"] == "walk"
        assert eng.phys["vx"] > 0

    def test_up_jumps_when_grounded(self):
        eng = make_engine()
        eng.walk_toward("up")
        assert not eng.phys["grounded"]
        assert eng.phys["vy"] < 0

    def test_up_ignored_when_airborne(self):
        phys = {"x": 0, "y": 0, "vx": 0, "vy": 0, "grounded": False,
                "mode": "idle", "t": 0, "walkT": 0, "spawned": True}
        eng = make_engine(phys=phys)
        eng.walk_toward("up")
        assert eng.phys["grounded"] is False
        assert eng.phys["vy"] == 0

    def test_walk_disabled_blocks_horizontal_but_jump_works(self):
        eng = make_engine(walk_factor=0.0)
        eng.walk_toward("left")
        assert eng.phys["mode"] == "idle"
        assert eng.phys["vx"] == 0
        eng.walk_toward("up")
        assert not eng.phys["grounded"]

    def test_unknown_direction_noop(self):
        eng = make_engine()
        eng.walk_toward("down")
        assert eng.phys["mode"] == "idle"

    def test_walk_speed_within_bounds(self):
        eng = make_engine()
        eng.walk_toward("right")
        assert 0 < eng.phys["vx"] <= engine_mod.WALK_SPEED_MIN + engine_mod.WALK_SPEED_RANGE


# ---------------------------------------------------------------- follow-cursor

class TestFollowCursor:
    def _eng(self, os_active=True, **kw):
        eng = make_engine(os_active=os_active, **kw)
        eng.area = (0, 0, 1920, 1040)
        eng._cursor = kw.get("cursor", (600, 500))
        return eng

    def test_far_cursor_right_walks_toward(self):
        eng = self._eng(cursor=(600, 500))
        eng.phys["x"] = 100
        eng._follow_cursor_tick(time.time())
        assert eng.phys["mode"] == "walk"
        assert eng.phys["vx"] > 0

    def test_far_cursor_left_walks_left(self):
        eng = self._eng(cursor=(50, 500))
        eng.phys["x"] = 400
        eng._follow_cursor_tick(time.time())
        assert eng.phys["mode"] == "walk"
        assert eng.phys["vx"] < 0

    def test_near_cursor_stops_cursor_walk(self):
        eng = self._eng(cursor=(300, 500))
        eng.phys["x"] = 200  # pet center 296; dx = 4
        eng.phys["mode"] = "walk"
        eng.phys["vx"] = 1.0
        eng._cursor_walk = True
        eng._follow_cursor_tick(time.time())
        assert eng.phys["mode"] == "idle"
        assert eng.phys["vx"] == 0

    def test_near_cursor_does_not_start_walk(self):
        eng = self._eng(cursor=(300, 500))
        eng.phys["x"] = 200
        eng._follow_cursor_tick(time.time())
        assert eng.phys["mode"] != "walk"

    def test_disabled_flag_suppresses(self):
        eng = self._eng(cursor=(600, 500), cfg={"followCursor": False})
        eng.phys["x"] = 100
        eng._follow_cursor_tick(time.time())
        assert eng.phys["mode"] != "walk"

    def test_drag_suppresses(self):
        eng = self._eng(cursor=(600, 500), dragging=True)
        eng.phys["x"] = 100
        eng._follow_cursor_tick(time.time())
        assert eng.phys["mode"] != "walk"

    def test_walk_factor_zero_suppresses(self):
        eng = self._eng(cursor=(600, 500), walk_factor=0.0)
        eng.phys["x"] = 100
        eng._follow_cursor_tick(time.time())
        assert eng.phys["mode"] != "walk"

    def test_airborne_suppresses(self):
        phys = {"x": 100, "y": 0, "vx": 0, "vy": -1, "grounded": False,
                "mode": "idle", "t": 0, "walkT": 0, "spawned": True}
        eng = self._eng(cursor=(600, 500), phys=phys)
        eng._follow_cursor_tick(time.time())
        assert eng.phys["mode"] != "walk"

    def test_os_idle_suppresses(self):
        eng = self._eng(os_active=False, cursor=(600, 500))
        eng.phys["x"] = 100
        eng._follow_cursor_tick(time.time())
        assert eng.phys["mode"] != "walk"

    def test_cursor_outside_area_suppresses(self):
        eng = self._eng(cursor=(5000, 500))
        eng.phys["x"] = 100
        eng._follow_cursor_tick(time.time())
        assert eng.phys["mode"] != "walk"

    def test_cursor_unavailable_suppresses(self):
        eng = self._eng(cursor=None)
        eng.phys["x"] = 100
        eng._follow_cursor_tick(time.time())
        assert eng.phys["mode"] != "walk"

    def test_throttle_keeps_existing_walk(self):
        eng = self._eng(cursor=(1000, 500))
        eng.phys["x"] = 100
        eng.phys["mode"] = "walk"
        eng.phys["vx"] = -1.0  # random walk, opposite direction
        eng._cursor_walk = False
        eng._follow_cursor_tick(time.time())
        assert eng.phys["vx"] == -1.0  # not re-targeted mid-walk


# ---------------------------------------------------------------- arrow keys

class TestArrows:
    def _win(self, eng):
        win = object.__new__(win32.PetWindow)
        win.engine = eng
        return win

    def test_left_arrow_walks_left(self):
        eng = make_engine(cfg={"arrows": True})
        self._win(eng)._on_key_down(win32.VK_LEFT)
        assert eng.phys["mode"] == "walk"
        assert eng.phys["vx"] < 0

    def test_right_arrow_walks_right(self):
        eng = make_engine(cfg={"arrows": True})
        self._win(eng)._on_key_down(win32.VK_RIGHT)
        assert eng.phys["mode"] == "walk"
        assert eng.phys["vx"] > 0

    def test_up_arrow_jumps(self):
        eng = make_engine(cfg={"arrows": True})
        self._win(eng)._on_key_down(win32.VK_UP)
        assert not eng.phys["grounded"]
        assert eng.phys["vy"] < 0

    def test_arrows_false_ignores_keydown(self):
        eng = make_engine(cfg={"arrows": False})
        self._win(eng)._on_key_down(win32.VK_LEFT)
        assert eng.phys["mode"] == "idle"
        assert eng.phys["vx"] == 0

    def test_arrows_default_true_without_cfg(self):
        eng = make_engine()
        self._win(eng)._on_key_down(win32.VK_RIGHT)
        assert eng.phys["mode"] == "walk"

    def test_unknown_key_noop(self):
        eng = make_engine()
        self._win(eng)._on_key_down(0x41)  # VK_A
        assert eng.phys["mode"] == "idle"

    def test_no_engine_noop(self):
        win = object.__new__(win32.PetWindow)
        win.engine = None
        assert win._on_key_down(win32.VK_LEFT) == 0


# ---------------------------------------------------------------- get_pet_state

class TestPetStateApi:
    def _snap(self, pet_dir):
        with open(store.state_file_path(), encoding="utf-8") as fh:
            return json.load(fh)

    def test_engine_snapshot_shape(self, no_window, pet_dir):
        eng = main.PetEngine()
        eng.sessions = make_sessions("busy")
        eng._snapshot_state()
        d = self._snap(pet_dir)
        assert set(d) == {"raw", "state", "anim", "t", "mood", "eventMap",
                          "arrows", "followCursor", "drag"}
        assert d["raw"] == "busy"
        assert d["state"] == "busy"
        assert d["anim"] == "walking"
        assert d["mood"] == "neutral"
        assert d["drag"] is False
        assert d["arrows"] is True
        assert d["followCursor"] is True
        assert isinstance(d["t"], (int, float))

    def test_snapshot_reflects_movement_toggles(self, no_window, pet_dir):
        eng = main.PetEngine()
        write(pet_dir, "config.json", {"arrows": False, "followCursor": False})
        eng.config_watch()
        eng._snapshot_state()
        d = self._snap(pet_dir)
        assert d["arrows"] is False
        assert d["followCursor"] is False

    def test_snapshot_drag_flag(self, no_window, pet_dir):
        eng = main.PetEngine()
        eng.dragging = True
        eng._snapshot_state()
        assert self._snap(pet_dir)["drag"] is True

    def test_snapshot_event_map_reports_resolved_map(self, no_window, pet_dir):
        eng = main.PetEngine()
        write(pet_dir, "config.json", {"eventMap": {"busy": "waving"}})
        eng.config_watch()
        eng._snapshot_state()
        assert self._snap(pet_dir)["eventMap"] == {"busy": "waving"}

    def test_api_reads_snapshot(self, no_window, pet_dir):
        eng = main.PetEngine()
        eng.sessions = make_sessions("error")
        eng._snapshot_state()
        d = main.ControlApi().get_pet_state()
        assert d["state"] == "error"
        assert d["anim"] == "failed"
        assert d["raw"] == "error"

    def test_api_fallback_without_snapshot(self, pet_dir, monkeypatch):
        monkeypatch.setattr(main, "current_app_session", lambda: None)
        d = main.ControlApi().get_pet_state()
        assert set(d) == {"raw", "state", "anim", "mood", "eventMap",
                          "arrows", "followCursor", "drag"}
        assert d["state"] == "idle"
        assert d["anim"] is None

    def test_web_methods_parity(self):
        assert "get_pet_state" in main._WEB_METHODS
        assert "get_pet_state" not in main._WEB_NOP
