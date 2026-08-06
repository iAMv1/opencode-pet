"""P6: Data-Embodiment — the pet's body IS the dashboard.

Covers: store.day_health pure math (fog threshold at 40% idle, bloom on goal
met / 1h continuous focus, storm on error count + focus wilt, ember on 4
saturated hours, quiet under 10 min, flow default, priority ordering,
intensity scaling), the engine embody tick (aura per state, error-static
bubble once per 10 min, embody log), and the get_day_health API shape +
web-methods parity entry.
"""

import json
import time

import pytest

main = pytest.importorskip("desktop.main")
import desktop.store as store_mod  # noqa: E402
import desktop.engine as engine_mod  # noqa: E402


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


def wb(apps, hour_today=None):
    """A wellbeing dict shaped like the engine's live state / the file."""
    return {"date": time.strftime("%Y-%m-%d"), "apps": apps,
            "hourToday": hour_today or {}}


def _eng(pet_dir, no_window):
    eng = main.PetEngine()
    eng.xp = 0
    eng.level = 1
    eng.mood = "neutral"
    eng._last_tool_earn = ""
    eng.bubble_until = 0
    eng.sessions = []
    return eng


def add_state_event(pet_dir, eng, state, t):
    """A 'state' transition line in this pet's activity log (like the engine
    logs on session transitions)."""
    p = pet_dir / ("activity-%s.jsonl" % eng.pet["id"])
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"t": t, "kind": "state", "state": state}) + "\n")


# ---------------------------------------------------------------- pure day_health

class TestDayHealth:
    def test_flow_default(self):
        h = store_mod.day_health(wb({"Code": 2000}))
        assert h["state"] == "flow"
        assert 0.0 <= h["intensity"] <= 1.0
        assert "Steady flow" in h["label"]

    def test_flow_uses_empty_wellbeing(self):
        assert store_mod.day_health({})["state"] == "quiet"

    def test_quiet_under_ten_minutes(self):
        h = store_mod.day_health(wb({"Code": 300, "Idle": 200}))
        assert h["state"] == "quiet"
        assert h["intensity"] == pytest.approx(1.0 - 500 / 600)

    def test_quiet_beats_fog_before_the_day_starts(self):
        # all idle but under 10 min tracked: the pet sleeps, not droops
        h = store_mod.day_health(wb({"Idle": 300}))
        assert h["state"] == "quiet"

    def test_stale_date_ignored(self):
        yesterday = (time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400)))
        h = store_mod.day_health({"date": yesterday, "apps": {"Code": 99999}})
        assert h["state"] == "quiet"

    def test_fog_at_forty_percent_boundary(self):
        # exactly 40% idle does NOT droop (strictly greater)
        h = store_mod.day_health(wb({"Code": 6000, "Idle": 4000}))
        assert h["state"] == "flow"

    def test_fog_just_over_forty_percent(self):
        h = store_mod.day_health(wb({"Code": 5999, "Idle": 4001}))
        assert h["state"] == "fog"
        assert h["label"] == "Your day feels foggy \u2014 40% idle"
        assert h["intensity"] == pytest.approx((4001 / 10000) / store_mod.FOG_RAMP)

    def test_fog_intensity_scales_with_idle(self):
        h = store_mod.day_health(wb({"Code": 5500, "Idle": 4500}))
        assert h["state"] == "fog"
        assert h["label"] == "Your day feels foggy \u2014 45% idle"
        assert h["intensity"] == pytest.approx(0.45 / 0.60)

    def test_fog_caps_intensity_at_one(self):
        h = store_mod.day_health(wb({"Idle": 10000}))
        assert h["state"] == "fog"
        assert h["intensity"] == 1.0

    def test_bloom_on_goal_met(self):
        h = store_mod.day_health(wb({"Code": 8000}), goal_min=120)
        assert h["state"] == "bloom"
        assert h["intensity"] == 1.0
        assert "goal met" in h["label"]

    def test_bloom_on_one_hour_continuous_focus(self):
        h = store_mod.day_health(
            wb({"Code": 4000, "Idle": 1000}),
            focus={"active": True, "elapsed": 3600})
        assert h["state"] == "bloom"
        assert "1h" in h["label"]
        assert h["intensity"] == 1.0

    def test_no_bloom_below_one_hour(self):
        h = store_mod.day_health(
            wb({"Code": 4000, "Idle": 1000}),
            focus={"active": True, "elapsed": 3599})
        assert h["state"] == "flow"

    def test_ember_on_four_saturated_hours(self):
        hours = {str(h): 700 for h in range(10, 14)}  # 4 hours >= 10 min
        h = store_mod.day_health(wb({"Code": 3000}, hours))
        assert h["state"] == "ember"
        assert "4 deep hours" in h["label"]
        assert h["intensity"] == pytest.approx(4 / store_mod.EMBER_RAMP)

    def test_no_ember_below_four_hours(self):
        hours = {str(h): 700 for h in range(10, 13)}  # 3 saturated
        h = store_mod.day_health(wb({"Code": 3000}, hours))
        assert h["state"] == "flow"

    def test_ember_ignores_unsaturated_hours(self):
        hours = {"10": 599, "11": 700, "12": 700, "13": 700, "14": 3600}
        # only 3 saturated (599 is below the floor); the 3600 makes it 4 -> ember
        h = store_mod.day_health(wb({"Code": 3000}, hours))
        assert h["state"] == "ember"

    def test_storm_on_errors(self):
        h = store_mod.day_health(wb({"Code": 8000}), errors=1)
        assert h["state"] == "storm"
        assert h["label"] == "A session errored \u2014 I felt the static"
        assert h["intensity"] == pytest.approx(0.5 + store_mod.STORM_ERROR_STEP)

    def test_storm_intensity_caps_at_one(self):
        assert store_mod.day_health(wb({}), errors=4)["intensity"] == 1.0

    def test_storm_on_focus_wilt(self):
        h = store_mod.day_health(wb({"Code": 5000}),
                                 focus={"active": True, "wilted": True})
        assert h["state"] == "storm"
        assert "wilted" in h["label"]
        assert h["intensity"] == store_mod.STORM_WILT_INTENSITY

    def test_storm_beats_fog_beats_bloom(self):
        # storm wins over a foggy, goal-met day
        h = store_mod.day_health(
            wb({"Idle": 8000, "Code": 10000}), errors=1, goal_min=120)
        assert h["state"] == "storm"
        # fog wins over a goal-met day
        h = store_mod.day_health(wb({"Idle": 6000, "Code": 8000}), goal_min=120)
        assert h["state"] == "fog"
        # bloom wins over ember (bloom checked first)
        h = store_mod.day_health(
            wb({"Code": 8000}, {str(h2): 700 for h2 in range(10, 15)}), goal_min=120)
        assert h["state"] == "bloom"
        # ember beats flow
        h = store_mod.day_health(
            wb({"Code": 3000}, {str(h2): 700 for h2 in range(10, 14)}))
        assert h["state"] == "ember"

    def test_focus_bloom_falls_behind_fog(self):
        h = store_mod.day_health(
            wb({"Idle": 6000, "Code": 4000}),
            focus={"active": True, "elapsed": 3600})
        assert h["state"] == "fog"


# ---------------------------------------------------------------- engine embody

class TestEngineEmbody:
    def test_embody_tick_applies_fog_aura_and_mood(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        eng._wb = {"Idle": 6000, "Code": 1000}
        eng._hour_today = {}
        eng._embody_tick(time.time(), force=True)
        assert eng._embody_state == "fog"
        assert eng._embody_aura == store_mod.EMBODY_AURA["fog"]
        assert eng.mood == "tired"
        kinds = [r["kind"] for r in read_log(pet_dir, eng)]
        assert "embody" in kinds

    def test_embody_tick_quiet_default(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        eng._wb = {}
        eng._embody_tick(time.time(), force=True)
        assert eng._embody_state == "quiet"
        assert eng._embody_aura is None

    def test_embody_tick_storm_aura_from_errors(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        eng._wb = {"Code": 5000}
        add_state_event(pet_dir, eng, "error", time.time())
        eng._embody_tick(time.time(), force=True)
        assert eng._embody_state == "storm"
        assert eng._embody_aura == store_mod.EMBODY_AURA["storm"]

    def test_embody_tick_bloom_on_goal(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        eng._wb = {"Code": 8000}
        eng.goal_min = 120
        eng._embody_tick(time.time(), force=True)
        assert eng._embody_state == "bloom"
        assert eng._embody_aura == store_mod.EMBODY_AURA["bloom"]

    def test_embody_tick_ember_from_hour_buckets(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        eng._wb = {"Code": 3000}
        eng._hour_today = {h: 700 for h in range(10, 14)}
        eng._embody_tick(time.time(), force=True)
        assert eng._embody_state == "ember"
        assert eng._embody_aura == store_mod.EMBODY_AURA["ember"]

    def test_embody_tick_30s_cadence(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        eng._wb = {"Code": 3000}
        now = time.time()
        eng._embody_tick(now, force=True)
        first = eng._embody_state
        eng._wb = {"Idle": 6000, "Code": 1000}
        eng._embody_tick(now)  # not forced, inside the 30s window
        assert eng._embody_state == first
        eng._embody_tick(now + engine_mod.EMBODY_TICK_SECS + 1)  # outside
        assert eng._embody_state == "fog"

    def test_embody_logs_only_on_change(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        now = time.time()
        eng._wb = {"Idle": 6000, "Code": 1000}  # fog
        eng._embody_tick(now, force=True)
        eng._wb = {"Code": 3000}  # flow
        eng._embody_tick(now + engine_mod.EMBODY_TICK_SECS + 1)
        eng._embody_tick(now + engine_mod.EMBODY_TICK_SECS * 2 + 1)  # still flow
        embody = [r for r in read_log(pet_dir, eng) if r["kind"] == "embody"]
        assert [r["state"] for r in embody] == ["fog", "flow"]

    def test_embody_glow_renders_into_compose(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        eng._wb = {"Code": 8000}
        eng.goal_min = 120
        eng._embody_tick(time.time(), force=True)
        glow = eng._embody_glow()
        assert glow is not None and glow.size[0] > 0
        img = eng._compose()
        assert img.size[0] > 0

    def test_static_bubble_once_per_ten_minutes(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        eng._wb = {"Code": 5000}
        now = time.time()
        add_state_event(pet_dir, eng, "error", now - 60)
        eng._embody_tick(now, force=True)
        assert eng.bubble_text == store_mod.EMBODY_LABELS["storm_error"]
        assert eng.bubble_until > now
        statics = [r for r in read_log(pet_dir, eng) if r["kind"] == "static"]
        assert len(statics) == 1 and statics[0]["errors"] == 1
        # second pass inside the 10-min cooldown: quiet, no new bubble
        eng._embody_tick(now + 300, force=True)
        statics = [r for r in read_log(pet_dir, eng) if r["kind"] == "static"]
        assert len(statics) == 1
        # after the cooldown it may speak once more
        eng._embody_tick(now + engine_mod.STATIC_BUBBLE_SECS + 1, force=True)
        statics = [r for r in read_log(pet_dir, eng) if r["kind"] == "static"]
        assert len(statics) == 2

    def test_wilt_storm_has_no_static_bubble(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        eng._wb = {"Code": 5000}
        eng.focus_active = True
        eng.focus_started = time.time() - 600
        eng.focus_wilted = True
        eng._embody_tick(time.time(), force=True)
        assert eng._embody_state == "storm"
        assert eng.bubble_text == ""  # wilt speaks through the aura, not static
        assert [r for r in read_log(pet_dir, eng) if r["kind"] == "static"] == []


# ---------------------------------------------------------------- API surface

class TestDayHealthApi:
    def test_get_day_health_shape(self, pet_dir):
        write(pet_dir, "wellbeing.json",
              wb({"Idle": 6000, "Code": 1000}))
        s = main.ControlApi().get_day_health()
        assert set(s) == {"state", "label", "intensity", "since"}
        assert s["state"] == "fog"
        assert "86% idle" in s["label"]  # 6000 / 7000 tracked seconds idle
        assert 0.0 <= s["intensity"] <= 1.0
        assert isinstance(s["since"], float)

    def test_get_day_health_quiet_default(self, pet_dir):
        s = main.ControlApi().get_day_health()
        assert s["state"] == "quiet"
        assert s["since"] == 0.0

    def test_get_day_health_since_from_embody_log(self, pet_dir):
        write(pet_dir, "wellbeing.json", wb({"Code": 3000}))
        log = pet_dir / "activity-capvolt.jsonl"  # default pet id
        t = time.time() - 120
        log.write_text(json.dumps(
            {"t": t, "kind": "embody", "state": "flow"}) + "\n", encoding="utf-8")
        s = main.ControlApi().get_day_health()
        assert s["state"] == "flow"
        assert s["since"] == t

    def test_get_day_health_storm_from_log_errors(self, pet_dir):
        write(pet_dir, "wellbeing.json", wb({"Code": 8000}))
        log = pet_dir / "activity-capvolt.jsonl"
        log.write_text(json.dumps(
            {"t": time.time(), "kind": "state", "state": "error"}) + "\n",
            encoding="utf-8")
        s = main.ControlApi().get_day_health()
        assert s["state"] == "storm"
        assert s["label"] == store_mod.EMBODY_LABELS["storm_error"]

    def test_get_day_health_in_web_methods(self, pet_dir):
        assert "get_day_health" in main._WEB_METHODS
