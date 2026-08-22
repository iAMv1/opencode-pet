"""Task Orchard: the task list is a garden the pet lives in.

Tasks are trees: they grow only during ACTIVE time in a matching soil, ripen
at their estimate, and are settled by the pet — harvest XP + terroir tally,
the gamble wither check (double XP inside 1.5x, wither past it), the weekly
prune (old trees -> barter-bank refund), the day-close haiku, and the
"dancing toward" next-task rule. Plus the store lock/merge resilience and the
dashboard API validation, and the web-bridge parity entries.
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


def read_tasks(pet_dir):
    d = json.loads((pet_dir / "tasks.json").read_text(encoding="utf-8"))
    return d


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
    eng.bubble_until = 0
    eng.sessions = []
    eng._barter_bank = 0
    eng._last_orchard = 0.0
    eng._last_waggle = time.time()  # keep the ambient waggle out of unit tests
    return eng


def _task(**kw):
    now = time.time()
    t = {"id": kw.get("id", "t-test-%d" % int(now * 1000)),
         "title": kw.get("title", "Grow the store"),
         "soil": kw.get("soil", "code"),
         "estMin": kw.get("estMin", 30),
         "invested": kw.get("invested", 0),
         "status": kw.get("status", "seed"),
         "planted": kw.get("planted", now),
         "updated": kw.get("updated", now),
         "lastTs": kw.get("lastTs", now),
         "gambled": kw.get("gambled", False),
         "doneAt": kw.get("doneAt", None),
         "harvested": kw.get("harvested", False)}
    return t


def _fake_localtime(monkeypatch, dt):
    """Pin the weekday/hour seen by time.localtime so the prune (Sunday) and
    haiku (>= 22:00) gates are deterministic whenever the suite runs. Real
    timestamps keep their real date (task-planted "today" checks stay true)."""
    import time as _t
    real = _t.localtime

    def fake(ts=None):
        b = list(real(ts) if ts is not None else real())
        b[3] = dt.hour        # tm_hour
        b[6] = dt.weekday()   # tm_wday
        return _t.struct_time(b)

    monkeypatch.setattr(_t, "localtime", fake)


def _backdate(cur, ts):
    """Anchor every tree's lastTs (the engine's growth delta basis)."""
    for t in cur.get("tasks") or []:
        if isinstance(t, dict):
            t["lastTs"] = ts
    return cur


def _prime(eng, now, last_ts):
    """Clear the tick gate, anchor lastTs for all trees, run ONE maintenance
    pass at `now` (growth dt == now - last_ts)."""
    eng._last_orchard = 0.0
    store_mod.update_tasks(lambda cur: _backdate(cur, last_ts))
    eng._orchard_tick(now)


def _tick(eng, now):
    """Run one maintenance pass with no growth (lastTs == now -> dt 0)."""
    _prime(eng, now, now)


# ---------------------------------------------------------------- store layer

class TestStore:
    def test_corrupt_tasks_file_reads_default_garden(self, pet_dir):
        (pet_dir / "tasks.json").write_text("{ not json !!!", encoding="utf-8")
        d = store_mod.read_tasks()
        assert d["version"] == 1
        assert d["tasks"] == []
        assert d["terroir"] == {}

    def test_missing_tasks_file_reads_default_garden(self, pet_dir):
        d = store_mod.read_tasks()
        assert d["version"] == 1 and d["tasks"] == []

    def test_write_tasks_merges_by_id_preserving_other_trees(self, pet_dir):
        a = _task(id="a", invested=100)
        write(pet_dir, "tasks.json", {"version": 1, "tasks": [a]})
        b = _task(id="b")
        ok = store_mod.write_tasks({"tasks": [b], "terroir": {"code": {"harvests": 1, "mins": 5}}})
        assert ok is True
        d = read_tasks(pet_dir)
        assert {t["id"] for t in d["tasks"]} == {"a", "b"}
        by_id = {t["id"]: t for t in d["tasks"]}
        assert by_id["a"]["invested"] == 100      # concurrent growth survived
        assert d["terroir"]["code"]["harvests"] == 1

    def test_update_tasks_returns_false_when_fn_skips(self, pet_dir):
        assert store_mod.update_tasks(lambda cur: None) is False
        # the lock's O_CREAT may leave an empty file; nothing is ever written
        assert store_mod.read_tasks()["tasks"] == []

    def test_update_tasks_rebases_on_fresh_state(self, pet_dir):
        write(pet_dir, "tasks.json", {"version": 1, "tasks": [_task(id="a")]})
        # simulate a plant landing between read and write: the update fn sees
        # the freshest on-disk state, not a stale snapshot
        def mutate(cur):
            cur.setdefault("tasks", []).append(_task(id="b"))
            return cur
        assert store_mod.update_tasks(mutate) is True
        assert {t["id"] for t in read_tasks(pet_dir)["tasks"]} == {"a", "b"}

    def test_soil_for_app_keywords(self, pet_dir):
        assert store_mod.soil_for_app("Visual Studio Code") == "code"
        assert store_mod.soil_for_app("opencode") == "code"
        assert store_mod.soil_for_app("Google Chrome") == "read"
        assert store_mod.soil_for_app("Microsoft Word") == "write"
        assert store_mod.soil_for_app("Discord") == "comm"
        assert store_mod.soil_for_app("") == "other"
        assert store_mod.soil_for_app("Totally Unknown App") == "other"

    def test_orchard_haiku_quiet_garden_is_empty(self, pet_dir):
        assert store_mod.orchard_haiku([]) == ""
        assert store_mod.orchard_haiku([_task(planted=time.time() - 5 * 86400)]) == ""

    def test_orchard_haiku_from_todays_activity(self, pet_dir):
        line = store_mod.orchard_haiku([_task(title="Refactor", soil="code"),
                                        _task(title="Old", planted=time.time() - 90000,
                                              doneAt=time.time())])
        assert "Refactor" in line and "code" in line and "harvest" in line
        assert len(line.splitlines()) == 3


# ---------------------------------------------------------------- plant + API

class TestPlantApi:
    def test_plant_valid_task(self, pet_dir):
        api = main.ControlApi()
        assert api.orchard_plant("Write the docs", "write", 45, True) is True
        d = read_tasks(pet_dir)
        t = d["tasks"][0]
        assert t["title"] == "Write the docs"
        assert t["soil"] == "write" and t["estMin"] == 45
        assert t["gambled"] is True and t["status"] == "seed"
        assert t["invested"] == 0 and t["doneAt"] is None

    def test_plant_validation_rejects_bad_input(self, pet_dir):
        api = main.ControlApi()
        assert api.orchard_plant("", "code", 30, False) is False
        assert api.orchard_plant("   ", "code", 30, False) is False
        assert api.orchard_plant("x" * 61, "code", 30, False) is False
        assert api.orchard_plant("ok title", "lava", 30, False) is False
        assert api.orchard_plant("ok title", "code", 0, False) is False
        assert api.orchard_plant("ok title", "code", 601, False) is False
        assert api.orchard_plant("ok title", "code", -5, False) is False
        assert api.orchard_plant(12345, "code", 30, False) is False
        assert not (pet_dir / "tasks.json").exists()

    def test_plant_clamps_estimate_and_coerces_gamble(self, pet_dir):
        api = main.ControlApi()
        assert api.orchard_plant("Fine", "code", "90", 1) is True
        t = read_tasks(pet_dir)["tasks"][0]
        assert t["estMin"] == 90 and t["gambled"] is True

    def test_delete_removes_only_that_tree(self, pet_dir):
        api = main.ControlApi()
        api.orchard_plant("Keep me")
        api.orchard_plant("Drop me")
        ids = [t["id"] for t in read_tasks(pet_dir)["tasks"]]
        assert api.orchard_delete(ids[1]) is True
        left = [t["title"] for t in read_tasks(pet_dir)["tasks"]]
        assert left == ["Keep me"]
        assert api.orchard_delete("nope") is False

    def test_harvest_marks_done_under_lock(self, pet_dir):
        api = main.ControlApi()
        api.orchard_plant("Ripe tree", estMin=1)
        tid = read_tasks(pet_dir)["tasks"][0]["id"]
        d = store_mod.update_tasks(lambda cur: _mark_ripe(cur, tid))
        assert d is True
        assert api.orchard_harvest(tid) is True
        t = read_tasks(pet_dir)["tasks"][0]
        assert t["status"] == "done" and t["doneAt"] is not None
        assert api.orchard_harvest(tid) is False   # no double mark
        assert api.orchard_harvest("missing") is False

    def test_get_orchard_state_shape(self, pet_dir):
        api = main.ControlApi()
        s = api.get_orchard_state()
        assert s["trees"] == [] and s["nextTask"] is None
        assert s["terroir"] == {} and s["prunedToday"] is False
        api.orchard_plant("A tree", "code", 30, False)
        s = api.get_orchard_state()
        assert len(s["trees"]) == 1
        assert s["trees"][0]["title"] == "A tree"


def _mark_ripe(cur, tid):
    for t in cur.get("tasks") or []:
        if isinstance(t, dict) and t.get("id") == tid:
            t["status"] = "ripe"
            t["invested"] = max(float(t.get("invested") or 0),
                                int(t.get("estMin") or 1) * 60)
    return cur


# ---------------------------------------------------------------- growth

class TestGrowth:
    def test_matching_app_grows_task(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        store_mod.write_tasks({"tasks": [_task(estMin=10)]})
        eng.os_active = True
        eng.os_app = "VS Code"
        now = time.time()
        _prime(eng, now, now - 30)        # 30s of matching code work
        t = read_tasks(pet_dir)["tasks"][0]
        assert t["invested"] == 30.0

    def test_non_matching_app_does_not_grow(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        store_mod.write_tasks({"tasks": [_task(estMin=10)]})
        eng.os_active = True
        eng.os_app = "Google Chrome"      # read soil, not code
        now = time.time()
        _prime(eng, now, now - 30)
        assert read_tasks(pet_dir)["tasks"][0]["invested"] == 0

    def test_other_soil_grows_in_any_app(self, pet_dir, no_window):
        """Regression: 'other'-soil trees never grew (soil != app_soil guard)."""
        eng = _eng(pet_dir, no_window)
        t = _task(estMin=10)
        t["soil"] = "other"
        store_mod.write_tasks({"tasks": [t]})
        eng.os_active = True
        eng.os_app = "VS Code"
        now = time.time()
        _prime(eng, now, now - 30)
        assert read_tasks(pet_dir)["tasks"][0]["invested"] == 30.0

    def test_idle_time_never_grows(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        store_mod.write_tasks({"tasks": [_task(estMin=10)]})
        eng.os_active = False             # screen idle
        now = time.time()
        _prime(eng, now, now - 30)
        assert read_tasks(pet_dir)["tasks"][0]["invested"] == 0

    def test_ripe_at_threshold_bubbles_and_logs(self, pet_dir, no_window, monkeypatch):
        # Pin the hour below ORCHARD_HAIKU_HOUR so the day-close haiku can
        # never race the ripe bubble regardless of when the suite runs.
        _fake_localtime(monkeypatch, datetime.datetime(2026, 1, 1, 12, 0, 0))
        eng = _eng(pet_dir, no_window)
        store_mod.write_tasks({"tasks": [_task(estMin=1)]})
        eng.os_active = True
        eng.os_app = "Terminal"
        now = time.time()
        _prime(eng, now, now - 60)        # 60s = 1 min estimate: ripe
        t = read_tasks(pet_dir)["tasks"][0]
        assert t["status"] == "ripe" and t["invested"] == 60.0
        assert "ripe" in eng.bubble_text
        ev = [r for r in read_log(pet_dir, eng)
              if r["kind"] == "orchard" and r["event"] == "ripe"]
        assert len(ev) == 1
        # already ripe: no re-bubble, no re-log
        eng.bubble_text = ""
        _tick(eng, now)
        assert "ripe" not in eng.bubble_text

    def test_growth_cadence_gate(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        store_mod.write_tasks({"tasks": [_task(estMin=10)]})
        eng.os_active = True
        eng.os_app = "VS Code"
        now = time.time()
        _tick(eng, now)
        eng._orchard_tick(now + 5)        # inside the 30s gate: skipped
        assert read_tasks(pet_dir)["tasks"][0]["lastTs"] == now

    def test_sleep_gap_never_credits(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        store_mod.write_tasks({"tasks": [_task(estMin=10)]})
        eng.os_active = True
        eng.os_app = "VS Code"
        now = time.time()
        _prime(eng, now, now - 500)       # 500s gap = sleep, not usage
        assert read_tasks(pet_dir)["tasks"][0]["invested"] == 0


# ---------------------------------------------------------------- harvest

class TestHarvest:
    def test_harvest_flow_awards_xp_once_and_tallies_terroir(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        api = main.ControlApi()
        api.orchard_plant("Ship it", "code", 30, False)
        tid = read_tasks(pet_dir)["tasks"][0]["id"]
        assert api.orchard_harvest(tid) is False    # seed: not harvestable
        store_mod.update_tasks(lambda cur: _mark_ripe(cur, tid))
        assert api.orchard_harvest(tid) is True     # api marks done
        t = read_tasks(pet_dir)["tasks"][0]
        assert t["status"] == "done" and t["doneAt"] is not None
        eng.os_active = True
        eng.os_app = "VS Code"
        now = time.time()
        _tick(eng, now)
        assert eng.xp == engine_mod.XP_ORCHARD
        assert "Harvested Ship it" in eng.bubble_text
        d = read_tasks(pet_dir)
        assert d["terroir"]["code"]["harvests"] == 1
        assert d["terroir"]["code"]["mins"] == 30      # 1800s / 60
        ev = [r for r in read_log(pet_dir, eng) if r["kind"] == "harvest"]
        assert len(ev) == 1 and ev[0]["xp"] == engine_mod.XP_ORCHARD
        # a full second tick: no double XP, no double tally
        eng.xp = 0
        _tick(eng, now + 1)
        assert eng.xp == 0
        assert read_tasks(pet_dir)["terroir"]["code"]["harvests"] == 1

    def test_gamble_within_budget_doubles_xp(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        api = main.ControlApi()
        store_mod.write_tasks({"tasks": [_task(estMin=60, gambled=True,
                                               status="ripe", invested=5400)]})
        tid = read_tasks(pet_dir)["tasks"][0]["id"]
        assert api.orchard_harvest(tid) is True        # harvest-request
        eng.os_active = True
        eng.os_app = "VS Code"
        _tick(eng, time.time())           # 90m < 1.5x of 60m: gambled win
        assert eng.xp == engine_mod.XP_ORCHARD * 2
        assert "Harvested" in eng.bubble_text

    def test_gamble_over_budget_withers_no_xp(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        api = main.ControlApi()
        store_mod.write_tasks({"tasks": [_task(estMin=60, gambled=True,
                                               status="ripe", invested=6000)]})
        tid = read_tasks(pet_dir)["tasks"][0]["id"]
        assert api.orchard_harvest(tid) is True        # harvest-request
        eng.os_active = True
        eng.os_app = "VS Code"
        _tick(eng, time.time())           # 100m > 1.5x: withers
        assert eng.xp == 0
        t = read_tasks(pet_dir)["tasks"][0]
        assert t["status"] == "pruned" and t["harvested"] is True
        assert "withered" in eng.bubble_text
        ev = [r for r in read_log(pet_dir, eng)
              if r["kind"] == "orchard" and r["event"] == "wither"]
        assert len(ev) == 1
        # no terroir for a withered tree
        assert read_tasks(pet_dir)["terroir"] == {}

    def test_non_gambled_late_harvest_never_withers(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        api = main.ControlApi()
        store_mod.write_tasks({"tasks": [_task(estMin=60, gambled=False,
                                               status="ripe", invested=9000)]})
        tid = read_tasks(pet_dir)["tasks"][0]["id"]
        assert api.orchard_harvest(tid) is True
        eng.os_active = True
        eng.os_app = "VS Code"
        _tick(eng, time.time())
        assert eng.xp == engine_mod.XP_ORCHARD


# ---------------------------------------------------------------- prune

class TestPrune:
    def test_old_tree_pruned_and_bank_refunded(self, pet_dir, no_window, monkeypatch):
        _fake_localtime(monkeypatch,
                        datetime.datetime(2026, 8, 2, 10, 0, 0))  # Sunday
        eng = _eng(pet_dir, no_window)
        old = _task(id="old", estMin=45, planted=time.time() - 8 * 86400,
                    status="growing", invested=300)
        young = _task(id="young", planted=time.time() - 2 * 86400)
        store_mod.write_tasks({"tasks": [old, young]})
        _tick(eng, time.time())
        d = read_tasks(pet_dir)
        by_id = {t["id"]: t for t in d["tasks"]}
        assert by_id["old"]["status"] == "pruned"
        assert by_id["young"]["status"] == "seed"
        assert eng._barter_bank == 45 // 5          # energy returned
        assert main.load_config()["barterBank"] == 45 // 5
        assert d["pruneDate"] == time.strftime("%Y-%m-%d")
        ev = [r for r in read_log(pet_dir, eng)
              if r["kind"] == "orchard" and r["event"] == "prune"]
        assert len(ev) == 1 and ev[0]["refund"] == 9
        assert "Pruned" in eng.bubble_text

    def test_prune_not_run_twice_same_day(self, pet_dir, no_window, monkeypatch):
        _fake_localtime(monkeypatch,
                        datetime.datetime(2026, 8, 2, 11, 0, 0))  # Sunday
        eng = _eng(pet_dir, no_window)
        old = _task(id="old", estMin=45, planted=time.time() - 8 * 86400,
                    status="growing", invested=300)
        store_mod.write_tasks({"tasks": [old]})
        now = time.time()
        _tick(eng, now)
        eng._barter_bank = 0
        _tick(eng, now + 1)                         # same Sunday: no re-run
        assert eng._barter_bank == 0
        assert len([r for r in read_log(pet_dir, eng)
                    if r["kind"] == "orchard" and r["event"] == "prune"]) == 1

    def test_prune_due_after_seven_days_any_weekday(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        old = _task(id="old", estMin=20, planted=time.time() - 9 * 86400)
        store_mod.write_tasks({"tasks": [old], "pruneDate": "2026-07-26"})
        _tick(eng, time.time())
        assert read_tasks(pet_dir)["tasks"][0]["status"] == "pruned"

    def test_fresh_garden_not_pruned_before_sunday(self, pet_dir, no_window, monkeypatch):
        _fake_localtime(monkeypatch,
                        datetime.datetime(2026, 8, 5, 12, 0, 0))  # Wednesday
        eng = _eng(pet_dir, no_window)
        store_mod.write_tasks({"tasks": [_task(id="young",
                                               planted=time.time() - 8 * 86400)]})
        _tick(eng, time.time())
        assert read_tasks(pet_dir)["tasks"][0]["status"] == "seed"


# ---------------------------------------------------------------- next task

class TestNextTask:
    def test_ripe_tree_has_priority(self, pet_dir):
        tasks = [_task(id="ripe1", status="ripe", updated=time.time() - 90),
                 _task(id="ripe2", status="ripe", updated=time.time() - 10),
                 _task(id="grow", status="growing", invested=100)]
        nxt = store_mod.orchard_next_task(tasks)
        assert nxt["id"] == "ripe1"                 # oldest ripe first

    def test_closest_to_ripe_wins(self, pet_dir):
        tasks = [_task(id="far", invested=60, estMin=120),
                 _task(id="near", invested=110, estMin=120)]
        assert store_mod.orchard_next_task(tasks)["id"] == "near"

    def test_soil_match_bonus_beats_closer_tree(self, pet_dir):
        tasks = [_task(id="match", invested=10, estMin=120, soil="code"),
                 _task(id="closer", invested=50, estMin=120, soil="read")]
        nxt = store_mod.orchard_next_task(tasks, app="Visual Studio Code")
        assert nxt["id"] == "match"

    def test_empty_garden_is_none(self, pet_dir):
        assert store_mod.orchard_next_task([]) is None
        assert store_mod.orchard_next_task([_task(status="done")]) is None

    def test_engine_next_reads_through_cache(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        store_mod.write_tasks({"tasks": [_task(status="ripe", updated=0)]})
        nxt = eng._orchard_next(time.time())
        assert nxt is not None and nxt["status"] == "ripe"


# ---------------------------------------------------------------- haiku

class TestHaiku:
    def test_day_close_haiku_fires_once(self, pet_dir, no_window, monkeypatch):
        _fake_localtime(monkeypatch,
                        datetime.datetime(2026, 8, 7, 22, 30, 0))
        eng = _eng(pet_dir, no_window)
        store_mod.write_tasks({"tasks": [_task(title="Refactor store")]})
        now = time.time()
        _tick(eng, now)
        assert len(eng.bubble_text.splitlines()) == 3
        assert "Refactor" in eng.bubble_text
        assert read_tasks(pet_dir)["haikuDate"] == time.strftime("%Y-%m-%d")
        assert [r for r in read_log(pet_dir, eng) if r["kind"] == "haiku"]
        eng.bubble_text = ""
        _tick(eng, now + 1)
        assert eng.bubble_text == ""                # once per day only

    def test_no_haiku_without_activity(self, pet_dir, no_window, monkeypatch):
        _fake_localtime(monkeypatch,
                        datetime.datetime(2026, 8, 7, 22, 30, 0))
        eng = _eng(pet_dir, no_window)
        store_mod.write_tasks({"tasks": [_task(planted=time.time() - 90000)]})
        eng._orchard_tick(time.time())
        assert eng.bubble_text == ""
        assert not read_tasks(pet_dir)["haikuDate"]

    def test_no_haiku_before_dayclose_hour(self, pet_dir, no_window, monkeypatch):
        _fake_localtime(monkeypatch,
                        datetime.datetime(2026, 8, 7, 15, 0, 0))
        eng = _eng(pet_dir, no_window)
        store_mod.write_tasks({"tasks": [_task(title="Refactor store")]})
        eng._orchard_tick(time.time())
        assert eng.bubble_text == ""


# ---------------------------------------------------------------- parity

def test_parity_entries(pet_dir):
    for m in ("get_orchard_state", "orchard_plant", "orchard_harvest",
              "orchard_delete"):
        assert m in main._WEB_METHODS
        assert hasattr(main.ControlApi, m)
