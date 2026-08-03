"""Load / stress / edge-case tests.

Simulates realistic production conditions that the pet process must survive
without crashing or degrading: hundreds of status files (valid + corrupt +
weird states), rapid config.json churn from the control process, and large
activity/wellbeing files.
"""

import json
import time

import pytest

main = pytest.importorskip("desktop.main")


def write(pet_dir, name, payload):
    p = pet_dir / name
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


class TestStatusLoad:
    def test_300_files_mixed_validity(self, pet_dir):
        """300 files: 260 valid across all states + 40 corrupt, must not crash
        and must return only the parseable ones, newest first."""
        now = int(time.time() * 1000)
        states = ["busy", "thinking", "error", "idle", "success", "celebrating",
                  "waiting", "retry"]
        for i in range(260):
            write(pet_dir, "status-s%03d.json" % i,
                  {"sessionID": "s%d" % i, "state": states[i % len(states)],
                   "updatedAt": now - i * 1000})
        for i in range(40):
            (pet_dir / ("status-bad%03d.json" % i)).write_text(
                "not json" if i % 2 else '{"state":', encoding="utf-8")
        main.read_status()  # warmup (cold first read pays filesystem cache cost)
        t0 = time.perf_counter()
        out = main.read_status()
        dt = (time.perf_counter() - t0) * 1000
        assert len(out) == 260
        # newest first
        assert out[0]["sessionID"] == "s0"
        assert out[-1]["sessionID"] == "s259"
        # stale flag must be consistent with each file's timestamp. The
        # cutoff is computed after the read, so files within a tolerance band
        # of the 25s boundary are ambiguous (read-time vs check-time clock
        # drift); skip those instead of asserting exact equality.
        cutoff = int(time.time() * 1000) - main.STALE_MS
        checked = 0
        for s in out:
            age_ms = cutoff - (s.get("updatedAt") or 0)
            if abs(age_ms) < 1000:
                continue  # too close to the boundary to be deterministic
            expect_stale = age_ms >= 0
            assert s["stale"] == expect_stale, s
            checked += 1
        assert checked >= len(out) - 3  # at most the boundary-adjacent files skip
        assert dt < 3000, "read_status too slow under load: %.1f ms" % dt

    def test_unicode_and_weird_states_survive(self, pet_dir):
        write(pet_dir, "status-u1.json",
              {"sessionID": "u1", "state": "thinking", "updatedAt": int(time.time() * 1000),
               "message": "emoji \U0001f600 \u2603 \u2014 unicode", "toolLabel": "\u00fcber tool"})
        out = main.read_status()
        assert out and out[0]["message"].startswith("emoji")
        assert out[0]["toolLabel"] == "\u00fcber tool"

    def test_huge_message_field(self, pet_dir):
        write(pet_dir, "status-big.json",
              {"sessionID": "b", "state": "busy", "updatedAt": int(time.time() * 1000),
               "message": "x" * 100_000})
        out = main.read_status()
        assert out and len(out[0]["message"]) == 100_000


class TestConfigChurn:
    def test_rapid_config_rewrites_do_not_clobber(self, pet_dir):
        """The pet and control processes both write config.json; interleaved
        writes must merge, never lose each other's keys."""
        main.save_config({"petIdx": 0, "walk": 100, "alwaysOnTop": True, "breakMin": 50})
        for i in range(50):
            main.save_config({"petIdx": i % len(main.PETS)})
            main.save_config({"walk": i % 100})
            c = main.load_config()
            assert c["breakMin"] == 50, "breakMin lost on iteration %d" % i
            assert "alwaysOnTop" in c

    def test_command_keys_survive_setting_saves(self, pet_dir):
        api = main.ControlApi()
        api._cmd("hidePet")
        api.save_config({"walk": 77})  # user tweaks a slider
        c = json.loads((pet_dir / "config.json").read_text(encoding="utf-8"))
        assert c.get("hidePet") == 1, "pending command clobbered by setting save"
        assert c.get("walk") == 77


class TestLogAndWellbeingLoad:
    def test_5000_line_log(self, pet_dir):
        log = pet_dir / "activity-capvolt.jsonl"
        lines = "".join(
            json.dumps({"t": time.time() + i, "kind": "state", "state": "busy"}) + "\n"
            for i in range(5000)
        )
        log.write_text(lines, encoding="utf-8")
        t0 = time.perf_counter()
        out = main.ControlApi().get_logs(limit=200)
        dt = (time.perf_counter() - t0) * 1000
        assert len(out) == 200
        assert dt < 3000, "get_logs too slow: %.1f ms" % dt

    def test_wellbeing_many_apps_capped(self, pet_dir):
        apps = {("app%d" % i): (i + 1) * 60 for i in range(40)}
        write(pet_dir, "wellbeing.json",
              {"date": time.strftime("%Y-%m-%d"), "apps": apps})
        out = main.ControlApi().get_wellbeing()
        assert len(out) == 8  # capped to top 8
        assert out[0]["app"] == "app39"
