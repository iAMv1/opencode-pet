"""P8: Threshold Narrations — pet-voice insights from the week's REAL data.

Covers: each voice_insights line firing on a crafted fixture (deep-work /
night pattern / idle fog / variety / focus-honest / streak praise), the
4-line cap, the focus-honest line ONLY on zero-completion weeks, and the
get_wellbeing_insights API "voice" field (new field, old keys untouched).
"""

import datetime
import json
import time

import pytest

main = pytest.importorskip("desktop.main")
import desktop.store as store_mod  # noqa: E402


def day_ago(n):
    return (datetime.date.today() - datetime.timedelta(days=n)).isoformat()


def write(pet_dir, name, payload):
    p = pet_dir / name
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def _saturated_day():
    return {str(h): store_mod.CHRONO_ACTIVE_FLOOR for h in range(8)}


# ---------------------------------------------------------------- lines

class TestLines:
    def test_deep_work_line(self, pet_dir):
        hh = {day_ago(1): _saturated_day(), day_ago(2): _saturated_day(),
              day_ago(3): _saturated_day()}
        lines = store_mod.voice_insights({}, hh, {})
        assert any("wall-to-wall" in l and "3 days" in l for l in lines)

    def test_deep_work_needs_three_days(self, pet_dir):
        hh = {day_ago(1): _saturated_day(), day_ago(2): _saturated_day()}
        lines = store_mod.voice_insights({}, hh, {})
        assert not any("wall-to-wall" in l for l in lines)

    def test_night_pattern_line(self, pet_dir):
        hh = {day_ago(1): {"1": 7200, "2": 7200, "3": 7200, "15": 3600}}
        lines = store_mod.voice_insights({}, hh, {})
        assert any("midnight hours" in l for l in lines)

    def test_night_needs_to_outshine_afternoon(self, pet_dir):
        hh = {day_ago(1): {"1": 1000, "15": 7200}}
        lines = store_mod.voice_insights({}, hh, {})
        assert not any("midnight hours" in l for l in lines)

    def test_idle_fog_line_with_percent(self, pet_dir):
        ah = {day_ago(1): {"Idle": 10000, "VS Code": 9000}}
        lines = store_mod.voice_insights({}, {}, ah)
        assert any("52% of your week slipped into idle fog" in l for l in lines)

    def test_idle_line_gated_at_30_percent(self, pet_dir):
        ah = {day_ago(1): {"Idle": 2000, "VS Code": 8000}}
        lines = store_mod.voice_insights({}, {}, ah)
        assert not any("idle fog" in l for l in lines)

    def test_variety_hats_line(self, pet_dir):
        apps = {day_ago(1): {a: 600 for a in
                             ("VS Code", "Chrome", "Terminal", "Slack", "Figma")}}
        lines = store_mod.voice_insights({}, {}, apps)
        assert any("wore 5 hats" in l for l in lines)

    def test_variety_gated_at_five_apps(self, pet_dir):
        apps = {day_ago(1): {a: 600 for a in ("VS Code", "Chrome", "Terminal")}}
        lines = store_mod.voice_insights({}, {}, apps)
        assert not any("hats" in l for l in lines)

    def test_focus_honest_line_on_zero_completions(self, pet_dir):
        lines = store_mod.voice_insights({}, {}, {},
                                         focus={"starts": 3, "done": 0})
        assert any("lit 3 candles" in l and "burn out" in l for l in lines)

    def test_focus_honest_never_on_completed_week(self, pet_dir):
        lines = store_mod.voice_insights({}, {}, {},
                                         focus={"starts": 2, "done": 1})
        assert not any("candles" in l for l in lines)

    def test_focus_honest_needs_starts(self, pet_dir):
        lines = store_mod.voice_insights({}, {}, {}, focus={"starts": 0, "done": 0})
        assert not any("candles" in l for l in lines)

    def test_streak_praise_line(self, pet_dir):
        hist = {day_ago(i): store_mod.STREAK_MIN_SECS for i in range(3)}
        lines = store_mod.voice_insights(hist, {}, {})
        assert any("3 days in a row" in l and "counting with you" in l for l in lines)

    def test_streak_gated_at_three_days(self, pet_dir):
        hist = {day_ago(i): store_mod.STREAK_MIN_SECS for i in range(2)}
        lines = store_mod.voice_insights(hist, {}, {})
        assert not any("counting with you" in l for l in lines)


# ---------------------------------------------------------------- cap + api

class TestCapAndApi:
    def test_voice_capped_at_four_lines(self, pet_dir):
        hh = {day_ago(1): dict(_saturated_day(), **{"1": 7200}),
              day_ago(2): _saturated_day(), day_ago(3): _saturated_day()}
        ah = {day_ago(1): {"Idle": 10000, "VS Code": 9000,
                           "Chrome": 600, "Terminal": 600, "Slack": 600,
                           "Figma": 600, "Notion": 600}}
        hist = {day_ago(i): store_mod.STREAK_MIN_SECS for i in range(3)}
        lines = store_mod.voice_insights(hist, hh, ah,
                                         focus={"starts": 4, "done": 0})
        assert len(lines) <= store_mod.VOICE_MAX_LINES

    def test_empty_data_no_lines(self, pet_dir):
        assert store_mod.voice_insights({}, {}, {}) == []

    def test_api_voice_field_on_empty_wellbeing(self, pet_dir):
        s = main.ControlApi().get_wellbeing_insights()
        assert "voice" in s and s["voice"] == []
        assert "weekSeconds" in s and "bestDay" in s  # old keys untouched

    def test_api_voice_field_from_real_data(self, pet_dir):
        wb = {"date": time.strftime("%Y-%m-%d"), "apps": {},
              "history": {}, "appHistory": {},
              "hourHistory": {day_ago(1): {"1": 7200, "2": 7200, "3": 7200,
                                           "15": 3600}},
              "hourToday": {}}
        write(pet_dir, "wellbeing.json", wb)
        write(pet_dir, "activity-p0.jsonl",
              json.dumps({"t": time.time() - 60, "kind": "focusStart",
                          "targetMin": 25}) + "\n")
        s = main.ControlApi().get_wellbeing_insights()
        assert isinstance(s["voice"], list)
        assert any("midnight hours" in l for l in s["voice"])
        # the API contract stayed additive: old fields still present
        assert {"weekSeconds", "prevWeekSeconds", "deltaPct", "bestDay",
                "todaySeconds", "topApp"} <= set(s)
