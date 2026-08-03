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
    """Point all main.py data-file constants at a throwaway temp directory."""
    import desktop.main as main

    monkeypatch.setattr(main, "PET_DIR", str(tmp_path))
    monkeypatch.setattr(main, "CONFIG_FILE", str(tmp_path / "config.json"))
    monkeypatch.setattr(main, "WELLBEING_FILE", str(tmp_path / "wellbeing.json"))
    monkeypatch.setattr(main, "FOCUS_FILE", str(tmp_path / "focus.json"))
    monkeypatch.setattr(main, "ACTIVITY_LOG", str(tmp_path / "activity.jsonl"))
    return tmp_path


@pytest.fixture()
def no_window(monkeypatch):
    """Replace PetWindow with a no-op stand-in so PetEngine() never touches GDI."""
    import desktop.main as main

    class FakeWin:
        def __init__(self):
            self.engine = None

        def __getattr__(self, name):
            return lambda *a, **k: None

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
