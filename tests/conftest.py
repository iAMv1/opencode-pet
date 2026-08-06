"""Shared fixtures for the OpenCode Pet test suite.

The suite is intentionally zero-dependency (stdlib unittest/pytest + PIL, which
is already required by the app). desktop.main is imported lazily and the whole
suite skips gracefully on non-Windows hosts, since main.py uses ctypes.windll.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pytest  # noqa: E402


@pytest.fixture()
def pet_dir(tmp_path, monkeypatch):
    """Point all data-file constants at a throwaway temp directory.

    Since the split, the constants live in desktop.store and are read through
    that module's namespace at call time; desktop.main re-exports them as
    copies, so patching main alone would NOT redirect the data layer (tests
    would hit the real ~/.opencode/pet). Patch store, keep patching main too.
    """
    import desktop.main as main
    import desktop.store as store

    for mod in (store, main):
        monkeypatch.setattr(mod, "PET_DIR", str(tmp_path))
        monkeypatch.setattr(mod, "CONFIG_FILE", str(tmp_path / "config.json"))
        monkeypatch.setattr(mod, "WELLBEING_FILE", str(tmp_path / "wellbeing.json"))
        monkeypatch.setattr(mod, "FOCUS_FILE", str(tmp_path / "focus.json"))
        monkeypatch.setattr(mod, "ACTIVITY_LOG", str(tmp_path / "activity.jsonl"), raising=False)
    return tmp_path


@pytest.fixture()
def no_window(monkeypatch):
    """Replace PetWindow with a no-op stand-in so PetEngine() never touches GDI.

    The engine resolves PetWindow through the desktop.win32 module namespace,
    so the replacement must land there; main re-exports the same name for
    anything that still reads it from desktop.main.
    """
    import desktop.main as main
    import desktop.win32 as win32

    class FakeWin:
        def __init__(self):
            self.engine = None

        def __getattr__(self, name):
            return lambda *a, **k: None

    monkeypatch.setattr(win32, "PetWindow", FakeWin)
    monkeypatch.setattr(main, "PetWindow", FakeWin)
    return FakeWin


def make_sessions(*states, stale=False, updated_at=None, **extra):
    """Build a list of fake status dicts in the shape read_status() returns.

    Pass state strings positionally; keyword extras (title, toolLabel, message,
    direction, sessionID) are applied to the first dict.
    """
    import time

    now = int(time.time() * 1000)
    out = []
    for i, st in enumerate(states):
        d = {
            "sessionID": "sess-%d" % i,
            "state": st,
            "updatedAt": (updated_at if updated_at is not None else now - i * 1000),
            "stale": stale,
        }
        d.update(extra if i == 0 else {})
        out.append(d)
    return out
