"""Activity-log pruning (P10): size cap, once-per-day guard, age window,
corrupt-file tolerance. store.prune_activity_log must never raise and must
never lose the newest events (the engine's append path depends on it).
"""

import json
import os
import time

import pytest

from desktop import store


def _write_log(pet_dir, pet_id, n, age_hours=0):
    """Write n events to the pet's activity log; every event `age_hours`
    before now, then aged so the LAST line is the most recent."""
    path = os.path.join(str(pet_dir), "activity-%s.jsonl" % pet_id)
    base = time.time() - age_hours * 3600
    with open(path, "w", encoding="utf-8") as fh:
        for i in range(n):
            fh.write(json.dumps({"t": base + i, "kind": "state"}) + "\n")
    return path


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return [json.loads(ln) for ln in fh if ln.strip()]


class TestPrune:
    def test_small_log_untouched(self, pet_dir):
        path = _write_log(pet_dir, "capvolt", 20)
        before = open(path, encoding="utf-8").read()
        assert store.prune_activity_log("capvolt", {}) is False
        assert open(path, encoding="utf-8").read() == before

    def test_missing_file_noop(self, pet_dir):
        assert store.prune_activity_log("capvolt", {}) is False

    def test_size_threshold_keeps_newest(self, pet_dir):
        path = _write_log(pet_dir, "capvolt", 20000)
        assert os.path.getsize(path) > store.ACTIVITY_MAX_BYTES
        assert store.prune_activity_log("capvolt", {}) is True
        events = _read(path)
        assert len(events) <= store.ACTIVITY_PRUNE_LINES
        assert os.path.getsize(path) <= store.ACTIVITY_MAX_BYTES
        # the newest events survive — last line written is still there
        assert events[-1]["t"] == pytest.approx(events[-2]["t"] + 1)

    def test_once_per_day_guard(self, pet_dir):
        path = _write_log(pet_dir, "capvolt", 20000)
        today = time.strftime("%Y-%m-%d")
        assert store.prune_activity_log("capvolt", {"pruneDate": today}) is False
        assert os.path.getsize(path) > store.ACTIVITY_MAX_BYTES  # untouched

    def test_old_events_trigger(self, pet_dir):
        path = _write_log(pet_dir, "capvolt", 20, age_hours=31 * 24)
        assert store.prune_activity_log("capvolt", {}) is True
        assert _read(path) == []  # everything older than 30 days

    def test_mixed_age_keeps_only_fresh(self, pet_dir):
        path = _write_log(pet_dir, "capvolt", 10, age_hours=31 * 24)
        now = time.time()
        with open(path, "a", encoding="utf-8") as fh:
            for i in range(5):
                fh.write(json.dumps({"t": now + i, "kind": "state"}) + "\n")
        assert store.prune_activity_log("capvolt", {}) is True
        events = _read(path)
        assert len(events) == 5  # old events dropped, fresh kept, order intact
        assert events[0]["t"] < events[-1]["t"]

    def test_guard_persisted_after_prune(self, pet_dir):
        _write_log(pet_dir, "capvolt", 20000)
        assert store.prune_activity_log("capvolt", {}) is True
        with open(os.path.join(str(pet_dir), "config.json"), encoding="utf-8") as fh:
            cfg = json.load(fh)
        assert cfg.get(store.ACTIVITY_PRUNE_KEY) == time.strftime("%Y-%m-%d")
        # a second prune on the same day is a no-op
        assert store.prune_activity_log("capvolt", cfg) is False

    def test_corrupt_file_tolerated(self, pet_dir):
        """Garbage lines must never raise out of prune — the engine appends
        through the same file."""
        path = os.path.join(str(pet_dir), "activity-capvolt.jsonl")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("not json\n" * 60000)
        assert os.path.getsize(path) > store.ACTIVITY_MAX_BYTES
        assert store.prune_activity_log("capvolt", {}) is True  # no raise
        # the append path still works afterwards
        with open(path, "a", encoding="utf-8") as fh:
            fh.write('{"t": 1, "kind": "poke"}\n')

    def test_small_corrupt_first_line_noop(self, pet_dir):
        path = os.path.join(str(pet_dir), "activity-capvolt.jsonl")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("garbage\n")
        assert store.prune_activity_log("capvolt", {}) is False
        assert open(path, encoding="utf-8").read() == "garbage\n"


class TestEngineHook:
    def test_log_append_triggers_prune(self, pet_dir, no_window):
        """The engine's _log path must both append AND cap the log — the
        prune hook lives inside the append's try/except, so a prune failure
        can never break the write."""
        import desktop.main as main

        eng = main.PetEngine()
        _write_log(pet_dir, eng.pet["id"], 20000)
        size_before = os.path.getsize(
            os.path.join(str(pet_dir), "activity-%s.jsonl" % eng.pet["id"]))
        assert size_before > store.ACTIVITY_MAX_BYTES
        eng._log("poke")
        size_after = os.path.getsize(
            os.path.join(str(pet_dir), "activity-%s.jsonl" % eng.pet["id"]))
        assert size_after <= store.ACTIVITY_MAX_BYTES
        events = _read(os.path.join(str(pet_dir),
                                    "activity-%s.jsonl" % eng.pet["id"]))
        assert events[-1]["kind"] == "poke"   # the new event survived

    def test_prune_runs_once_per_day(self, pet_dir, no_window):
        import desktop.main as main

        eng = main.PetEngine()
        _write_log(pet_dir, eng.pet["id"], 20000)
        eng._log("poke")
        assert eng._prune_checked == time.strftime("%Y-%m-%d")
        # same-day second log does not re-read the (already small) file
        eng._log("jump")
        assert store.prune_activity_log(eng.pet["id"], eng.cfg) is False
