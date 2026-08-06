"""P8: Memory Lane — the pet narrates the last 7 days in its own voice.

Covers: build_lane 7-day shape + folding of today's live totals + per-day
top-app/hour-peak selection, every day_note template firing on crafted
fixtures (record / night-owl / quiet / idle-heavy / multi-pet / error /
pattern), and determinism (same data, same lane).
"""

import datetime
import json
import time

import pytest

main = pytest.importorskip("desktop.main")
import desktop.store as store_mod  # noqa: E402


def day_ago(n):
    return (datetime.date.today() - datetime.timedelta(days=n)).isoformat()


def _wb(history=None, hour_hist=None, app_hist=None, apps=None, hours=None):
    return {"date": time.strftime("%Y-%m-%d"), "apps": apps or {},
            "history": history or {}, "hourHistory": hour_hist or {},
            "appHistory": app_hist or {}, "hourToday": hours or {}}


def _event(kind, day, state=None):
    """An activity-log event pinned to a calendar day (12:00 local)."""
    t = datetime.datetime.fromisoformat(day + "T12:00:00").timestamp()
    e = {"t": t, "kind": kind}
    if state is not None:
        e["state"] = state
    return e


def _entry(lane, day):
    return next(e for e in lane if e["date"] == day)


# ---------------------------------------------------------------- shape

class TestShape:
    def test_lane_has_seven_days_ascending(self, pet_dir):
        lane = store_mod.build_lane(_wb(history={day_ago(1): 6000}))
        assert len(lane) == 7
        assert [e["date"] for e in lane] == [day_ago(6), day_ago(5), day_ago(4),
                                             day_ago(3), day_ago(2), day_ago(1),
                                             time.strftime("%Y-%m-%d")]
        assert set(lane[0]) == {"date", "totalMin", "appTop", "hourPeak", "note"}

    def test_total_min_math(self, pet_dir):
        lane = store_mod.build_lane(_wb(history={day_ago(1): int(9.3 * 3600)}))
        assert _entry(lane, day_ago(1))["totalMin"] == int(9.3 * 3600) // 60

    def test_app_top_and_hour_peak_selected(self, pet_dir):
        wb = _wb(history={day_ago(1): 12000, day_ago(2): 15000},
                 app_hist={day_ago(1): {"Idle": 5000, "VS Code": 4000, "Chrome": 3000}},
                 hour_hist={day_ago(1): {"13": 7200, "2": 3600}})
        e = _entry(store_mod.build_lane(wb), day_ago(1))
        assert e["appTop"] == "VS Code"      # Idle never wins the top-app line
        assert e["hourPeak"] == 13

    def test_folds_todays_live_apps_and_hours(self, pet_dir):
        wb = _wb(apps={"VS Code": 3600, "Idle": 1800},
                 hours={"14": 5400},
                 history={day_ago(1): 20000})
        e = _entry(store_mod.build_lane(wb), time.strftime("%Y-%m-%d"))
        assert e["totalMin"] == 90           # live running total folded in
        assert e["appTop"] == "VS Code"
        assert e["hourPeak"] == 14

    def test_empty_lane_is_all_still(self, pet_dir):
        lane = store_mod.build_lane(None)
        assert len(lane) == 7
        assert all(e["totalMin"] == 0 and e["appTop"] is None
                   and e["hourPeak"] is None for e in lane)
        assert all("still day" in e["note"] for e in lane)


# ---------------------------------------------------------------- notes

class TestNotes:
    def test_record_note_on_deepest_day(self, pet_dir):
        wb = _wb(history={day_ago(1): int(9.3 * 3600), day_ago(2): 5000})
        e = _entry(store_mod.build_lane(wb), day_ago(1))
        assert "deepest day" in e["note"] and "9.3h" in e["note"]

    def test_record_note_needs_to_be_the_deepest(self, pet_dir):
        wb = _wb(history={day_ago(1): 6000, day_ago(2): 20000})
        e = _entry(store_mod.build_lane(wb), day_ago(1))
        assert "deepest day" not in e["note"]

    def test_night_owl_note_on_hours_zero_to_six(self, pet_dir):
        # real user shape: hours 1-5 saturated (>= 4h in the 0-6 window)
        wb = _wb(history={day_ago(1): 20000, day_ago(2): 30000},
                 hour_hist={day_ago(1): {"1": 4700, "2": 4700, "3": 4700, "4": 4700}})
        e = _entry(store_mod.build_lane(wb), day_ago(1))
        assert "past 3am" in e["note"]

    def test_quiet_note_under_one_hour(self, pet_dir):
        wb = _wb(history={day_ago(1): 600, day_ago(2): 20000})
        e = _entry(store_mod.build_lane(wb), day_ago(1))
        assert "still day" in e["note"]

    def test_idle_heavy_note_with_percent(self, pet_dir):
        # real user shape: 45% idle day
        wb = _wb(history={day_ago(1): 12000, day_ago(2): 20000},
                 app_hist={day_ago(1): {"Idle": 5400, "VS Code": 6600}})
        e = _entry(store_mod.build_lane(wb), day_ago(1))
        assert "foggy day" in e["note"] and "45%" in e["note"]

    def test_multi_pet_note_on_switches(self, pet_dir):
        wb = _wb(history={day_ago(1): 10000, day_ago(2): 20000},
                 app_hist={day_ago(1): {"VS Code": 10000}})
        events = [_event("petSwitch", day_ago(1)) for _ in range(4)]
        e = _entry(store_mod.build_lane(wb, events), day_ago(1))
        assert "visited 5 forms" in e["note"]

    def test_error_note_on_static_day(self, pet_dir):
        wb = _wb(history={day_ago(1): 10000, day_ago(2): 20000},
                 app_hist={day_ago(1): {"VS Code": 10000}})
        events = [_event("state", day_ago(1), state="error"),
                  _event("state", day_ago(1), state="retry")]
        e = _entry(store_mod.build_lane(wb, events), day_ago(1))
        assert "static" in e["note"]

    def test_pattern_note_with_top_app(self, pet_dir):
        wb = _wb(history={day_ago(1): int(6.3 * 3600), day_ago(2): int(8.3 * 3600)},
                 app_hist={day_ago(1): {"VS Code": 20000, "Chrome": 2700}})
        e = _entry(store_mod.build_lane(wb), day_ago(1))
        assert "steady day" in e["note"] and "6.3h" in e["note"]
        assert "VS Code" in e["note"]


# ---------------------------------------------------------------- determinism

class TestDeterminism:
    def test_build_lane_deterministic(self, pet_dir):
        wb = _wb(history={day_ago(1): int(9.3 * 3600), day_ago(2): 12000},
                 app_hist={day_ago(1): {"Idle": 5400, "VS Code": 6600}},
                 hour_hist={day_ago(1): {"1": 4700, "2": 4700}})
        events = [_event("petSwitch", day_ago(1)) for _ in range(3)]
        a = store_mod.build_lane(wb, events)
        b = store_mod.build_lane(json.loads(json.dumps(wb)),
                                 json.loads(json.dumps(events)))
        assert a == b

    def test_day_note_deterministic(self, pet_dir):
        data = {"total": 15000, "apps": {"VS Code": 15000}, "hours": {},
                "errors": 0, "petSwitches": 0, "weekMax": 20000}
        assert (store_mod.day_note(day_ago(1), data)
                == store_mod.day_note(day_ago(1), dict(data)))
