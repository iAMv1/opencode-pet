"""P5: Chronotype Metamorphosis — the pet's genes drift from the user's REAL
hour fingerprint, not from a generic level curve.

Covers: chronotype_profile math (per-hour averages, empty days skipped,
active-hours floor, peak ties), classification boundaries (night_owl / lark /
midday / erratic / balanced on crafted hour shapes), gene_manifest
determinism per class, metamorphosis (<3 days stays larval, >=3 days
transforms exactly once with the chronoDate guard + XP + log), weekly drift
(class change -> drift event, no double, review without change is quiet),
chrono_aura per gene/hour (night glow in 0-6h only), and the get_chronotype
API shape.
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


def _eng(pet_dir, no_window):
    eng = main.PetEngine()
    eng.xp = 0
    eng.level = 1
    eng.mood = "neutral"
    eng._last_tool_earn = ""
    eng.bubble_until = 0
    eng.sessions = []
    return eng


def _tick(eng):
    """One chrono evaluation (the per-day date gate would swallow a second
    call on the same day, so tests reset it)."""
    eng._chrono_checked = ""
    eng._chrono_tick(time.time())


# ---------------------------------------------------------------- profile math

class TestProfile:
    def test_average_over_available_days(self, pet_dir):
        hh = {day_ago(1): {"1": 3600, "2": 3600},
              day_ago(2): {"1": 1800}}
        p = store_mod.chronotype_profile(hh)
        assert p["days"] == 2
        assert p["hours"][1] == 2700   # (3600 + 1800) / 2
        assert p["hours"][2] == 1800   # 3600 / 2
        assert p["peak_hour"] == 1

    def test_empty_days_skipped_not_zero_counted(self, pet_dir):
        hh = {day_ago(1): {"3": 3600}, day_ago(2): {}, day_ago(3): {}}
        p = store_mod.chronotype_profile(hh)
        assert p["days"] == 1
        assert p["hours"][3] == 3600  # not 1200 — empty days don't dilute

    def test_no_data(self, pet_dir):
        p = store_mod.chronotype_profile({})
        assert p == {"hours": {}, "active_hours": [], "peak_hour": -1,
                     "peakLabel": "", "days": 0}

    def test_active_hours_floor_and_peak_label(self, pet_dir):
        hh = {day_ago(1): {"1": 3600, "2": 599, "3": 600},
              day_ago(2): {"1": 3600, "2": 599, "3": 600}}
        p = store_mod.chronotype_profile(hh)
        assert p["active_hours"] == [1, 3]   # >= 600s avg; 2 is just under
        assert p["peakLabel"] == "1 AM"

    def test_peak_tie_goes_to_earliest_hour(self, pet_dir):
        hh = {day_ago(1): {"13": 3600, "3": 3600}}
        p = store_mod.chronotype_profile(hh)
        assert p["peak_hour"] == 3


# ---------------------------------------------------------------- classification

class TestClassify:
    def test_night_owl(self, pet_dir):
        hours = {0: 600, 1: 3600, 2: 3600, 3: 3600, 4: 3600, 5: 3600, 6: 1200}
        assert store_mod.chronotype_class({"hours": hours}) == "night_owl"

    def test_lark(self, pet_dir):
        hours = {h: 3600 for h in range(6, 12)}
        assert store_mod.chronotype_class({"hours": hours}) == "lark"

    def test_midday(self, pet_dir):
        hours = {h: 3600 for h in range(10, 16)}
        assert store_mod.chronotype_class({"hours": hours}) == "midday"

    def test_midday_beats_lark_on_overlap(self, pet_dir):
        # 10am-4pm work: midday (10-16) is 6/6, lark (5-12) is 3/6
        hours = {h: 3600 for h in range(10, 16)}
        assert store_mod.chronotype_class({"hours": hours}) == "midday"

    def test_erratic_all_day_coverage(self, pet_dir):
        hours = {h: 900 for h in range(24)}
        assert store_mod.chronotype_class({"hours": hours}) == "erratic"

    def test_erratic_split_schedule(self, pet_dir):
        # real mass at 1-3am AND 2-4pm: no single rhythm
        hours = {1: 3600, 2: 3600, 14: 3600, 15: 3600}
        assert store_mod.chronotype_class({"hours": hours}) == "erratic"

    def test_night_owl_not_split_by_adjacent_hours(self, pet_dir):
        hours = {1: 3600, 2: 3600, 3: 3600, 4: 3600, 5: 3600}
        assert store_mod.chronotype_class({"hours": hours}) == "night_owl"

    def test_balanced_default(self, pet_dir):
        # every 4th hour: no band holds 35% of the total
        hours = {h: 900 for h in range(0, 24, 4)}
        assert store_mod.chronotype_class({"hours": hours}) == "balanced"

    def test_balanced_falls_through_when_no_band_qualifies(self, pet_dir):
        assert store_mod.chronotype_class({"hours": {}}) == "balanced"

    def test_class_on_real_shaped_night_owl(self, pet_dir):
        # the real user's fingerprint: hours 1-5 saturated, a little at 0/6
        hours = {0: 1200, 1: 3600, 2: 3600, 3: 3600, 4: 3600, 5: 3600, 6: 2400}
        assert store_mod.chronotype_class({"hours": hours}) == "night_owl"


# ---------------------------------------------------------------- gene manifest

class TestGenes:
    def test_manifest_deterministic_per_class(self, pet_dir):
        a = store_mod.gene_manifest("night_owl")
        b = store_mod.gene_manifest("night_owl")
        assert a == b == {"species": "nocturnal", "color": "indigo",
                          "pattern": "starlight", "activity": "after-midnight"}

    def test_manifest_keys(self, pet_dir):
        for cls in ("larval", "night_owl", "lark", "midday", "erratic", "balanced"):
            g = store_mod.gene_manifest(cls)
            assert set(g) == {"species", "color", "pattern", "activity"}

    def test_manifest_species_are_own_names(self, pet_dir):
        species = {store_mod.gene_manifest(cls)["species"]
                   for cls in ("night_owl", "lark", "midday", "erratic", "balanced")}
        assert species == {"nocturnal", "sunrise", "daylight", "hybrid", "steady"}
        existing = {p["id"] for p in main.PETS}
        assert not (species & existing)

    def test_larval_manifest(self, pet_dir):
        assert store_mod.gene_manifest("larval")["species"] == "larval"
        assert store_mod.gene_manifest("bogus")["species"] == "larval"  # safe fallback

    def test_readout_uses_peak_label(self, pet_dir):
        line = store_mod.chrono_readout("night_owl", {"peakLabel": "3 AM"})
        assert "3 AM" in line and "Nocturnal" in line
        assert store_mod.chrono_readout("larval") == (
            "My genes are still forming \u2014 I need more days to read you.")


# ---------------------------------------------------------------- metamorphosis

class TestMetamorphosis:
    def _wellbeing(self, hours_per_day, n=3):
        return {"date": time.strftime("%Y-%m-%d"), "apps": {},
                "history": {}, "hourHistory":
                {day_ago(i): {str(h): s for h, s in hours_per_day.items()}
                 for i in range(1, n + 1)},
                "appHistory": {}}

    def test_stays_larval_below_three_days(self, pet_dir, no_window):
        write(pet_dir, "wellbeing.json",
              self._wellbeing({1: 3600, 2: 3600}, n=2))
        eng = _eng(pet_dir, no_window)
        _tick(eng)
        assert eng.chrono_type == "larval"
        assert eng.xp == 0
        assert [r for r in read_log(pet_dir, eng) if r["kind"] == "metamorph"] == []
        assert main.load_config().get("chronoType") == "larval"

    def test_metamorphoses_at_three_days(self, pet_dir, no_window):
        write(pet_dir, "wellbeing.json",
              self._wellbeing({1: 3600, 2: 3600, 3: 3600, 4: 3600}, n=3))
        eng = _eng(pet_dir, no_window)
        _tick(eng)
        assert eng.chrono_type == "night_owl"
        assert eng.xp == engine_mod.XP_METAMORPH
        assert eng.mood == "happy"
        assert eng.cast is not None  # transformation ceremony flash
        assert "1 AM" in eng.bubble_text  # gene readout with the real peak
        m = [r for r in read_log(pet_dir, eng) if r["kind"] == "metamorph"]
        assert len(m) == 1 and m[0]["to"] == "night_owl"
        assert m[0]["genes"]["species"] == "nocturnal"
        c = main.load_config()
        assert c["chronoType"] == "night_owl"
        assert c["chronoDate"] == time.strftime("%Y-%m-%d")
        assert c["chronoWeekDate"] == time.strftime("%Y-%m-%d")  # review in 7 days

    def test_metamorphoses_once_chrono_date_guards(self, pet_dir, no_window):
        write(pet_dir, "wellbeing.json",
              self._wellbeing({1: 3600, 2: 3600}, n=4))
        eng = _eng(pet_dir, no_window)
        _tick(eng)
        xp_after = eng.xp
        _tick(eng)  # same day: the date gate must swallow the re-check
        assert eng.xp == xp_after
        assert len([r for r in read_log(pet_dir, eng) if r["kind"] == "metamorph"]) == 1

    def test_lark_metamorphosis_readout(self, pet_dir, no_window):
        write(pet_dir, "wellbeing.json",
              self._wellbeing({h: 3600 for h in range(7, 12)}, n=3))
        eng = _eng(pet_dir, no_window)
        _tick(eng)
        assert eng.chrono_type == "lark"
        assert "Sunrise" in eng.bubble_text


# ---------------------------------------------------------------- weekly drift

class TestDrift:
    def _wellbeing(self, hours_per_day, n=8):
        return {"date": time.strftime("%Y-%m-%d"), "apps": {},
                "history": {}, "hourHistory":
                {day_ago(i): {str(h): s for h, s in hours_per_day.items()}
                 for i in range(1, n + 1)},
                "appHistory": {}}

    def test_drift_fires_on_class_change(self, pet_dir, no_window):
        write(pet_dir, "wellbeing.json",
              self._wellbeing({h: 3600 for h in range(7, 12)}))  # now a lark
        write(pet_dir, "config.json",
              {"chronoType": "night_owl",
               "chronoDate": day_ago(30),
               "chronoWeekDate": day_ago(8)})  # review overdue
        eng = _eng(pet_dir, no_window)
        _tick(eng)
        assert eng.chrono_type == "lark"
        assert "drifting" in eng.bubble_text
        d = [r for r in read_log(pet_dir, eng) if r["kind"] == "drift"]
        assert len(d) == 1 and d[0]["to"] == "lark" and d[0]["fromType"] == "night_owl"
        assert main.load_config()["chronoWeekDate"] == time.strftime("%Y-%m-%d")

    def test_no_drift_without_class_change(self, pet_dir, no_window):
        write(pet_dir, "wellbeing.json",
              self._wellbeing({1: 3600, 2: 3600, 3: 3600}))  # still night owl
        write(pet_dir, "config.json",
              {"chronoType": "night_owl", "chronoDate": day_ago(30),
               "chronoWeekDate": day_ago(8)})
        eng = _eng(pet_dir, no_window)
        _tick(eng)
        assert eng.chrono_type == "night_owl"
        assert [r for r in read_log(pet_dir, eng) if r["kind"] == "drift"] == []
        assert main.load_config()["chronoWeekDate"] == time.strftime("%Y-%m-%d")

    def test_no_double_drift_within_a_week(self, pet_dir, no_window):
        write(pet_dir, "wellbeing.json",
              self._wellbeing({h: 3600 for h in range(7, 12)}))
        write(pet_dir, "config.json",
              {"chronoType": "night_owl", "chronoDate": day_ago(30),
               "chronoWeekDate": day_ago(8)})
        eng = _eng(pet_dir, no_window)
        _tick(eng)  # drifts to lark, review date = today
        drifts = lambda: [r for r in read_log(pet_dir, eng) if r["kind"] == "drift"]
        assert len(drifts()) == 1
        _tick(eng)  # same day: date gate swallows it
        _tick(eng)
        assert len(drifts()) == 1  # still one drift, no double

    def test_review_not_due_before_a_week(self, pet_dir, no_window):
        write(pet_dir, "wellbeing.json",
              self._wellbeing({h: 3600 for h in range(7, 12)}))
        write(pet_dir, "config.json",
              {"chronoType": "night_owl", "chronoDate": day_ago(30),
               "chronoWeekDate": day_ago(3)})  # only 3 days since review
        eng = _eng(pet_dir, no_window)
        _tick(eng)
        assert eng.chrono_type == "night_owl"  # lark data ignored until review
        assert [r for r in read_log(pet_dir, eng) if r["kind"] == "drift"] == []

    def test_next_review_helper(self, pet_dir):
        today = datetime.date.today()
        assert store_mod.chrono_next_review(today.isoformat()) == \
            (today + datetime.timedelta(days=store_mod.CHRONO_REVIEW_DAYS)).isoformat()
        assert store_mod.chrono_next_review("") == today.isoformat()


# ---------------------------------------------------------------- aura

class TestAura:
    def test_night_glow_only_in_0_6h(self, pet_dir):
        assert store_mod.chrono_aura("night_owl", hour=3) == (99, 102, 241, 60)
        assert store_mod.chrono_aura("night_owl", hour=0) == (99, 102, 241, 60)
        assert store_mod.chrono_aura("night_owl", hour=6) == (99, 102, 241, 60)
        assert store_mod.chrono_aura("night_owl", hour=7) is None
        assert store_mod.chrono_aura("night_owl", hour=23) is None

    def test_lark_amber_at_morning_only(self, pet_dir):
        assert store_mod.chrono_aura("lark", hour=8) == (255, 178, 90, 60)
        assert store_mod.chrono_aura("lark", hour=5) == (255, 178, 90, 60)
        assert store_mod.chrono_aura("lark", hour=12) == (255, 178, 90, 60)
        assert store_mod.chrono_aura("lark", hour=2) is None

    def test_midday_golden_in_window(self, pet_dir):
        assert store_mod.chrono_aura("midday", hour=13) == (255, 205, 92, 60)
        assert store_mod.chrono_aura("midday", hour=20) is None

    def test_erratic_hue_shifts_by_day(self, pet_dir):
        a1 = store_mod.chrono_aura("erratic", hour=3, day_of_year=1)
        a2 = store_mod.chrono_aura("erratic", hour=3, day_of_year=2)
        assert a1 is not None and a2 is not None
        assert a1 != a2 and len(a1) == 4 and len(a2) == 4

    def test_balanced_steady_sage_always(self, pet_dir):
        assert store_mod.chrono_aura("balanced", hour=2) == (141, 196, 157, 30)
        assert store_mod.chrono_aura("balanced", hour=14) == (141, 196, 157, 30)

    def test_larval_and_unknown_have_no_aura(self, pet_dir):
        assert store_mod.chrono_aura("larval", hour=3) is None
        assert store_mod.chrono_aura("bogus", hour=3) is None

    def test_engine_glow_tracks_gene(self, pet_dir, no_window, monkeypatch):
        write(pet_dir, "wellbeing.json",
              {"date": time.strftime("%Y-%m-%d"), "apps": {},
               "history": {}, "hourHistory": {}, "appHistory": {}})
        eng = _eng(pet_dir, no_window)
        assert eng._chrono_glow() is None  # larval: no aura
        eng.chrono_type = "night_owl"
        monkeypatch.setattr(main.time, "localtime",
                            lambda: type("T", (), {"tm_hour": 3})())
        assert eng._chrono_glow() is not None
        monkeypatch.setattr(main.time, "localtime",
                            lambda: type("T", (), {"tm_hour": 12})())
        assert eng._chrono_glow() is None  # outside 0-6: dormant
        img = eng._compose()  # aura path renders without crash
        assert img.size[0] > 0


# ---------------------------------------------------------------- API surface

class TestChronotypeApi:
    def test_get_chronotype_shape(self, pet_dir):
        write(pet_dir, "wellbeing.json",
              {"date": time.strftime("%Y-%m-%d"), "apps": {},
               "history": {}, "hourHistory":
               {day_ago(i): {"1": 3600, "2": 3600} for i in range(1, 4)},
               "appHistory": {}})
        write(pet_dir, "config.json",
              {"chronoType": "night_owl", "chronoDate": day_ago(3),
               "chronoWeekDate": day_ago(3)})
        s = main.ControlApi().get_chronotype()
        assert s["chronoType"] == "night_owl"
        assert s["dataDays"] == 3 and s["neededDays"] == 3
        assert s["genes"]["species"] == "nocturnal"
        assert s["peakHour"] == "1 AM"
        assert s["activeHours"] == [1, 2]
        assert len(s["fingerprintHours"]) == 24
        assert s["fingerprintHours"][1]["seconds"] == 3600
        assert s["nextReview"] >= time.strftime("%Y-%m-%d")
        assert "Nocturnal" in s["readout"]

    def test_get_chronotype_larval_default(self, pet_dir):
        s = main.ControlApi().get_chronotype()
        assert s["chronoType"] == "larval"
        assert s["dataDays"] == 0
        assert s["genes"]["species"] == "larval"
        assert s["readout"]

    def test_get_chronotype_in_web_methods(self, pet_dir):
        assert "get_chronotype" in main._WEB_METHODS
