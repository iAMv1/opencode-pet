"""P8: Lifestyle Alerts — pet bubbles, at most one per day.

Covers: churn (state-flap: median state segment < 60s over > 20 today
events), idle-fog warning (60%+ idle after 15:00, real day only), Sunday
week-end review (once — the config alertDate guard survives restarts),
"alert" log entries, and the get_alerts API shapes + parity entries.
"""

import datetime
import json
import time

import pytest

main = pytest.importorskip("desktop.main")
import desktop.store as store_mod  # noqa: E402
import desktop.engine as engine_mod  # noqa: E402


def day_ago(n):
    return (datetime.date.today() - datetime.timedelta(days=n)).isoformat()


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


def write_state_events(pet_dir, eng, count, gap):
    """`count` state transitions today, `gap` seconds apart."""
    p = pet_dir / ("activity-%s.jsonl" % eng.pet["id"])
    now = time.time()
    lines = [json.dumps({"t": now - (count - 1 - i) * gap, "kind": "state",
                         "state": "busy"}) for i in range(count)]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _at(hour, minute=0):
    d = datetime.date.today()
    return datetime.datetime(d.year, d.month, d.day, hour, minute).timestamp()


def _sunday_2030():
    d = datetime.date.today()
    sunday = d + datetime.timedelta(days=(6 - d.weekday()) % 7)
    return datetime.datetime(sunday.year, sunday.month, sunday.day, 20, 30).timestamp()


def _eng(pet_dir, no_window):
    eng = main.PetEngine()
    eng.xp = 0
    eng.level = 1
    eng.mood = "neutral"
    eng.bubble_until = 0
    eng.sessions = []
    eng._last_alert_check = 0.0
    eng._alert_date = ""
    return eng


def alerts(pet_dir, eng):
    return [e for e in read_log(pet_dir, eng) if e.get("kind") == "alert"]


# ---------------------------------------------------------------- churn

class TestChurn:
    def test_flap_fires_on_six_second_median(self, pet_dir, no_window):
        # real user shape: 6s state-flap median
        eng = _eng(pet_dir, no_window)
        write_state_events(pet_dir, eng, 30, 6)
        now = _at(10, 0)
        eng._alert_tick(now)
        assert "flitting between tasks" in eng.bubble_text
        a = alerts(pet_dir, eng)
        assert len(a) == 1 and a[0]["alert"] == "churn"

    def test_flap_needs_more_than_twenty_events(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        write_state_events(pet_dir, eng, 20, 6)
        eng._alert_tick(_at(10, 0))
        assert eng.bubble_text == "" and not alerts(pet_dir, eng)

    def test_flap_needs_sub_sixty_second_median(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        write_state_events(pet_dir, eng, 30, 90)
        eng._alert_tick(_at(10, 0))
        assert eng.bubble_text == "" and not alerts(pet_dir, eng)


# ---------------------------------------------------------------- idle warning

class TestIdleWarning:
    def test_idle_warning_fires_at_1500(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        eng._wb = {"Idle": 7200, "VS Code": 4800}   # 60% idle, 2h tracked
        eng._alert_tick(_at(15, 5))
        assert "Half the day is fog" in eng.bubble_text
        assert alerts(pet_dir, eng)[0]["alert"] == "idle_warn"

    def test_idle_warning_not_before_1500(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        eng._wb = {"Idle": 7200, "VS Code": 4800}
        eng._alert_tick(_at(14, 59))
        assert eng.bubble_text == "" and not alerts(pet_dir, eng)

    def test_idle_warning_requires_sixty_percent(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        eng._wb = {"Idle": 6000, "VS Code": 6000}   # 50% idle
        eng._alert_tick(_at(16, 0))
        assert eng.bubble_text == "" and not alerts(pet_dir, eng)

    def test_idle_warning_requires_a_real_day(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        eng._wb = {"Idle": 1200, "VS Code": 300}    # 80% but under 30 min total
        eng._alert_tick(_at(16, 0))
        assert eng.bubble_text == "" and not alerts(pet_dir, eng)


# ---------------------------------------------------------------- week-end review

class TestWeekEnd:
    def test_week_end_review_fires_sunday_evening(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        eng._history = {day_ago(1): int(6.3 * 3600)}
        now = _sunday_2030()
        eng._alert_tick(now)
        assert "The week closed at 6.3h" in eng.bubble_text
        assert "guard your sharpest hour" in eng.bubble_text
        assert alerts(pet_dir, eng)[0]["alert"] == "week_review"

    def test_week_end_review_not_on_saturday(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        eng._history = {day_ago(1): int(6.3 * 3600)}
        sat = datetime.date.today() + datetime.timedelta(days=(5 - datetime.date.today().weekday()) % 7)
        now = datetime.datetime(sat.year, sat.month, sat.day, 21, 0).timestamp()
        eng._alert_tick(now)
        assert eng.bubble_text == "" and not alerts(pet_dir, eng)


# ---------------------------------------------------------------- guard + api

class TestGuardAndApi:
    def test_alert_fires_at_most_once_per_day(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        write_state_events(pet_dir, eng, 30, 6)
        now = _at(10, 0)
        eng._alert_tick(now)
        eng._alert_tick(now + 120)          # same day, alertDate guard holds
        assert len(alerts(pet_dir, eng)) == 1
        c = store_mod.load_config()
        assert c.get("alertDate") == time.strftime("%Y-%m-%d")

    def test_alert_guard_survives_restart(self, pet_dir, no_window):
        write(pet_dir, "config.json", {"alertDate": time.strftime("%Y-%m-%d")})
        eng = main.PetEngine()
        eng.bubble_until = 0
        write_state_events(pet_dir, eng, 30, 6)
        eng._last_alert_check = 0.0
        eng._alert_tick(_at(10, 0))
        assert eng.bubble_text == "" and not alerts(pet_dir, eng)

    def test_alert_logs_line_for_dashboard(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        write_state_events(pet_dir, eng, 30, 6)
        eng._alert_tick(_at(10, 0))
        a = alerts(pet_dir, eng)[0]
        assert a["alert"] == "churn" and a["line"] and a.get("t")

    def test_alert_defers_while_a_moment_is_live(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        write_state_events(pet_dir, eng, 30, 6)
        now = _at(10, 0)
        eng.attention_until = now + 10
        eng._alert_tick(now)
        assert eng.bubble_text == "" and not alerts(pet_dir, eng)
        eng.attention_until = 0
        eng._alert_tick(now + 70)
        assert "flitting between tasks" in eng.bubble_text

    def test_get_alerts_shape(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        write_state_events(pet_dir, eng, 30, 6)
        eng._alert_tick(_at(10, 0))
        s = main.ControlApi().get_alerts()
        assert set(s) == {"today", "last"}
        assert "flitting between tasks" in s["today"]
        assert s["last"][0]["alert"] == "churn" and s["last"][0]["line"]

    def test_get_alerts_empty_without_events(self, pet_dir):
        s = main.ControlApi().get_alerts()
        assert s == {"today": "", "last": []}

    def test_parity_entries(self, pet_dir):
        for m in ("get_alerts", "get_memory_lane"):
            assert m in main._WEB_METHODS
            assert hasattr(main.ControlApi, m)

    def test_week_end_review_helper(self, pet_dir):
        line = store_mod.week_end_review({day_ago(1): int(6.3 * 3600)})
        assert "6.3h" in line and "sharpest hour" in line
        assert store_mod.week_end_review({})  # zero week still narrates
