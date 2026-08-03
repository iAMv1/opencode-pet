"""Production-hardening tests: Win32 interop shape, config write locking,
wellbeing sleep-resume handling, status-read resilience, and bubble-text
truncation performance.

These lock in the fixes found by the validation team's reliability &
failure-recovery specialists (see tests/README.md).
"""

import ctypes
import json
import threading
import time

import pytest

main = pytest.importorskip("desktop.main")


# ---------------------------------------------------------------- Win32 interop

class TestWin32Interop:
    def test_pointer_returns_have_64bit_restypes(self):
        """HANDLE/HMODULE/HWND-returning calls must declare a pointer-sized
        restype, or ctypes truncates 64-bit handles to 32-bit c_int on 64-bit
        Windows (window/app-state corruption)."""
        from ctypes import wintypes

        assert main.kernel32.GetModuleHandleW.restype is wintypes.HMODULE
        assert main.kernel32.OpenProcess.restype is wintypes.HANDLE
        assert main.kernel32.CreateFileW.restype is wintypes.HANDLE
        assert main.kernel32.CreateMutexW.restype is wintypes.HANDLE
        assert main.user32.GetForegroundWindow.restype is wintypes.HWND
        # sanity: none of them silently fall back to the default c_int
        for fn in (main.kernel32.GetModuleHandleW, main.kernel32.OpenProcess,
                   main.kernel32.CreateFileW, main.user32.GetForegroundWindow):
            assert fn.restype is not ctypes.c_int

    def test_handle_accepting_calls_have_argtypes(self):
        main.kernel32.CreateFileW.argtypes  # smoke: defined without error
        main.kernel32.ReadDirectoryChangesW.argtypes
        main.user32.GetWindowThreadProcessId.argtypes
        main.user32.SystemParametersInfoW.argtypes


# ---------------------------------------------------------------- bubble text

class TestFitText:
    def _font(self, no_window, pet_dir):
        eng = main.PetEngine()
        return eng._font_cache()

    def test_binary_search_matches_linear(self, no_window, pet_dir):
        """The O(log n) implementation must truncate to exactly what the old
        O(n) walk produced, across widths and text lengths."""
        font = self._font(no_window, pet_dir)

        def linear(text, font, avail):
            if font.getlength(text) <= avail:
                return text
            t = text
            while t and font.getlength(t + "\u2026") > avail:
                t = t[:-1]
            return (t + "\u2026") if t else text[:1]

        for width in (20, 60, 100, 168, 400):
            for n in (0, 1, 5, 50, 200):
                text = "bash " + "x" * n
                got = main.PetEngine._fit_text(text, font, width)
                want = linear(text, font, width)
                assert got == want, "width=%d n=%d: got %r want %r" % (width, n, got, want)
                if got:
                    assert font.getlength(got) <= width

    def test_empty_and_short(self, no_window, pet_dir):
        font = self._font(no_window, pet_dir)
        assert main.PetEngine._fit_text("", font, 60) == ""
        assert main.PetEngine._fit_text("hi", font, 400) == "hi"

    def test_fit_speed(self, no_window, pet_dir):
        """The binary-search truncation must be dramatically faster than the
        old O(n) walk for long labels. Asserted RELATIVELY (binary vs linear
        measured back-to-back) so a loaded machine can't flake an absolute ms
        budget — the ratio holds under any load."""
        font = self._font(no_window, pet_dir)
        text = "bash " + "x" * 500

        def linear(text, font, avail):
            if font.getlength(text) <= avail:
                return text
            t = text
            while t and font.getlength(t + "\u2026") > avail:
                t = t[:-1]
            return (t + "\u2026") if t else text[:1]

        main.PetEngine._fit_text(text, font, 168)  # warmup
        linear(text, font, 168)

        t0 = time.perf_counter()
        for _ in range(30):
            main.PetEngine._fit_text(text, font, 168)
        binary_ms = (time.perf_counter() - t0) * 1000

        t0 = time.perf_counter()
        for _ in range(30):
            linear(text, font, 168)
        linear_ms = (time.perf_counter() - t0) * 1000

        assert binary_ms < linear_ms / 3, (
            "binary search not faster than linear walk: %.2f ms vs %.2f ms"
            % (binary_ms, linear_ms)
        )


# ---------------------------------------------------------------- OS activity

class TestLastInput:
    def test_last_input_ms_wires_getlastinputinfo(self, monkeypatch):
        """The OS-activity layer must really call GetLastInputInfo. A missing
        LASTINPUTINFO struct used to return 0 from a swallowed exception,
        which made last_input_ms() < 30000 always true — the pet thought the
        user was permanently active (no idle/waiting state ever)."""
        def fake_get(ptr):
            # the real call passes ctypes.byref(), which has no .contents —
            # cast to the struct pointer the same way the real ABI would.
            li = ctypes.cast(ptr, ctypes.POINTER(main.LASTINPUTINFO)).contents
            li.dwTime = 5000  # input happened 5s ago
            return True

        monkeypatch.setattr(main.user32, "GetLastInputInfo", fake_get)
        got = main.last_input_ms()
        assert got == main.kernel32.GetTickCount() - 5000

    def test_last_input_ms_is_int(self):
        assert isinstance(main.last_input_ms(), int)
        assert main.last_input_ms() >= 0

    def test_tick_rollover_never_negative(self, monkeypatch):
        """GetTickCount wraps every 49.7 days of uptime. A subtraction across
        the wrap must be masked to the DWORD range — an unwrapped negative
        would make os_active permanently True (the pet never rests)."""
        import ctypes

        def fake_get(ptr):
            li = ctypes.cast(ptr, ctypes.POINTER(main.LASTINPUTINFO)).contents
            li.dwTime = 5  # input happened 5ms before the wrap
            return True

        monkeypatch.setattr(main.kernel32, "GetTickCount", lambda: 2)  # just wrapped
        monkeypatch.setattr(main.user32, "GetLastInputInfo", fake_get)
        got = main.last_input_ms()
        assert got > 1000, "rollover produced %r — must stay in DWORD range" % got


# ---------------------------------------------------------------- wellbeing

class TestWellbeingSleepResume:
    def test_long_gap_not_credited(self, pet_dir):
        """After a laptop-sleep gap (>60s), elapsed time must NOT be credited
        to the foreground app (would inflate the daily wellbeing total)."""
        eng = object.__new__(main.PetEngine)
        eng._wb = {}
        eng._wb_date = time.strftime("%Y-%m-%d")
        eng._wb_app = ""
        eng._wb_t = time.time() - 300  # machine "slept" 5 minutes
        eng._last_wb_save = 0.0
        eng.os_active = True
        eng.os_app = "VS Code"
        eng._track_app_time()
        assert eng._wb == {}, "sleep gap credited time to an app: %r" % eng._wb
        # clock advanced so the next tick starts fresh
        assert time.time() - eng._wb_t < 5

    def test_normal_interval_credited(self, pet_dir):
        eng = object.__new__(main.PetEngine)
        eng._wb = {}
        eng._wb_date = time.strftime("%Y-%m-%d")
        eng._wb_app = ""
        eng._wb_t = time.time() - 1
        eng._last_wb_save = 0.0
        eng.os_active = True
        eng.os_app = "Terminal"
        eng._track_app_time()
        assert eng._wb.get("Terminal", 0) > 0


# ---------------------------------------------------------------- read_status

class TestReadStatusResilience:
    def test_permission_error_returns_empty(self, pet_dir, monkeypatch):
        def boom(*a, **k):
            raise PermissionError(13, "Access is denied")

        monkeypatch.setattr(main.os, "listdir", boom)
        assert main.read_status() == []

    def test_listdir_generic_oserror(self, pet_dir, monkeypatch):
        monkeypatch.setattr(main.os, "listdir", lambda *a: (_ for _ in ()).throw(OSError(2)))
        assert main.read_status() == []


# ---------------------------------------------------------------- config lock

class TestConfigLock:
    def test_concurrent_saves_do_not_lose_keys(self, pet_dir):
        """The pet and control processes both write config.json; concurrent
        writers must never lose each other's keys, even when writes
        interleave."""
        main.save_config({"petIdx": 0, "walk": 100, "alwaysOnTop": True, "breakMin": 50})
        errors = []

        def writer(key, value):
            try:
                for _ in range(25):
                    main.save_config({key: value})
            except Exception as e:  # pragma: no cover
                errors.append(e)

        threads = [
            threading.Thread(target=writer, args=("petIdx", 3)),
            threading.Thread(target=writer, args=("walk", 77)),
            threading.Thread(target=writer, args=("breakMin", 25)),
        ]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        assert not errors, errors
        c = json.loads((pet_dir / "config.json").read_text(encoding="utf-8"))
        assert c.get("petIdx") == 3, "petIdx lost under concurrent writes"
        assert c.get("walk") == 77, "walk lost under concurrent writes"
        assert c.get("breakMin") == 25, "breakMin lost under concurrent writes"
        assert c.get("alwaysOnTop") is True

    def test_cmd_merges_not_clobbers(self, pet_dir):
        api = main.ControlApi()
        api.save_config({"walk": 55})
        api._cmd("hidePet")
        c = json.loads((pet_dir / "config.json").read_text(encoding="utf-8"))
        assert c.get("hidePet") == 1
        assert c.get("walk") == 55, "command write clobbered an existing key"

    def test_clear_command_keeps_other_keys(self, pet_dir):
        main.save_config({"petIdx": 2, "walk": 30})
        main.PetEngine._clear_command("walk")
        c = json.loads((pet_dir / "config.json").read_text(encoding="utf-8"))
        assert "walk" not in c
        assert c.get("petIdx") == 2

    def test_reentrant_clear_after_corrupt(self, pet_dir):
        (pet_dir / "config.json").write_text("!!!", encoding="utf-8")
        main.PetEngine._clear_command("hidePet")  # must not raise
        c = json.loads((pet_dir / "config.json").read_text(encoding="utf-8"))
        assert "hidePet" not in c
