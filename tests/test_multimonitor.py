"""Multi-monitor correctness: per-monitor workareas (EnumDisplayMonitors),
monitor-aware drag release, and WM_DISPLAYCHANGE area recovery.
"""

import pytest

main = pytest.importorskip("desktop.main")
import desktop.win32 as win32  # noqa: E402

PRIMARY = (0, 0, 1920, 1040)
LEFT_MON = (-1920, 0, 0, 1040)   # secondary placed left of primary


def make_engine(area=PRIMARY, x=100, y=500):
    """Bare PetEngine with just the physics attributes these paths touch."""
    eng = object.__new__(main.PetEngine)
    eng.pet = main.PETS[0]
    eng.area = area
    eng.phys = {"x": x, "y": y, "vx": 0, "vy": 0, "grounded": True,
                "mode": "idle", "t": 0, "walkT": 0, "spawned": True}
    eng.walk_factor = 1.0
    eng.dragging = False
    return eng


@pytest.fixture()
def two_monitors(monkeypatch):
    """EnumDisplayMonitors reports primary + left-placed negative-x monitor;
    _monitor_info maps each fake HMONITOR to its workarea tuple."""
    areas = {1: PRIMARY, 2: LEFT_MON}

    def fake_enum(_hdc, _clip, proc, _data):
        for hmon in areas:
            proc(None, None, hmon, 0)
        return True

    monkeypatch.setattr(win32.user32, "EnumDisplayMonitors", fake_enum)
    monkeypatch.setattr(win32, "_monitor_info", lambda hmon: areas.get(hmon))
    return areas


class TestMonitorWorkareaFor:
    def test_primary_fallback_when_enumeration_unavailable(self, monkeypatch):
        monkeypatch.setattr(win32.user32, "EnumDisplayMonitors", lambda *a: False)
        monkeypatch.setattr(win32, "workarea", lambda: PRIMARY)
        assert win32.monitor_workarea_for(-500, 100) == PRIMARY

    def test_secondary_monitor_with_negative_coords(self, two_monitors):
        assert win32.monitor_workarea_for(-1500, 500) == LEFT_MON

    def test_point_on_primary_still_returns_primary(self, two_monitors):
        assert win32.monitor_workarea_for(960, 500) == PRIMARY


class TestDragEndMonitorAware:
    def test_release_clamps_into_monitor_pet_is_on(self, monkeypatch):
        monkeypatch.setattr(win32, "monitor_workarea_for", lambda x, y: LEFT_MON)
        eng = make_engine(area=PRIMARY, x=-10, y=900)
        eng._last_pos = (-10, 900)
        eng.drag_end()
        # Primary bounds would force x >= 0; the left monitor keeps it there.
        fw = main.PETS[0]["frameW"] * main.PETS[0]["scale"]
        fh = main.PETS[0]["frameH"] * main.PETS[0]["scale"]
        assert eng.phys["x"] == max(LEFT_MON[0], min(-10, LEFT_MON[2] - fw))
        assert eng.phys["y"] == max(LEFT_MON[1], min(900, LEFT_MON[3] - fh))
        assert eng.phys["x"] < 0

    def test_explicit_area_keeps_legacy_behavior(self):
        eng = make_engine(area=PRIMARY, x=900, y=700)
        eng._last_pos = None
        eng.drag_end((0, 0, 800, 600), 100, 50)
        assert (eng.phys["x"], eng.phys["y"]) == (700, 550)


class TestDisplayChange:
    def test_handler_refreshes_area_from_monitor_under_pet(self, monkeypatch):
        monkeypatch.setattr(win32, "monitor_workarea_for", lambda x, y: LEFT_MON)
        pw = object.__new__(win32.PetWindow)
        pw.engine = make_engine(x=-1500)
        pw.engine.refresh_area = lambda area: setattr(pw.engine, "area", area)
        assert pw._on_display_change() == 0
        assert pw.engine.area == LEFT_MON

    def test_handler_falls_back_to_workarea_when_lookup_raises(self, monkeypatch):
        def boom(x, y):
            raise OSError("enum dead")
        monkeypatch.setattr(win32, "monitor_workarea_for", boom)
        monkeypatch.setattr(win32, "workarea", lambda: PRIMARY)
        pw = object.__new__(win32.PetWindow)
        pw.engine = make_engine()
        pw.engine.refresh_area = lambda area: setattr(pw.engine, "area", area)
        pw._on_display_change()
        assert pw.engine.area == PRIMARY

    def test_refresh_area_reclamps_after_shrink(self):
        eng = make_engine(area=(0, 0, 1920, 1040), x=1700)
        eng.refresh_area((0, 0, 800, 600))
        fw = main.PETS[0]["frameW"] * main.PETS[0]["scale"]
        fh = main.PETS[0]["frameH"] * main.PETS[0]["scale"]
        assert eng.area == (0, 0, 800, 600)
        assert eng.phys["x"] <= 800 - fw and eng.phys["y"] <= 600 - fh
        # pet remains walkable inside the shrunken workarea
        eng.walk_toward("right")
        for _ in range(30):
            eng._phys(17)
        assert 0 <= eng.phys["x"] <= 800 - fw
