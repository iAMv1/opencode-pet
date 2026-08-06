"""P7: Attention Barter — the pet's metamorphosis stages are TRADED for real
banked focus minutes (no currency abstraction): bank accrual (active minutes
only, idle never), offer staging, one-shot pay (deducts bank + stage up + XP +
ceremony, consumes barterPay once), quiet 3-day expiry with the bank kept, and
daily re-offer. Plus the get_barter_state / get_rituals API shapes and the
web-bridge parity entries.
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
    eng.bubble_until = 0
    eng.sessions = []
    return eng


def _track(eng, active, secs):
    """Feed `secs` of tracked time through _track_app_time (active or idle)."""
    eng.os_active = active
    eng.os_app = "VS Code" if active else ""
    eng._wb_t = time.time() - secs
    eng._wb_date = time.strftime("%Y-%m-%d")
    eng._wb = {}
    eng._hour_today = {}
    eng._memory_work = 0.0
    eng._last_wb_save = time.time()
    eng._track_app_time()


# ---------------------------------------------------------------- bank accrual

class TestBank:
    def test_bank_accrues_active_minutes_only(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        _track(eng, True, 30)
        assert eng._barter_acc == 30.0
        _track(eng, False, 30)  # idle: never banks
        assert eng._barter_acc == 30.0

    def test_bank_flushes_whole_minutes_to_config(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        _track(eng, True, 30)
        _track(eng, True, 30)
        _track(eng, True, 30)   # 90s accumulated
        eng._barter_tick(time.time())
        assert eng._barter_bank == 1   # 1 whole minute, remainder kept
        assert main.load_config()["barterBank"] == 1
        assert eng._barter_acc == 30.0
        _track(eng, True, 30)
        _track(eng, True, 30)   # crosses the next minute
        eng._barter_tick(time.time())
        assert eng._barter_bank == 2

    def test_bank_defaults_zero(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        assert eng._barter_bank == 0 and eng._barter_stage == 0


# ---------------------------------------------------------------- offer staging

class TestOffers:
    def test_stage_progression(self, pet_dir):
        seq = [store_mod.barter_next_offer(s) for s in range(4)]
        assert [o["stage"] for o in seq] == [1, 2, 3, 4]
        assert [o["costMinutes"] for o in seq] == [300, 600, 900, 1500]
        assert seq[0]["name"] == "Perk up ears"
        assert seq[3]["name"] == "Full form"
        assert store_mod.barter_next_offer(4) is None   # all stages done
        assert store_mod.barter_next_offer(-1)["costMinutes"] == 300
        assert store_mod.barter_next_offer("bogus")["costMinutes"] == 300

    def test_stage_count_matches_offers(self, pet_dir):
        assert len(store_mod.BARTER_OFFERS) == 4


# ---------------------------------------------------------------- pay

class TestPay:
    def test_pay_consumes_command_once_and_celebrates(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        eng._barter_bank = 700
        eng._barter_stage = 0
        write(pet_dir, "config.json", {"barterPay": True})
        eng.config_watch()
        assert eng._barter_bank == 400          # 700 - 300 deducted
        assert eng._barter_stage == 1           # stage 1 done -> next is stage 2
        assert eng.xp == engine_mod.XP_BARTER
        assert eng.mood == "happy"
        assert "Shift complete" in eng.bubble_text
        assert eng.cast is not None             # ceremony cast flash
        assert main.load_config().get("barterPay") is None  # one-shot consumed
        ev = [r for r in read_log(pet_dir, eng) if r["kind"] == "barter"]
        assert len(ev) == 1 and ev[0]["stage"] == 1 and ev[0]["cost"] == 300
        # re-drive: nothing left to pay, no double
        write(pet_dir, "config.json", {"barterPay": True})
        eng.config_watch()
        assert eng._barter_bank == 400
        assert eng.xp == engine_mod.XP_BARTER
        assert len([r for r in read_log(pet_dir, eng)
                    if r["kind"] == "barter"]) == 1

    def test_pay_rejected_when_bank_short(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        eng._barter_bank = 100
        write(pet_dir, "config.json", {"barterPay": True})
        eng.config_watch()
        assert eng._barter_bank == 100
        assert eng.xp == 0
        assert main.load_config().get("barterPay") is None  # command still cleared

    def test_pay_last_stage_leaves_no_next_offer(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        eng._barter_bank = 99999
        eng._barter_stage = 3   # "Full form" (1500 min) is next and last
        write(pet_dir, "config.json", {"barterPay": True})
        eng.config_watch()
        assert eng._barter_stage == 4
        assert store_mod.barter_next_offer(eng._barter_stage) is None
        assert main.load_config()["barterStage"] == 4


# ---------------------------------------------------------------- expiry + re-offer

class TestOfferLifecycle:
    def test_ask_bubble_fires_once_per_day(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        eng._barter_bank = 300
        eng._barter_offer_date = ""
        eng._barter_tick(time.time())
        assert eng.bubble_text == ("I can shift form \u2014 trade 300 focus-minutes?")
        assert main.load_config()["barterOfferDate"] == time.strftime("%Y-%m-%d")
        assert [r for r in read_log(pet_dir, eng) if r["kind"] == "barterAsk"]
        eng._barter_tick(time.time())   # same day: no re-ask, no bubble churn
        assert eng.bubble_text == ("I can shift form \u2014 trade 300 focus-minutes?")
        assert len([r for r in read_log(pet_dir, eng)
                    if r["kind"] == "barterAsk"]) == 1

    def test_expiry_after_three_days_is_quiet_bank_kept(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        eng._barter_bank = 600
        eng._barter_offer_date = day_ago(4)   # offered 4 days ago, never paid
        eng._barter_tick(time.time())
        assert eng._barter_bank == 600                 # bank intact
        assert eng.xp == 0                             # no XP, no punishment
        assert eng._barter_offer_date == time.strftime("%Y-%m-%d")
        assert "shift form" not in eng.bubble_text     # expiry itself is quiet
        assert [r for r in read_log(pet_dir, eng) if r["kind"] == "barterAsk"] == []

    def test_reoffer_next_day_after_expiry(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        eng._barter_bank = 600
        eng._barter_offer_date = day_ago(1)   # a fresh offer window opens
        eng._barter_tick(time.time())
        assert "shift form" in eng.bubble_text
        assert eng._barter_offer_date == time.strftime("%Y-%m-%d")
        assert [r for r in read_log(pet_dir, eng) if r["kind"] == "barterAsk"]

    def test_pending_offer_not_expired_at_two_days(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        eng._barter_bank = 600
        eng._barter_offer_date = day_ago(2)
        eng._barter_tick(time.time())
        assert eng._barter_bank == 600
        assert "shift form" in eng.bubble_text   # still within the window

    def test_no_ask_when_bank_short(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        eng._barter_bank = 100
        eng._barter_offer_date = ""
        eng._barter_tick(time.time())
        assert "shift form" not in eng.bubble_text
        assert main.load_config().get("barterOfferDate") in ("", None)

    def test_stage_aura_tiers_and_periodic_shimmer(self, pet_dir, no_window):
        eng = _eng(pet_dir, no_window)
        assert eng._barter_glow() is None            # stage 0: no radiance
        eng._barter_stage = 2
        glow = eng._barter_glow()
        assert glow is not None
        assert eng._barter_glow() is glow            # cached per stage
        now = time.time()
        eng._last_barter_shimmer = now - engine_mod.BARTER_SHIMMER_SECS - 1
        eng._barter_tick(now)
        assert eng.cast is not None                  # periodic shimmer fired


# ---------------------------------------------------------------- API

class TestBarterApi:
    def test_get_barter_state_shape(self, pet_dir):
        write(pet_dir, "config.json",
              {"barterBank": 450, "barterStage": 0, "barterOfferDate": ""})
        s = main.ControlApi().get_barter_state()
        assert s["bank"] == 450 and s["stage"] == 0
        assert s["nextOffer"]["stage"] == 1
        assert s["nextOffer"]["costMinutes"] == 300
        assert s["offered"] is False

    def test_offered_true_when_asked_today(self, pet_dir):
        write(pet_dir, "config.json",
              {"barterBank": 600, "barterStage": 0,
               "barterOfferDate": time.strftime("%Y-%m-%d")})
        s = main.ControlApi().get_barter_state()
        assert s["offered"] is True

    def test_offered_false_when_bank_short(self, pet_dir):
        write(pet_dir, "config.json",
              {"barterBank": 100, "barterStage": 0,
               "barterOfferDate": time.strftime("%Y-%m-%d")})
        s = main.ControlApi().get_barter_state()
        assert s["offered"] is False

    def test_no_next_offer_at_final_stage(self, pet_dir):
        write(pet_dir, "config.json", {"barterBank": 99999, "barterStage": 4})
        s = main.ControlApi().get_barter_state()
        assert s["nextOffer"] is None

    def test_get_rituals_shape_with_progress(self, pet_dir):
        yday = day_ago(1)
        write(pet_dir, "wellbeing.json",
              {"date": time.strftime("%Y-%m-%d"),
               "apps": {"VS Code": 7200},
               "history": {yday: 2 * 3600},
               "hourHistory": {}, "appHistory": {}, "hourToday": {}})
        s = main.ControlApi().get_rituals()
        assert s["ritualDate"] == time.strftime("%Y-%m-%d")
        assert [r["kind"] for r in s["rituals"]] == ["beat_yesterday"]
        assert s["rituals"][0]["current"] == 120
        assert s["rituals"][0]["done"] is True

    def test_get_rituals_prefers_persisted_daily_list(self, pet_dir):
        write(pet_dir, "wellbeing.json",
              {"date": time.strftime("%Y-%m-%d"), "apps": {}, "history": {},
               "hourHistory": {}, "appHistory": {}, "hourToday": {}})
        write(pet_dir, "config.json",
              {"ritualDate": time.strftime("%Y-%m-%d"),
               "ritualList": [{"id": "night_guard", "kind": "night_guard",
                               "name": "Night guard", "desc": "", "target": 60}]})
        s = main.ControlApi().get_rituals()
        assert [r["kind"] for r in s["rituals"]] == ["night_guard"]

    def test_parity_entries(self, pet_dir):
        for m in ("get_rituals", "get_barter_state", "barter_pay"):
            assert m in main._WEB_METHODS
            assert hasattr(main.ControlApi, m)
