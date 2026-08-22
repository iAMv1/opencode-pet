"""Persistence + progress-integrity regressions for the gauntlet-loop audit.

Covers the failure chains nobody had tested:
- a settings toggle / pet switch must never roll back xp/level/goal/chrono
  (the engine must persist only the keys it actually changed),
- a crash mid-write on wellbeing.json must recover from the .bak snapshot
  instead of silently wiping the history,
- a corrupt locked file (config/tasks) is quarantined as .corrupt and the
  last good snapshot survives the next save,
- the day-close haiku defers behind a live bubble instead of stomping it.
"""

import datetime
import json
import time

import pytest

main = pytest.importorskip("desktop.main")
store = pytest.importorskip("desktop.store")
sprites = pytest.importorskip("desktop.sprites")
engine_mod = pytest.importorskip("desktop.engine")


def _active_engine(pet_dir, no_window, monkeypatch):
    monkeypatch.setattr(main, "last_input_ms", lambda: 0)
    monkeypatch.setattr(main, "foreground_app", lambda: "VS Code")
    eng = main.PetEngine()
    eng.sessions = []
    eng.bubble_until = 0
    return eng


class TestNoProgressRollback:
    def test_config_watch_keeps_progress(self, pet_dir, no_window, monkeypatch):
        """Regression: config_watch used to save_config(self.cfg) — the whole
        boot-stale snapshot — so toggling any setting silently reverted
        xp/level/mood/lastGoalDate written by fresher subsystem saves."""
        eng = _active_engine(pet_dir, no_window, monkeypatch)
        today = time.strftime("%Y-%m-%d")
        # subsystems wrote fresh progress to disk AFTER the engine booted
        store.save_config({"xp": 500, "level": 7, "mood": "happy",
                           "lastGoalDate": today})
        # the engine's in-memory snapshot is stale (boot state)
        eng.cfg["xp"] = 0
        eng.cfg["level"] = 1
        eng.cfg["mood"] = "neutral"
        eng.cfg["lastGoalDate"] = ""
        # user flips one setting from the control process
        store.save_config({"walk": 55})
        eng.config_watch()
        c = store.load_config()
        assert c["walk"] == 55
        assert c["xp"] == 500 and c["level"] == 7 and c["mood"] == "happy"
        assert c["lastGoalDate"] == today

    def test_set_pet_keeps_progress(self, pet_dir, no_window, monkeypatch):
        """Regression: set_pet persisted the full stale cfg on every switch."""
        eng = _active_engine(pet_dir, no_window, monkeypatch)
        store.save_config({"xp": 400, "level": 6})
        eng.cfg["xp"] = 0
        eng.cfg["level"] = 1
        new_idx = (eng.cfg["petIdx"] + 1) % len(sprites.PETS)
        eng.set_pet(new_idx)
        c = store.load_config()
        assert c["petIdx"] % len(sprites.PETS) == new_idx
        assert c["xp"] == 400 and c["level"] == 6

    def test_toggle_still_persists_its_own_key(self, pet_dir, no_window, monkeypatch):
        eng = _active_engine(pet_dir, no_window, monkeypatch)
        store.save_config({"perchChatter": True})
        eng.cfg["perchChatter"] = True
        store.save_config({"perchChatter": False})
        eng.config_watch()
        assert store.load_config()["perchChatter"] is False


class TestCrashRecovery:
    def test_truncated_wellbeing_recovers_from_bak(self, pet_dir):
        """A crash mid-write leaves truncated JSON; read_wellbeing must fall
        back to the .bak snapshot rather than None (which let the next save
        persist an empty state — a silent 30-day memory wipe)."""
        today = time.strftime("%Y-%m-%d")
        good = {"date": today, "apps": {"VS Code": 3600},
                "history": {today: 3600}, "appHistory": {}, "hourToday": {},
                "hourHistory": {}}
        # two writes: the second snapshots the first into .bak (a first-ever
        # write has no previous bytes to back up, by design)
        assert store.atomic_write_json(store.WELLBEING_FILE, good)
        assert store.atomic_write_json(store.WELLBEING_FILE, good)
        # simulate the torn write
        with open(store.WELLBEING_FILE, "w", encoding="utf-8") as fh:
            fh.write('{"date": "20')
        d = store.read_wellbeing()
        assert isinstance(d, dict)
        assert d["apps"]["VS Code"] == 3600

    def test_corrupt_config_quarantined_and_recovered(self, pet_dir):
        """Locked-path corruption: bytes are preserved as .corrupt and the
        next save re-bases on the last good snapshot instead of defaults."""
        store.save_config({"goalMin": 120, "chimes": True})
        # corrupt the file behind the lock's back
        with open(store.CONFIG_FILE, "w", encoding="utf-8") as fh:
            fh.write('{"goalMin": 12')
        store.save_config({"walk": 30})  # triggers quarantine + bak restore
        assert (pet_dir / "config.json.corrupt").exists()
        c = store.load_config()
        assert c["goalMin"] == 120      # restored from .bak, not defaulted
        assert c["chimes"] is True
        assert c["walk"] == 30          # fresh write merged on top

    def test_atomic_write_leaves_no_tmp(self, pet_dir):
        p = pet_dir / "wellbeing.json"
        store.atomic_write_json(str(p), {"a": 1})
        assert json.loads(p.read_text(encoding="utf-8")) == {"a": 1}
        assert not (pet_dir / "wellbeing.json.tmp").exists()


class TestHaikuDefers:
    def test_haiku_never_stomps_live_bubble(self, pet_dir, no_window, monkeypatch):
        """Regression: at ORCHARD_HAIKU_HOUR the day-close haiku fired on the
        same tick that ripened a tree and overwrote its bubble."""
        import desktop.engine as eng_mod

        real_localtime = time.localtime

        def late(ts=None):
            b = list(real_localtime(ts) if ts is not None else real_localtime())
            b[3] = 23  # tm_hour past the haiku gate
            return time.struct_time(b)

        monkeypatch.setattr(time, "localtime", late)
        monkeypatch.setattr(main, "foreground_app", lambda: "Terminal")
        eng = _active_engine(pet_dir, no_window, monkeypatch)
        eng.os_active = True
        eng.os_app = "Terminal"
        now = time.time()
        t = {"id": "t-h", "title": "Grow the store", "soil": "code",
             "estMin": 1, "invested": 0.0, "status": "growing",
             "planted": now - 3600, "updated": now, "lastTs": now - 60,
             "gambled": False, "doneAt": None, "harvested": False}
        store.write_tasks({"tasks": [t]})
        eng._last_orchard = 0.0
        eng._orchard_tick(now)  # one pass: growth ripens the tree, haiku defers
        assert "ripe" in eng.bubble_text
        # haiku deferred: date not yet consumed by the stomped attempt
        cur2 = store.read_tasks()
        assert str(cur2.get("haikuDate") or "") != time.strftime("%Y-%m-%d")


class TestBubblePriority:
    def _eng(self, pet_dir, no_window, monkeypatch):
        eng = _active_engine(pet_dir, no_window, monkeypatch)
        eng.bubble_text = ""
        eng.bubble_until = 0.0
        eng.bubble_pri = 0
        return eng

    def test_ambient_blocked_while_milestone_live(self, pet_dir, no_window, monkeypatch):
        eng = self._eng(pet_dir, no_window, monkeypatch)
        now = time.time()
        assert eng._say("Daily goal met!", 60,
                        pri=eng.BUBBLE_PRI_MILESTONE, now=now)
        assert not eng._say("In VS Code", 5,
                            pri=eng.BUBBLE_PRI_AMBIENT, now=now + 1)
        assert eng.bubble_text == "Daily goal met!"

    def test_reactive_blocked_while_milestone_live(self, pet_dir, no_window, monkeypatch):
        eng = self._eng(pet_dir, no_window, monkeypatch)
        now = time.time()
        eng._say("Harvested tree! +10 XP", 30,
                 pri=eng.BUBBLE_PRI_MILESTONE, now=now)
        assert not eng._say("Running a shell command", 6,
                            pri=eng.BUBBLE_PRI_REACTIVE, now=now + 1)
        assert eng.bubble_text == "Harvested tree! +10 XP"

    def test_equal_priority_may_replace(self, pet_dir, no_window, monkeypatch):
        eng = self._eng(pet_dir, no_window, monkeypatch)
        now = time.time()
        eng._say("Searching the codebase", 6,
                 pri=eng.BUBBLE_PRI_REACTIVE, now=now)
        assert eng._say("Reading a file", 6,
                        pri=eng.BUBBLE_PRI_REACTIVE, now=now + 1)
        assert eng.bubble_text == "Reading a file"

    def test_takes_over_after_expiry(self, pet_dir, no_window, monkeypatch):
        eng = self._eng(pet_dir, no_window, monkeypatch)
        now = time.time()
        eng._say("Daily goal met!", 60, pri=eng.BUBBLE_PRI_MILESTONE, now=now)
        later = now + 61
        assert eng._say("In VS Code", 5,
                        pri=eng.BUBBLE_PRI_AMBIENT, now=later)
        assert eng.bubble_text == "In VS Code"
        assert eng.bubble_pri == eng.BUBBLE_PRI_AMBIENT


class TestFocusTagOwnership:
    def _focus_engine(self, pet_dir, no_window, monkeypatch):
        eng = _active_engine(pet_dir, no_window, monkeypatch)
        eng.start_focus(25)
        return eng

    def test_dashboard_tag_survives_engine_save(self, pet_dir, no_window, monkeypatch):
        eng = self._focus_engine(pet_dir, no_window, monkeypatch)
        # dashboard writes the tag directly (cross-process path)
        ok = store.update_focus(lambda d: {**d, "tag": "Work"} if d.get("active") else None)
        assert ok
        eng.focus_started = time.time() - 5  # force a periodic save path
        eng._save_focus_state()
        d = json.loads((pet_dir / "focus.json").read_text(encoding="utf-8"))
        assert d["tag"] == "Work"

    def test_dashboard_tag_clear_survives_engine_save(self, pet_dir, no_window, monkeypatch):
        """Regression: clearing the tag from the dashboard was undone seconds
        later — the engine kept its stale in-memory copy and wrote it back."""
        eng = self._focus_engine(pet_dir, no_window, monkeypatch)
        store.update_focus(lambda d: {**d, "tag": "Work"})
        eng._save_focus_state()          # engine adopts Work
        assert eng._focus_tag == "Work"
        store.update_focus(lambda d: {**d, "tag": ""})   # user clears it
        eng._save_focus_state()          # next engine save must keep it cleared
        d = json.loads((pet_dir / "focus.json").read_text(encoding="utf-8"))
        assert d["tag"] == ""
        assert eng._focus_tag == ""


class TestBarterOfferLifecycle:
    def _barter_engine(self, pet_dir, no_window, monkeypatch):
        eng = _active_engine(pet_dir, no_window, monkeypatch)
        eng._barter_bank = 10_000
        eng._barter_stage = 0
        eng._barter_offer_date = ""
        eng.cfg["barterOfferSince"] = ""
        return eng

    def test_fresh_offer_not_instantly_expired_after_payment(self, pet_dir, no_window, monkeypatch):
        """Regression: paying an offer left barterOfferSince stale, so the
        NEXT offer quiet-expired on its first tick after being made."""
        import datetime as _dt
        eng = self._barter_engine(pet_dir, no_window, monkeypatch)
        old = (_dt.date.today() - _dt.timedelta(days=10)).isoformat()
        eng.cfg["barterOfferSince"] = old      # offer made 10 days ago
        eng._barter_offer_date = old
        assert eng._barter_pay()               # pay the standing offer
        assert eng.cfg["barterOfferSince"] == ""
        # a fresh ask on a later tick must start a NEW clock
        now = time.time()
        eng._barter_tick(now)
        assert eng._barter_offer_date == time.strftime("%Y-%m-%d")
        assert eng.cfg["barterOfferSince"] == time.strftime("%Y-%m-%d")
        assert "trade" in (eng.bubble_text or "")

    def test_stale_offer_quietly_expires(self, pet_dir, no_window, monkeypatch):
        import datetime as _dt
        eng = self._barter_engine(pet_dir, no_window, monkeypatch)
        old = (_dt.date.today() - _dt.timedelta(days=store.BARTER_EXPIRE_DAYS)).isoformat()
        eng.cfg["barterOfferSince"] = old
        eng._barter_offer_date = old
        eng._barter_tick(time.time())
        # suppressed until tomorrow, clock cleared for the fresh offer
        assert eng._barter_offer_date == time.strftime("%Y-%m-%d")
        assert eng.cfg["barterOfferSince"] == ""
