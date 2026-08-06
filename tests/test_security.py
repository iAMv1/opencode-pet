"""RPC input validation + static-file hardening (P10).

The web bridge takes strings/JSON from JS; every mutating ControlApi method
must survive hostile input without raising (a raise becomes a 500 from the
--web server), and web._file must never resolve outside the served directory.
"""

import json
import os
import sys
import time

import pytest

from desktop import api, store, web


class TestSaveConfigSanitize:
    def test_valid_merge(self, pet_dir):
        ctl = api.ControlApi()
        assert ctl.save_config({"goalMin": 90, "alwaysOnTop": False,
                                "name": "Fido"}) is True
        c = store.load_config()
        assert c["goalMin"] == 90
        assert c["alwaysOnTop"] is False
        assert c["name"] == "Fido"

    def test_lists_dropped_nested_dicts_dropped(self, pet_dir):
        api.ControlApi().save_config({"badList": [1, 2],
                                      "nested": {"a": [1]},
                                      "ok": "fine"})
        c = store.load_config()
        assert "badList" not in c
        assert "nested" not in c
        assert c["ok"] == "fine"

    def test_numeric_keys_coerced(self, pet_dir):
        api.ControlApi().save_config({"goalMin": "60", "walk": 75,
                                      "pomoMin": "abc"})
        c = store.load_config()
        assert c["goalMin"] == 60      # string coerced via safe int
        assert c["walk"] == 75
        # unparseable value falls back to the safe default, never garbage
        assert c["pomoMin"] == 25

    def test_shallow_primitive_dict_kept(self, pet_dir):
        """Plugin ecosystem writes custom keys (eventMap etc.) — unknown keys
        survive as long as they are shallow primitive maps."""
        api.ControlApi().save_config({"eventMap": {"poke": 1, "jump": "x"}})
        assert store.load_config()["eventMap"] == {"poke": 1, "jump": "x"}

    def test_null_numeric_dropped(self, pet_dir):
        api.ControlApi().save_config({"goalMin": None})
        assert store.load_config()["goalMin"] == store.GOAL_DEFAULT_MIN

    def test_non_dict_conf_no_raise(self, pet_dir):
        ctl = api.ControlApi()
        assert ctl.save_config("nonsense") is True
        assert ctl.save_config([1, 2]) is True
        assert ctl.save_config(None) is True

    def test_non_string_keys_dropped(self, pet_dir):
        api.ControlApi().save_config({1: "x"})
        assert 1 not in store.load_config()


class TestSetFocusTag:
    def _active_session(self, pet_dir):
        with open(os.path.join(str(pet_dir), "focus.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"active": True, "startedAt": time.time(),
                       "targetMin": 25, "wilted": False}, fh)

    def test_strip_and_clamp(self, pet_dir):
        self._active_session(pet_dir)
        ctl = api.ControlApi()
        tag = "  " + "x" * 80 + "  "
        assert ctl.set_focus_tag(tag) is True
        assert ctl.tag == "x" * 32
        with open(os.path.join(str(pet_dir), "focus.json"),
                  encoding="utf-8") as fh:
            assert json.load(fh)["tag"] == "x" * 32

    def test_short_tag_kept(self, pet_dir):
        self._active_session(pet_dir)
        ctl = api.ControlApi()
        assert ctl.set_focus_tag("  Work  ") is True
        assert ctl.tag == "Work"

    def test_non_string_rejected(self, pet_dir):
        self._active_session(pet_dir)
        ctl = api.ControlApi()
        assert ctl.set_focus_tag(123) is False
        assert ctl.set_focus_tag(None) is False
        assert ctl.set_focus_tag({"x": 1}) is False
        assert ctl.set_focus_tag(["a"]) is False

    def test_no_active_session_false(self, pet_dir):
        assert api.ControlApi().set_focus_tag("Work") is False


class TestPetIndex:
    def test_garbage_pet_idx_survives_next_prev(self, pet_dir):
        store.save_config({"petIdx": "garbage"})
        ctl = api.ControlApi()
        assert ctl.next_pet() is True   # must not raise / 500
        assert ctl.prev_pet() is True
        c = store.load_config()
        assert 0 <= c["petIdx"] < len(api.sprites.PETS)

    def test_garbage_pet_idx_read_paths(self, pet_dir):
        """String petIdx must not 500 any pet-derived read (was a RPC 500 —
        dashboard died on first call)."""
        store.save_config({"petIdx": "garbage"})
        ctl = api.ControlApi()
        assert isinstance(ctl.get_config(), dict)
        assert isinstance(ctl.get_pet_profile(), dict)
        assert isinstance(ctl.get_logs(), list)
        assert isinstance(ctl.get_memory_lane(), list)
        assert isinstance(ctl.get_day_health(), dict)
        assert isinstance(ctl.get_weekly_wrapped(), dict)
        assert isinstance(ctl.get_wellbeing_insights(), dict)


class TestArgClamps:
    def test_garbage_days_limits_fall_back(self, pet_dir):
        ctl = api.ControlApi()
        assert ctl.get_logs("garbage") == []          # no raise
        assert isinstance(ctl.get_alerts("garbage"), dict)
        assert ctl.get_wellbeing_history("garbage")   # no raise
        assert ctl.get_week_apps("garbage") == []
        assert ctl.start_focus("garbage") is True

    def test_limit_clamped(self, pet_dir):
        ctl = api.ControlApi()
        ctl.get_logs(10 ** 9)  # no memory blowup; clamped to 2000


class TestWebFile:
    @pytest.fixture()
    def meipass(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
        return tmp_path

    def test_traversal_rejected(self, meipass):
        for name in ("../evil.html", "%2e%2e/evil.html", "%2E%2E%5Cevil.html",
                     "..\\evil.html", "desktop/../../evil.html"):
            assert web._file(name) is None, name

    def test_absolute_paths_rejected(self, meipass):
        assert web._file(os.path.abspath(__file__)) is None
        assert web._file("C:\\Windows\\win.ini") is None
        assert web._file("/etc/passwd") is None

    def test_extension_whitelist(self, meipass):
        assert web._file("evil.exe") is None
        assert web._file("evil.html.exe") is None   # suffix is .exe
        assert web._file("noext") is None
        for ext in (".html", ".css", ".js", ".png", ".webp", ".json"):
            (meipass / ("ok" + ext)).write_text("x")
            assert web._file("ok" + ext) == str(meipass / ("ok" + ext))

    def test_valid_asset_resolves(self, meipass):
        (meipass / "desktop").mkdir()
        (meipass / "desktop" / "app.html").write_text("x")
        assert web._file("app.html") == str(meipass / "desktop" / "app.html")

    def test_missing_file_none(self, meipass):
        assert web._file("nope.html") is None
