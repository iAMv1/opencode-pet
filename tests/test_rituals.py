"""P7: Personal Rituals â€” daily rituals DERIVED from the user's OWN history
(no canned quests, no currency): guard_hour (historical best hour >= 1h avg),
beat_yesterday (yesterday >= 1h), break_the_idle (yesterday > 30% idle),
night_guard (night-owl chrono), first_light (lark chrono).

Covers: derivation firing per kind on crafted fixtures (and NOT on mismatched
data), priority + 3-ritual limit, per-kind completion detection against
real-data-shaped wellbeing, daily re-derivation (ritualDate guard), XP awarded
exactly once per ritual (ritualDone guard), and the quiet end-of-day bubble
(at 22:00+, only when something went unfinished, once per day, no XP).
"""

import datetime
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


def day_ago(n):
    return (datetime.date.today() - datetime.timedelta(days=n)).isoformat()


def _wb(history=None, hour_hist=None, app_hist=None, apps=None, hours=None):
    return {"date": time.strftime("%Y-%m-%d"), "apps": apps or {},
            "history": history or {}, "hourHistory": hour_hist or {},
            "appHistory": app_hist or {}, "hourToday": hours or {}}


def kinds(rs):
    return [r["kind"] for r in rs]


def _eng(pet_dir, no_window):
    eng = main.PetEngine()
    eng.xp = 0
    eng.level = 1
    eng.mood = "neutral"
    eng.bubble_until = 0
    eng.sessions = []
    return eng


# ---------------------------------------------------------------- derivation

class TestDerive:
    def test_guard_hour_fires_on_historical_peak(self, pet_dir):
        # hours 1-3 saturate >= 1h avg every day -> guard_hour at the peak
        wb = _wb(hour_hist={day_ago(1): {"1": 3600, "2": 3600, "3": 3600},
                            day_ago(2): {"1": 3600, "2": 3600, "3": 3600}})
        rs = store_mod.derive_rituals(wb, 0, {})
        assert "guard_hour" in kinds(rs)
        g = next(r for r in rs if r["kind"] == "guard_hour")
        assert g["hour"] == 1 and g["target"] == 30
        assert "1 AM" in g["desc"] and "2 AM" in g["desc"]

    def test_guard_hour_skips_when_peak_below_one_hour(self, pet_dir):
        # the user's own data says the best hour averages only 30 min
        wb = _wb(hour_hist={day_ago(1): {"1": 1800}, day_ago(2): {"1": 1800}})
        rs = store_mod.derive_rituals(wb, 0, {})
        assert "guard_hour" not in kinds(rs)

    def test_beat_yesterday_fires_on_yesterday_total(self, pet_dir):
        # real user shape: a 9.3h day yesterday
        wb = _wb(history={day_ago(1): int(9.3 * 3600)})
        rs = store_mod.derive_rituals(wb, 0, {})
        assert "beat_yesterday" in kinds(rs)
        b = next(r for r in rs if r["kind"] == "beat_yesterday")
        assert b["target"] == int(9.3 * 3600) // 60
        assert "9.3h" in b["desc"]

    def test_beat_yesterday_skips_under_one_hour(self, pet_dir):
        wb = _wb(history={day_ago(1): 1800})
        rs = store_mod.derive_rituals(wb, 0, {})
        assert "beat_yesterday" not in kinds(rs)

    def test_break_the_idle_fires_on_idle_heavy_yesterday(self, pet_dir):
        # real user shape: 45% idle yesterday (total in history, split in appHist)
        wb = _wb(history={day_ago(1): 12000},
                 app_hist={day_ago(1): {"VS Code": 6000, "Idle": 6000}})
        rs = store_mod.derive_rituals(wb, 0, {})
        assert "break_the_idle" in kinds(rs)
        b = next(r for r in rs if r["kind"] == "break_the_idle")
        assert b["target"] == 120
        assert "50%" in b["desc"]

    def test_break_the_idle_skips_low_idle_ratio(self, pet_dir):
        wb = _wb(history={day_ago(1): 10000},
                 app_hist={day_ago(1): {"VS Code": 8000, "Idle": 2000}})
        rs = store_mod.derive_rituals(wb, 0, {})
        assert "break_the_idle" not in kinds(rs)

    def test_night_guard_fires_for_night_owl_only(self, pet_dir):
        wb = _wb()
        rs = store_mod.derive_rituals(wb, 0, {"chronoType": "night_owl"})
        assert "night_guard" in kinds(rs)
        assert next(r for r in rs if r["kind"] == "night_guard")["target"] == 60
        assert "night_guard" not in kinds(store_mod.derive_rituals(wb, 0, {}))
        assert "night_guard" not in kinds(
            store_mod.derive_rituals(wb, 0, {"chronoType": "lark"}))

    def test_first_light_fires_for_lark_morning_peak(self, pet_dir):
        wb = _wb(hour_hist={day_ago(1): {"8": 3600, "9": 3600}})
        rs = store_mod.derive_rituals(wb, 0, {"chronoType": "lark"})
        assert "first_light" in kinds(rs)
        f = next(r for r in rs if r["kind"] == "first_light")
        assert f["hour"] == 8 and f["target"] == 30
        assert "8 AM" in f["desc"]
        assert "first_light" not in kinds(
            store_mod.derive_rituals(wb, 0, {"chronoType": "night_owl"}))

    def test_priority_order_and_three_limit(self, pet_dir):
        # all four independent kinds at once -> first three in priority order
        wb = _wb(history={day_ago(1): 8 * 3600},
                 hour_hist={day_ago(1): {"2": 3600, "3": 3600}},
                 app_hist={day_ago(1): {"VS Code": 14400, "Idle": 14400}})
        rs = store_mod.derive_rituals(wb, 0, {"chronoType": "night_owl"})
        assert len(rs) == store_mod.RITUAL_MAX_DAILY == 3
        assert kinds(rs) == ["guard_hour", "beat_yesterday", "break_the_idle"]

    def test_lone_ritual_returns_single(self, pet_dir):
        rs = store_mod.derive_rituals(_wb(), 0, {"chronoType": "night_owl"})
        assert kinds(rs) == ["night_guard"]

    def test_empty_data_derives_nothing(self, pet_dir):
        assert store_mod.derive_rituals({}, 0, {}) == []


# ---------------------------------------------------------------- completion

class TestProgress:
    def _rit(self, kind, **extra):
        r = {"id": kind, "kind": kind, "name": kind, "desc": "", "target": 30}
        r.update(extra)
        return r

    def test_guard_hour_done_from_hour_today(self, pet_dir):
        wb = _wb(hours={"3": 2000})
        r = self._rit("guard_hour", hour=3)
        p = store_mod.ritual_progress(r, wb, {})
        assert p == {"current": 33, "done": True}

    def test_guard_hour_not_done(self, pet_dir):
        wb = _wb(hours={"3": 1200})
        p = store_mod.ritual_progress(self._rit("guard_hour", hour=3), wb, {})
        assert p == {"current": 20, "done": False}

    def test_beat_yesterday_done_from_today_total(self, pet_dir):
        wb = _wb(apps={"VS Code": 7200})
        r = self._rit("beat_yesterday", target=120)
        assert store_mod.ritual_progress(r, wb, {})["done"] is True

    def test_break_the_idle_counts_active_minus_idle(self, pet_dir):
        wb = _wb(apps={"VS Code": 9000, "Idle": 6000})
        r = self._rit("break_the_idle", target=120)
        assert store_mod.ritual_progress(r, wb, {}) == {"current": 150, "done": True}

    def test_break_the_idle_not_done(self, pet_dir):
        wb = _wb(apps={"VS Code": 3600, "Idle": 6000})
        r = self._rit("break_the_idle", target=120)
        assert store_mod.ritual_progress(r, wb, {})["done"] is False

    def test_night_guard_sums_hours_0_to_6(self, pet_dir):
        wb = _wb(hours={"0": 1800, "1": 1800})
        r = self._rit("night_guard", target=60)
        assert store_mod.ritual_progress(r, wb, {}) == {"current": 60, "done": True}

    def test_first_light_morning_bucket(self, pet_dir):
        wb = _wb(hours={"8": 1800})
        r = self._rit("first_light", hour=8)
        assert store_mod.ritual_progress(r, wb, {})["done"] is True


# ---------------------------------------------------------------- engine

class TestEngineRituals:
    def test_derive_on_new_day_resets_daily(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        eng._wb = {"VS Code": 7200}
        eng._history = {day_ago(1): 2 * 3600}
        eng._wb_date = time.strftime("%Y-%m-%d")
        eng._hour_today = {}
        eng._hour_history = {}
        eng._app_history = {}
        eng._ritual_tick(time.time())
        assert eng.cfg["ritualDate"] == time.strftime("%Y-%m-%d")
        assert len(eng._rituals) >= 1
        c = main.load_config()
        assert c["ritualDate"] == time.strftime("%Y-%m-%d")
        assert [r["kind"] for r in c["ritualList"]] == ["beat_yesterday"]

    def test_stale_ritual_date_re_derives(self, pet_dir, no_window):
        write(pet_dir, "config.json", {"ritualDate": day_ago(1)})
        eng = _eng(pet_dir, no_window)
        eng._wb = {}
        eng._history = {day_ago(1): 2 * 3600}
        eng._wb_date = time.strftime("%Y-%m-%d")
        eng._hour_today = {}
        eng._hour_history = {}
        eng._app_history = {}
        eng._ritual_tick(time.time())
        assert eng.cfg["ritualDate"] == time.strftime("%Y-%m-%d")
        assert [r["kind"] for r in eng._rituals] == ["beat_yesterday"]

    def test_completion_awards_xp_once_and_logs(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        eng._wb = {"VS Code": 7200}
        eng._history = {day_ago(1): 2 * 3600}
        eng._wb_date = time.strftime("%Y-%m-%d")
        eng._hour_today = {}
        eng._hour_history = {}
        eng._app_history = {}
        eng._ritual_tick(time.time())
        assert eng.xp == engine_mod.XP_RITUAL
        assert eng.mood == "happy"
        assert "Ritual complete" in eng.bubble_text
        ev = [r for r in read_log(pet_dir, eng) if r["kind"] == "ritual"]
        assert len(ev) == 1 and ev[0]["id"] == "beat_yesterday"
        assert "beat_yesterday" in main.load_config()["ritualDone"]
        # second tick: ritualDone guard -> no re-award
        eng._ritual_tick(time.time())
        assert eng.xp == engine_mod.XP_RITUAL
        assert len([r for r in read_log(pet_dir, eng) if r["kind"] == "ritual"]) == 1

    def test_completion_guard_survives_restart(self, pet_dir, no_window):
        write(pet_dir, "config.json",
              {"ritualDate": time.strftime("%Y-%m-%d"),
               "ritualList": [{"id": "beat_yesterday", "kind": "beat_yesterday",
                               "name": "Match yesterday", "desc": "",
                               "target": 120, "hour": None}],
               "ritualDone": ["beat_yesterday"]})
        eng = _eng(pet_dir, no_window)
        eng._wb = {"VS Code": 7200}
        eng._history = {day_ago(1): 2 * 3600}
        eng._wb_date = time.strftime("%Y-%m-%d")
        eng._hour_today = {}
        eng._hour_history = {}
        eng._app_history = {}
        eng._ritual_tick(time.time())
        assert eng.xp == 0
        assert [r for r in read_log(pet_dir, eng) if r["kind"] == "ritual"] == []

    def test_guard_hour_completes_from_hour_today(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        eng._hour_history = {day_ago(1): {"2": 3600}, day_ago(2): {"2": 3600}}
        eng._hour_today = {2: 1800}
        eng._wb_date = time.strftime("%Y-%m-%d")
        eng._wb = {}
        eng._history = {}
        eng._app_history = {}
        eng._ritual_tick(time.time())
        assert kinds(eng._rituals) == ["guard_hour"]
        assert eng.xp == engine_mod.XP_RITUAL
        assert "guard_hour" in main.load_config()["ritualDone"]

    def test_night_guard_completes_from_night_hours(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        eng.cfg["chronoType"] = "night_owl"
        eng._hour_today = {0: 1800, 1: 1800}
        eng._wb_date = time.strftime("%Y-%m-%d")
        eng._wb = {}
        eng._history = {}
        eng._hour_history = {}
        eng._app_history = {}
        eng._ritual_tick(time.time())
        assert kinds(eng._rituals) == ["night_guard"]
        assert eng.xp == engine_mod.XP_RITUAL

    def test_end_of_day_quiet_bubble_once(self, pet_dir, no_window, monkeypatch):
        eng = _eng(pet_dir, no_window)
        eng._rituals = [{"id": "night_guard", "kind": "night_guard",
                         "name": "Night guard", "desc": "", "target": 60,
                         "current": 0, "done": False}]
        eng.cfg["ritualDate"] = time.strftime("%Y-%m-%d")
        eng._dayclose_date = ""
        monkeypatch.setattr(main.time, "localtime",
                            lambda *a: type("T", (), {"tm_hour": 22})())
        eng._ritual_tick(time.time())
        assert eng.bubble_text == "Tomorrow's a new day"
        assert eng.xp == 0  # quiet: no XP, no punishment
        ev = [r for r in read_log(pet_dir, eng) if r["kind"] == "dayclose"]
        assert len(ev) == 1 and ev[0]["pending"] == 1
        # second tick: closes once per day
        eng._ritual_tick(time.time())
        assert len([r for r in read_log(pet_dir, eng)
                    if r["kind"] == "dayclose"]) == 1

    def test_end_of_day_stays_quiet_when_all_done(self, pet_dir, no_window, monkeypatch):
        eng = _eng(pet_dir, no_window)
        eng._rituals = [{"id": "night_guard", "kind": "night_guard",
                         "name": "Night guard", "desc": "", "target": 60,
                         "current": 60, "done": True}]
        eng._ritual_done = {"night_guard"}
        eng._hour_today = {0: 3600}   # real data: the deep hour was banked
        eng._wb_date = time.strftime("%Y-%m-%d")
        eng.cfg["ritualDate"] = time.strftime("%Y-%m-%d")
        eng._dayclose_date = ""
        monkeypatch.setattr(main.time, "localtime",
                            lambda *a: type("T", (), {"tm_hour": 23})())
        eng._ritual_tick(time.time())
        assert "Tomorrow" not in eng.bubble_text
        assert [r for r in read_log(pet_dir, eng) if r["kind"] == "dayclose"] == []

    def test_end_of_day_not_before_22(self, pet_dir, no_window, monkeypatch):
        eng = _eng(pet_dir, no_window)
        eng._rituals = [{"id": "night_guard", "kind": "night_guard",
                         "name": "Night guard", "desc": "", "target": 60,
                         "current": 0, "done": False}]
        eng.cfg["ritualDate"] = time.strftime("%Y-%m-%d")
        eng._dayclose_date = ""
        monkeypatch.setattr(main.time, "localtime",
                            lambda *a: type("T", (), {"tm_hour": 21})())
        eng._ritual_tick(time.time())
        assert [r for r in read_log(pet_dir, eng) if r["kind"] == "dayclose"] == []

