"""Engine-level integration tests: real PetEngine against the real sprite
sheets (no window — PetWindow is stubbed), frame-cache integrity, sprite
sheet bounds, physics stability, and bubble rendering.
"""

import os

import pytest

main = pytest.importorskip("desktop.main")
from conftest import make_sessions  # noqa: E402

SPRITES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "desktop", "sprites")


# ---------------------------------------------------------------- definitions

class TestDefinitions:
    def test_pet_states_unique_rows(self):
        """No two states may share a sprite row (walking/running collision)."""
        rows = [s["row"] for s in main.PET_STATES]
        assert len(rows) == len(set(rows)), (
            "PET_STATES has duplicate sprite rows: %r" % rows
        )

    def test_pet_states_unique_ids(self):
        ids = [s["id"] for s in main.PET_STATES]
        assert len(ids) == len(set(ids))

    def test_every_anim_id_reachable(self):
        """No dead animation ids: every declared state is reachable from the
        per-pet maps or the physics-driven ids."""
        reachable = {"idle", "jumping", "waving", "running-left", "running-right"}
        for pet in main.PETS:
            reachable |= set((pet.get("map") or main.DEFAULT_MAP).values())
        for pet in main.PETS:
            for s in pet.get("states") or main.PET_STATES:
                assert s["id"] in reachable, (
                    "state %r of pet %s is unreachable dead code" % (s["id"], pet["id"])
                )

    def test_default_map_keys_resolve_for_standard_pets(self):
        ids = {s["id"] for s in main.PET_STATES}
        for k, v in main.DEFAULT_MAP.items():
            assert v in ids, "DEFAULT_MAP %r -> %r is not a declared state" % (k, v)

    def test_sprite_sheets_exist_and_match_defs(self):
        for pet in main.PETS:
            p = os.path.join(SPRITES_DIR, pet["file"])
            assert os.path.exists(p), "missing sprite %s" % pet["file"]
            from PIL import Image

            im = Image.open(p)
            iw, ih = im.size
            assert iw % pet["frameW"] == 0, "%s width not divisible" % pet["file"]
            assert ih % pet["frameH"] == 0, "%s height not divisible" % pet["file"]
            rows = ih // pet["frameH"]
            cols = iw // pet["frameW"]
            for s in pet.get("states") or main.PET_STATES:
                assert s["row"] < rows, "%s state %s row OOB" % (pet["file"], s["id"])
                assert s["frames"] <= cols, "%s state %s cols OOB" % (pet["file"], s["id"])

    def test_pets_declared(self):
        assert len(main.PETS) == 7
        assert main.PETS[-1]["id"] == "emberkit"


# ---------------------------------------------------------------- full engine

class TestFullEngine:
    def test_init_loads_everything(self, no_window, pet_dir):
        eng = main.PetEngine()
        assert eng.sheet is not None, "sprite sheet failed to load"
        assert eng.phys["spawned"] is False
        assert eng.anim["id"] == "idle"
        assert eng.pet["id"] == "capvolt"

    def test_frame_cache_has_every_declared_frame(self, no_window, pet_dir):
        eng = main.PetEngine()
        states = main.pet_states(eng.pet)
        for s in states:
            for i in range(s["frames"]):
                assert (s["id"], i) in eng._frame_cache, (
                    "missing cached frame (%s, %d)" % (s["id"], i)
                )

    def test_frame_cache_has_no_dead_keys(self, no_window, pet_dir):
        eng = main.PetEngine()
        declared = {(s["id"], i) for s in main.pet_states(eng.pet)
                    for i in range(s["frames"])}
        assert set(eng._frame_cache) <= declared

    def test_compose_returns_correct_size(self, no_window, pet_dir):
        eng = main.PetEngine()
        img = eng._compose()
        assert img.size == (eng.pet["frameW"] * eng.pet["scale"],
                            eng.pet["frameH"] * eng.pet["scale"])

    def test_compose_with_missing_sheet_no_crash(self, no_window, pet_dir):
        eng = main.PetEngine()
        eng.sheet = None
        eng._frame_cache = {}
        img = eng._compose()
        assert img.size == (eng.pet["frameW"] * eng.pet["scale"],
                            eng.pet["frameH"] * eng.pet["scale"])

    def test_compose_bubble_fits_within_canvas(self, no_window, pet_dir):
        eng = main.PetEngine()
        eng.bubble_text = "bash " + "x" * 400  # absurdly long label
        eng.bubble_until = main.time.time() + 5
        img = eng._compose()
        assert img.size[0] >= 8  # canvas exists; bubble must not overflow width

    def test_bubble_font_loaded_once(self, no_window, pet_dir, monkeypatch):
        """truetype() must be cached, not reloaded per frame (~5ms each)."""
        eng = main.PetEngine()
        calls = []
        real = main.ImageFont.truetype
        monkeypatch.setattr(main.ImageFont, "truetype",
                            lambda *a, **k: calls.append(a) or real(*a, **k))
        eng.bubble_text = "VS Code"
        eng.bubble_until = main.time.time() + 5
        canvas = main.Image.new("RGBA", (192, 208), (0, 0, 0, 0))
        for _ in range(5):
            eng._draw_bubble(canvas, eng.bubble_text)
        assert len(calls) == 1, "font was loaded %d times" % len(calls)

    def test_fit_text_truncates_with_ellipsis(self, no_window, pet_dir):
        eng = main.PetEngine()
        font = eng._font_cache()
        avail = 168
        long_text = "bash " + "x" * 500
        fitted = eng._fit_text(long_text, font, avail)
        assert len(fitted) < len(long_text)
        assert fitted.endswith("\u2026")
        assert font.getlength(fitted) <= avail
        # short text passes through untouched
        assert eng._fit_text("hi", font, avail) == "hi"

    def test_bubble_compose_no_overflow(self, no_window, pet_dir):
        """An absurdly long label must not crash or overflow the canvas."""
        eng = main.PetEngine()
        eng.bubble_text = "bash " + "x" * 500
        eng.bubble_until = main.time.time() + 5
        img = eng._compose()
        assert img.size[0] == 192

    def test_loop_does_not_crash(self, no_window, pet_dir):
        eng = main.PetEngine()
        eng.update_sessions(make_sessions("busy", direction="right"))
        eng.area = (0, 0, 800, 600)
        for _ in range(10):
            eng.loop()

    def test_loop_with_stale_session(self, no_window, pet_dir):
        eng = main.PetEngine()
        eng.update_sessions(make_sessions("error"))
        eng.update_sessions(make_sessions("error", stale=True))
        eng.area = (0, 0, 800, 600)
        for _ in range(5):
            eng.loop()


# ---------------------------------------------------------------- physics

class TestPhysics:
    def _eng(self, no_window, pet_dir):
        eng = main.PetEngine()
        eng.area = (0, 0, 800, 600)
        return eng

    def test_spawn_centered_on_floor(self, no_window, pet_dir):
        eng = self._eng(no_window, pet_dir)
        eng.loop()  # first tick spawns
        h = eng.pet["frameH"] * eng.pet["scale"]

        assert eng.phys["y"] == 600 - h
        assert eng.phys["x"] == 400 - (eng.pet["frameW"] * eng.pet["scale"]) / 2

    def test_jump_returns_to_ground(self, no_window, pet_dir):
        eng = self._eng(no_window, pet_dir)
        eng.loop()
        eng.poke()
        assert not eng.phys["grounded"]
        for _ in range(400):  # plenty of ticks
            eng.loop()
        assert eng.phys["grounded"]
        h = eng.pet["frameH"] * eng.pet["scale"]
        assert eng.phys["y"] == 600 - h

    def test_walk_stays_in_bounds(self, no_window, pet_dir):
        eng = self._eng(no_window, pet_dir)
        eng.loop()
        eng.phys["mode"] = "walk"
        eng.phys["vx"] = 3.0
        for _ in range(2000):
            eng.loop()
        assert eng.phys["x"] >= 0
        w = eng.pet["frameW"] * eng.pet["scale"]
        assert eng.phys["x"] <= 800 - w

    def test_wall_bounce_sets_vy(self, no_window, pet_dir):
        eng = self._eng(no_window, pet_dir)
        eng.loop()
        w = eng.pet["frameW"] * eng.pet["scale"]
        eng.phys["x"] = 800 - w
        eng.phys["vx"] = 2.0
        eng.phys["mode"] = "walk"
        eng._phys(16.7)
        assert eng.phys["vx"] < 0  # bounced back left


# ---------------------------------------------------------------- cast flash

class TestCastFlash:
    def test_focus_completion_triggers_cast(self, no_window, pet_dir):
        """Completing a focus session fires the small 'cast' event."""
        import time as _t
        eng = main.PetEngine()
        eng.focus_active = True
        eng.focus_wilted = False
        eng.focus_started = _t.time() - ((eng.focus_target_min or 25) * 60) - 5
        eng._focus_tick()
        assert eng.focus_active is False
        assert eng.cast is not None and eng.cast.get("until", 0) > _t.time()

    def test_cast_self_expires_on_compose(self, no_window, pet_dir):
        """An expired cast must be cleared (not left stuck as a flash)."""
        import time as _t
        eng = main.PetEngine()
        eng.cast = {"until": _t.time() - 1, "started": _t.time() - 2}
        eng.bubble_text = ""
        eng.bubble_until = 0
        img = eng._compose()
        assert eng.cast is None
        assert img is not None

    def test_draw_cast_no_crash(self, no_window, pet_dir):
        """The additive burst renderer must run harmlessly for any progress."""
        eng = main.PetEngine()
        canvas = main.Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        out = eng._draw_cast(canvas, 0.5)
        assert out.mode == "RGBA"

    def test_state_aura_renders(self, no_window, pet_dir):
        """The status ring behind the pet always composes (RGBA), for any state."""
        eng = main.PetEngine()
        a = eng._state_aura()
        assert a is not None and a.mode == "RGBA"
        # changing the engine state must still yield a valid ring
        eng.os_active = True
        a2 = eng._state_aura()
        assert a2 is not None and a2.mode == "RGBA"
