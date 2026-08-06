"""ControlApi â€” the JS bridge contract for the pet dashboard/control UI.

Runs in the SEPARATE control process (or the --web server). Talks to the pet
via config.json + one-shot commands, so the pet process never hosts a browser.
"""

import datetime
import json
import os
import random
import sys
import time
from . import engine, sprites, store

SNAPSHOT_STALE_SECS = 6.0  # pet-state.json older than this = engine dead/absent

# Methods the --web RPC bridge accepts; must stay in sync with the desktop
# ControlApi (guarded by tests/test_spec_contract.py).
_WEB_METHODS = [
    "get_config", "get_previews", "get_sessions", "get_logs",
    "get_wellbeing", "get_wellbeing_history", "get_wellbeing_insights",
    "get_focus_state", "start_focus", "stop_focus", "set_focus_tag", "get_pet_profile",
    "get_goal_state", "get_pomo_state", "get_weekly_wrapped", "get_week_apps",
    "get_focus_peaks", "get_memory_state", "get_chronotype", "get_day_health",
    "get_rituals", "get_barter_state", "barter_pay",
    "get_memory_lane", "get_alerts",
    "get_orchard_state", "orchard_plant", "orchard_harvest", "orchard_delete",
    "get_pet_state", "save_config", "next_pet", "prev_pet", "hide_pet", "show_pet",
    "hide_control", "quit",
]
# Methods that make no sense from a browser tab: there is no control window
# to hide (the tab IS the UI), so hide_control is a no-op. quit is NOT a
# no-op: the dashboard's Quit button means "quit the pet app", and the real
# pet process reads the quit one-shot command from config.json â€” so we write
# the command (like ControlApi.quit does) but never os._exit(0) the SERVER.
_WEB_NOP = frozenset(["hide_control"])

# ---------------------------------------------------------------- input validation (P10)
# Config keys the app itself int()s when reading (goal_minutes & friends).
# save_config coerces these with a safe int; anything unparseable is dropped.
_INT_CONFIG_KEYS = frozenset({
    "goalMin", "breakMin", "stretchMin", "pomoMin", "pomoShort", "pomoLong",
    "pomoCount", "memoryMin", "memoryMax", "memoryCount", "walk",
    "barterBank", "barterStage", "petIdx", "xp", "level",
})


def _is_primitive(v):
    """JSON-primitive check: str/int/float/bool/None (bool before int â€” Python
    bools are ints)."""
    return v is None or isinstance(v, str) or isinstance(v, bool) \
        or isinstance(v, (int, float))


def _sanitize_config(conf):
    """Keep only JSON primitives from a JS-supplied config merge.

    The plugin ecosystem writes custom keys (eventMap etc.), so unknown keys
    are KEPT â€” but lists are dropped and dicts only survive when every value
    is a primitive (no nested lists/dicts). Known numeric keys are coerced
    with a safe int; unparseable values drop the key instead of corrupting a
    reader that int()s it.
    """
    if not isinstance(conf, dict):
        return {}
    out = {}
    for k, v in conf.items():
        if not isinstance(k, str):
            continue
        if _is_primitive(v):
            out[k] = v
        elif isinstance(v, dict) and all(_is_primitive(x) for x in v.values()):
            out[k] = dict(v)
    for k in _INT_CONFIG_KEYS & set(out):
        try:
            out[k] = int(out[k])
        except (TypeError, ValueError):
            del out[k]
    return out


def _safe_int(v, default):
    """int() that never raises â€” JS-supplied args fall back to the default
    instead of 500ing the RPC bridge."""
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _pet_idx(cfg):
    """Safe pet index from config: any garbage petIdx resolves to 0 instead
    of blowing up the next_pet/prev_pet int math."""
    try:
        return int(cfg.get("petIdx", 0) or 0) % len(sprites.PETS)
    except (TypeError, ValueError):
        return 0


def _current_app_session():
    """Resolve current_app_session through the desktop.main namespace: the
    test suite monkeypatches main.current_app_session, so the lookup must
    happen at call time (lazy import â€” api is imported BY main)."""
    from desktop import main as _app
    return _app.current_app_session()


class ControlApi:
    """Runs in the SEPARATE control process. Talks to the pet via config.json
    + one-shot commands, so the pet process never hosts a browser."""

    def __init__(self):
        self._control = None
        self.tag = ""

    def bind_window(self, win):
        self._control = win

    def get_config(self):
        c = store.load_config()
        c["pets"] = [p["name"] for p in sprites.PETS]
        c["petVisible"] = bool(c.get("petVisible", True))
        c["petName"] = sprites.PETS[_pet_idx(c)]["name"]
        sess = store.read_status()
        c["state"] = (sess[0].get("state") or "idle") if sess and not sess[0].get("stale") else ("busy" if _current_app_session() else "idle")
        return c

    def get_previews(self):
        return sprites.build_previews()

    def get_sessions(self):
        # ACTIVE sessions only â€” working/thinking/error/celebrating right now.
        # Idle/done sessions drop off the dashboard immediately; combined with
        # the server plugin no longer heartbeating idle sessions, stale files
        # are pruned from disk too.
        out = []
        for s in store.read_status():
            if s.get("stale"):
                continue
            if (s.get("state") or "idle") in ("busy", "thinking", "error", "retry", "celebrating"):
                out.append(s)
        if not out:
            activity = _current_app_session()
            if activity:
                out.append(activity)
        return out

    def get_logs(self, limit=200):
        """Recent activity history for the CURRENT pet (one pet, one memory)."""
        pet_id = sprites.PETS[_pet_idx(store.load_config())]["id"]
        log_path = store.activity_log_path(pet_id)
        limit = max(1, min(_safe_int(limit, 200), 2000))
        try:
            with open(log_path, "r", encoding="utf-8") as fh:
                lines = fh.readlines()
            out = []
            for line in lines[-int(limit):]:
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
            return out
        except Exception:
            return []

    def get_wellbeing(self):
        """Per-app time for today (digital wellbeing), top apps first."""
        try:
            d = store.read_wellbeing()
            if not d or d.get("date") != time.strftime("%Y-%m-%d"):
                return []
            out = [{"app": a, "seconds": int(s)}
                   for a, s in d.get("apps", {}).items() if s >= store.APP_MIN_SECS]
            out.sort(key=lambda x: -x["seconds"])
            return out[:store.TOP_APPS_LIMIT]
        except Exception:
            return []

    def get_wellbeing_history(self, days=7):
        """Per-day total focus for the last N days, ascending, ending today.

        Returns [{date: "YYYY-MM-DD", seconds: int}, ...] with zero-second
        days included so the dashboard can draw a contiguous week. The live
        running total for today is folded in from the apps map. The day window
        uses calendar arithmetic so DST transitions can't skip/duplicate a day.
        """
        d = store.read_wellbeing()
        # A missing file is treated as an empty window, NOT a short list: the
        # dashboard contract is a contiguous N-day series (zero-filled days
        # included) so the chart always draws the same shape. The UI shows its
        # empty state from the totals, not from list length.
        history = d.get("history") if (d and isinstance(d.get("history"), dict)) else {}
        history = store._fold_today(history, d)
        days = _safe_int(days, 7)  # 0 => 1 via the clamp below
        # 90-day window is used by the focus-calendar heatmap; 30 would
        # silently truncate it. The list itself stays bounded.
        days = max(1, min(days, store.HISTORY_MAX_DAYS))
        out = []
        for i in range(days - 1, -1, -1):
            day = (datetime.date.today() - datetime.timedelta(days=i)).isoformat()
            out.append({"date": day, "seconds": int(history.get(day, 0))})
        return out

    def get_wellbeing_insights(self):
        """Automated focus insights for the dashboard.

        Returns a dict:
          weekSeconds / prevWeekSeconds : totals for the last 7 days and the
              seven before that (today's running total folded into the week)
          deltaPct                      : rounded % change, None if no baseline
          bestDay                       : {date, seconds} or None (ties -> first)
          todaySeconds                  : seconds accrued today so far
          topApp                        : {app, seconds} or None (today, >= 30s)
          voice                         : pet-voice narrations of the week
              (P8, store.voice_insights) â€” 0-4 lines; the JS contract only
              adds a field, never removes one.
        """
        d = store.read_wellbeing()
        empty = {"weekSeconds": 0, "prevWeekSeconds": 0, "deltaPct": None,
                 "bestDay": None, "todaySeconds": 0, "topApp": None,
                 "voice": []}
        if d is None:
            return empty
        history = d.get("history") if isinstance(d.get("history"), dict) else {}
        history = store._fold_today(history, d)
        today = datetime.date.today()
        week, prev = store.week_window(history, today=today)
        week_secs = sum(week.values())
        prev_secs = sum(prev.values())
        delta = None
        if prev_secs > 0:
            delta = int(round((week_secs - prev_secs) / prev_secs * 100))
        best_day = None
        if week_secs > 0:
            best = max(week, key=week.get)
            best_day = {"date": best, "seconds": week[best]}
        running = 0
        top_app = None
        if d.get("date") == today.isoformat() and isinstance(d.get("apps"), dict):
            running = int(sum(v for v in d["apps"].values() if isinstance(v, (int, float))))
            if running >= store.APP_MIN_SECS:
                apps = [(a, int(s)) for a, s in d["apps"].items()
                        if isinstance(s, (int, float)) and s >= store.APP_MIN_SECS]
                if apps:
                    apps.sort(key=lambda x: -x[1])
                    top_app = {"app": apps[0][0], "seconds": apps[0][1]}
        # P8: pet-voice week narrations â€” fold today's live hour/app maps in
        # so the voice reflects the running day (same rule as the analyses).
        hour_hist = dict(d.get("hourHistory")) if isinstance(d.get("hourHistory"), dict) else {}
        app_hist = dict(d.get("appHistory")) if isinstance(d.get("appHistory"), dict) else {}
        if d.get("date") == today.isoformat():
            if isinstance(d.get("hourToday"), dict) and d["hourToday"]:
                day_hours = dict(hour_hist.get(today.isoformat(), {}))
                for h, s in d["hourToday"].items():
                    if isinstance(s, (int, float)):
                        try:
                            day_hours[int(h) % 24] = day_hours.get(int(h) % 24, 0) + int(s)
                        except (TypeError, ValueError):
                            pass
                hour_hist[today.isoformat()] = day_hours
            if isinstance(d.get("apps"), dict) and d["apps"]:
                day_apps = dict(app_hist.get(today.isoformat(), {}))
                for a, s in d["apps"].items():
                    if isinstance(s, (int, float)):
                        day_apps[a] = day_apps.get(a, 0) + int(s)
                app_hist[today.isoformat()] = day_apps
        starts = done = 0
        try:
            pet_id = sprites.PETS[_pet_idx(store.load_config())]["id"]
            with open(store.activity_log_path(pet_id),
                      encoding="utf-8") as fh:
                for line in fh:
                    try:
                        e = json.loads(line)
                    except Exception:
                        continue
                    if time.time() - (e.get("t") or 0) >= store.WEEK_SECS:
                        continue
                    if e.get("kind") == "focusStart":
                        starts += 1
                    elif e.get("kind") == "focusDone":
                        done += 1
        except Exception:
            pass
        voice = store.voice_insights(
            history, hour_hist, app_hist, focus={"starts": starts, "done": done})
        return {
            "weekSeconds": week_secs,
            "prevWeekSeconds": prev_secs,
            "deltaPct": delta,
            "bestDay": best_day,
            "todaySeconds": running,
            "topApp": top_app,
            "voice": voice,
        }

    def get_focus_peaks(self, days=7):
        """Best time-of-day for deep work over the last N days.

        Reuses the exact selection pattern from get_wellbeing_insights (window
        arithmetic, today's live total folded in, ties -> first found) but over
        24 hour-of-day buckets instead of 7 calendar days, so the two analyses
        stay consistent by construction.

        Returns:
          days            : the clamped window actually analysed
          totalSeconds    : sum over the window
          hours           : [{hour, seconds}, ...] for all 24, ascending
          best            : {hour, label, seconds, pct} of the busiest hour
                            (ties -> earliest hour), or None
          runnerUp        : second-busiest hour (or None) â€” shows the spread
          spanLabel       : "mornings" / "afternoons" / "evenings" / "nights"
                            for the best hour, for a friendlier UI line
        """
        days = _safe_int(days, 7)  # 0 => 1 via the clamp below
        days = max(1, min(days, store.PEAKS_MAX_DAYS))
        d = store.read_wellbeing()
        buckets = store.hour_buckets(d, days)
        total = sum(buckets)
        hours = [{"hour": h, "seconds": buckets[h]} for h in range(24)]
        best = runner = None
        if total > 0:
            # ties -> earliest hour (stable argmax over ascending order)
            ranked = sorted(((buckets[h], -h) for h in range(24)), reverse=True)
            best_hour = -ranked[0][1]
            best = {"hour": best_hour,
                    "label": store.hour_label(best_hour),
                    "seconds": buckets[best_hour],
                    "pct": int(round(buckets[best_hour] * 100.0 / total))}
            if ranked[1][0] > 0:
                runner_hour = -ranked[1][1]
                runner = {"hour": runner_hour,
                          "label": store.hour_label(runner_hour),
                          "seconds": buckets[runner_hour],
                          "pct": int(round(buckets[runner_hour] * 100.0 / total))}
        span = {0: "overnight", 1: "overnight", 2: "overnight", 3: "overnight", 4: "overnight",
                5: "mornings", 6: "mornings", 7: "mornings", 8: "mornings", 9: "mornings",
                10: "mornings", 11: "mornings", 12: "afternoons", 13: "afternoons",
                14: "afternoons", 15: "afternoons", 16: "afternoons", 17: "afternoons",
                18: "evenings", 19: "evenings", 20: "evenings", 21: "evenings",
                22: "nights", 23: "nights"}
        return {"days": days, "totalSeconds": total, "hours": hours,
                "best": best, "runnerUp": runner,
                "spanLabel": span.get(best["hour"], "") if best else ""}

    # ------------------------------------------------------ focus + growth API
    def get_focus_state(self):
        """Live focus-session state for the dashboard (sprout progress).

        Progress is recomputed from startedAt/targetMin rather than trusting
        the file snapshot (which is only written on start/wilt/stop/complete),
        so the dashboard ring actually grows during a session."""
        try:
            with open(store.FOCUS_FILE, encoding="utf-8") as fh:
                d = json.load(fh)
            if isinstance(d, dict) and d.get("active"):
                d["progress"] = store.focus_progress(
                    d.get("active"), d.get("startedAt", 0), d.get("targetMin", engine.FOCUS_DEFAULT_MIN))
                d["tag"] = d.get("tag") or self.tag or ""
            else:
                d = {"active": False, "startedAt": 0, "targetMin": engine.FOCUS_DEFAULT_MIN,
                     "wilted": False, "app": "", "progress": 0.0, "tag": ""}
            return d
        except Exception:
            return {"active": False, "startedAt": 0, "targetMin": engine.FOCUS_DEFAULT_MIN,
                    "wilted": False, "app": "", "progress": 0.0, "tag": ""}

    def set_focus_tag(self, tag=""):
        """Tag the CURRENT focus session (Work/Study/Write/...). Applies until
        the session ends; a new session starts untagged. Type-validated: only
        strings are accepted (P10), stripped and capped at 32 chars."""
        if not isinstance(tag, str):
            return False
        tag = tag.strip()[:32]
        self.tag = tag
        try:
            with open(store.FOCUS_FILE, encoding="utf-8") as fh:
                d = json.load(fh)
            if not (isinstance(d, dict) and d.get("active")):
                return False
            d["tag"] = tag
            with open(store.FOCUS_FILE, "w", encoding="utf-8") as fh:
                json.dump(d, fh)
            return True
        except Exception:
            return False

    def start_focus(self, minutes=None):
        """Write the one-shot command; the pet process owns the session."""
        minutes = _safe_int(minutes, engine.FOCUS_DEFAULT_MIN) if minutes is not None else None
        self._cmd("focusStart", minutes or engine.FOCUS_DEFAULT_MIN)
        return True

    def stop_focus(self):
        self._cmd("focusStop")
        return True

    def get_pet_profile(self):
        """Level / XP / mood / streak for the pet profile card."""
        c = store.load_config()
        xp = int(c.get("xp", 0))
        level = int(c.get("level", 1))
        needed = engine.PetEngine._xp_needed(level)
        streak = 0
        d = store.read_wellbeing()
        if d:
            hist = d.get("history") if isinstance(d.get("history"), dict) else {}
            # fold today's live running total so a fresh 30+ min of focus
            # extends the streak immediately (matches get_wellbeing_history)
            hist = store._fold_today(hist, d)
            streak = store.streak_from_history(hist)
        stage = store.evolution_stage(level)
        return {"level": level, "xp": xp, "xpNext": needed, "xpPct": min(1.0, xp / needed),
                "mood": c.get("mood", "neutral"), "streak": streak,
                "stage": {"id": stage["id"], "name": stage["name"],
                           "emoji": stage["emoji"]}}

    def get_goal_state(self):
        """Daily focus goal state for the dashboard ring.

        Returns {goalMin, todaySeconds, met, streak} â€” todaySeconds folds the
        live running total (same rule as get_wellbeing_history) and streak is
        consecutive days (ending today or yesterday) that hit goalMin*60.
        """
        goal_min = store.goal_minutes(store.load_config())
        d = store.read_wellbeing()
        history = d.get("history") if (d and isinstance(d.get("history"), dict)) else {}
        history = store._fold_today(history, d)
        today = datetime.date.today().isoformat()
        today_seconds = int(history.get(today, 0))
        return {"goalMin": goal_min, "todaySeconds": today_seconds,
                "met": today_seconds >= goal_min * 60,
                "streak": store.streak_from_history(history, goal_min * 60)}

    def get_memory_state(self):
        """Memory dashboard state: today's dream line, the daily recall
        budget, and unlocked epoch markers (name + description for chips).

        The dream is recomputed through the same deterministic build_dream the
        pet uses at wake, so the card can never disagree with the bubble.
        """
        c = store.load_config()
        flags = c.get("epochFlags") or []
        flags = flags if isinstance(flags, list) else []
        d = store.read_wellbeing()
        dream = store.build_dream(d) if isinstance(d, dict) else ""
        return {"wakeDate": str(c.get("wakeDate") or ""),
                "dream": dream,
                "memoryCount": int(c.get("memoryCount", 0) or 0),
                "memoryMax": int(c.get("memoryMax", store.MEMORY_MAX_DEFAULT)
                                 or store.MEMORY_MAX_DEFAULT),
                "epochFlags": [{"id": eid, "name": name, "desc": desc}
                               for (eid, name, desc) in store.EPOCHS if eid in flags]}

    def get_memory_lane(self):
        """The pet's memory lane (P8): the last 7 days, each narrated in the
        pet's voice from the REAL shape of that day â€” store.build_lane +
        day_note are the same pure rules the pet itself would use, so the
        card can never disagree with the pet's own telling."""
        d = store.read_wellbeing()
        events = []
        try:
            pet_id = sprites.PETS[_pet_idx(store.load_config())]["id"]
            with open(store.activity_log_path(pet_id),
                      encoding="utf-8") as fh:
                for line in fh:
                    try:
                        events.append(json.loads(line))
                    except Exception:
                        continue
        except Exception:
            pass
        return store.build_lane(d if isinstance(d, dict) else None, events)

    def get_alerts(self, limit=3):
        """Lifestyle alerts (P8): today's pet-bubble alert line (when one
        fired) plus the most recent alert events. The pet fires at most one
        per day (config alertDate guard) and logs each as kind "alert";
        this API only reads that log."""
        out = {"today": "", "last": []}
        try:
            pet_id = sprites.PETS[_pet_idx(store.load_config())]["id"]
            today = time.strftime("%Y-%m-%d")
            with open(store.activity_log_path(pet_id),
                      encoding="utf-8") as fh:
                for line in fh:
                    try:
                        e = json.loads(line)
                    except Exception:
                        continue
                    if e.get("kind") != "alert":
                        continue
                    entry = {"alert": e.get("alert", ""),
                             "line": e.get("line", ""), "t": e.get("t", 0)}
                    if not out["today"] and time.strftime(
                            "%Y-%m-%d", time.localtime(e.get("t", 0) or 0)) == today:
                        out["today"] = entry["line"]
                    out["last"].append(entry)
            out["last"] = out["last"][-_safe_int(limit, 3):]
        except Exception:
            pass
        return out

    def get_chronotype(self):
        """Chronotype (P5): the pet's gene state read from the user's REAL
        hour fingerprint â€” the same pure store rules the pet engine uses, so
        the dashboard card can never disagree with the bubble."""
        c = store.load_config()
        chrono_type = str(c.get("chronoType", "larval") or "larval")
        d = store.read_wellbeing()
        hour_history = d.get("hourHistory") if (d and isinstance(d.get("hourHistory"), dict)) else {}
        profile = store.chronotype_profile(hour_history)
        return {"chronoType": chrono_type,
                "chronoDate": str(c.get("chronoDate", "") or ""),
                "genes": store.gene_manifest(chrono_type),
                "fingerprintHours": [{"hour": h, "seconds": profile["hours"].get(h, 0)}
                                     for h in range(24)],
                "activeHours": profile["active_hours"],
                "peakHour": profile["peakLabel"],
                "dataDays": profile["days"],
                "neededDays": store.CHRONO_MIN_DAYS,
                "nextReview": store.chrono_next_review(c.get("chronoWeekDate")),
                "readout": store.chrono_readout(chrono_type, profile)}

    def get_day_health(self):
        """Day-body (P6): the pet's embodied day state â€” the SAME pure store
        rule the pet engine draws, so the card can never disagree with the
        aura. Errors come from this pet's activity log, focus from focus.json.

        since = wall-clock epoch the current state began (from the pet's own
        embody log); 0 when the engine hasn't logged one yet.
        """
        d = store.read_wellbeing()
        pet_id = sprites.PETS[_pet_idx(store.load_config())]["id"]
        log_path = store.activity_log_path(pet_id)
        today = time.strftime("%Y-%m-%d")
        errors = 0
        since = 0.0
        try:
            with open(log_path, encoding="utf-8") as fh:
                for line in fh:
                    try:
                        e = json.loads(line)
                    except Exception:
                        continue
                    if e.get("kind") == "state" and e.get("state") in ("error", "retry") \
                            and time.strftime("%Y-%m-%d",
                                              time.localtime(e.get("t", 0))) == today:
                        errors += 1
        except Exception:
            pass
        focus = {}
        try:
            with open(store.FOCUS_FILE, encoding="utf-8") as fh:
                f = json.load(fh)
            if isinstance(f, dict) and f.get("active"):
                focus = {"active": True,
                         "elapsed": time.time() - float(f.get("startedAt", 0) or 0),
                         "wilted": bool(f.get("wilted"))}
        except Exception:
            pass
        h = store.day_health(d if isinstance(d, dict) else {},
                             errors=errors, focus=focus or None,
                             goal_min=store.goal_minutes(store.load_config()))
        # wall-clock start of the current state (append-ordered embody log)
        try:
            with open(log_path, encoding="utf-8") as fh:
                for line in fh:
                    try:
                        e = json.loads(line)
                    except Exception:
                        continue
                    if e.get("kind") == "embody" and e.get("state") == h["state"]:
                        since = float(e.get("t", 0) or 0)
        except Exception:
            pass
        return {"state": h["state"], "label": h["label"],
                "intensity": h["intensity"], "since": since}

    def get_pomo_state(self):
        """Pomodoro cycle state for the dashboard rail card.

        Returns {count, nextIsLong, pomoMin, pomoShort, pomoLong} â€” count is
        today's completed sessions; nextIsLong is whether the break after the
        NEXT completed pomodoro is a long one (every 4th).
        """
        c = store.load_config()
        count = int(c.get("pomoCount", 0))
        return {"count": count,
                "nextIsLong": store.pomo_next_long(count),
                "pomoMin": int(c.get("pomoMin", 25) or 25),
                "pomoShort": int(c.get("pomoShort", 5) or 5),
                "pomoLong": int(c.get("pomoLong", 15) or 15)}

    def get_rituals(self):
        """Today's personal rituals (P7) with LIVE progress â€” the same pure
        store derivation and progress rules the pet engine uses, so the card
        can never disagree with the bubble. Prefers the engine's persisted
        daily list (ritualDate/ritualList) and falls back to deriving fresh
        when the engine hasn't run today (e.g. dashboard-only session)."""
        c = store.load_config()
        d = store.read_wellbeing()
        wb = d if isinstance(d, dict) else {}
        today = time.strftime("%Y-%m-%d")
        rituals = []
        if str(c.get("ritualDate") or "") == today:
            rl = c.get("ritualList")
            if isinstance(rl, list):
                rituals = [dict(r) for r in rl if isinstance(r, dict)]
        if not rituals:
            rituals = store.derive_rituals(wb, 0, c)
        for r in rituals:
            p = store.ritual_progress(r, wb, c)
            r["current"] = p["current"]
            r["done"] = p["done"]
        return {"ritualDate": today, "rituals": rituals}

    def get_barter_state(self):
        """Attention barter (P7): banked focus minutes, form stage, and the
        next tradable stage. offered = the pet asked for this trade today
        (pending confirmation); the trade itself is available whenever the
        bank covers the cost."""
        c = store.load_config()
        bank = int(c.get("barterBank", 0) or 0)
        stage = int(c.get("barterStage", 0) or 0)
        offer = store.barter_next_offer(stage)
        today = time.strftime("%Y-%m-%d")
        od = str(c.get("barterOfferDate") or "")
        offered = bool(od and od == today and offer is not None
                       and bank >= offer["costMinutes"])
        return {"bank": bank, "stage": stage, "nextOffer": offer,
                "offered": offered}

    def barter_pay(self):
        """Confirm the standing barter offer — writes the one-shot command;
        the pet process owns the trade (bank deduction + stage-up ceremony)."""
        self._cmd("barterPay")
        return True

    def get_pet_state(self):
        """Live pet state: the engine's own resolution (raw/state/anim) plus
        the movement toggles and drag flag.

        The engine writes pet-state.json at ~2Hz on change (cross-process:
        this process can't touch the engine's memory), so this reads that
        snapshot. Before the first snapshot (engine not running) it falls
        back to a best-effort read of the session files.
        """
        try:
            with open(store.state_file_path(), encoding="utf-8") as fh:
                d = json.load(fh)
            if isinstance(d, dict):
                t = d.get("t")
                if isinstance(t, (int, float)) and time.time() - t > SNAPSHOT_STALE_SECS:
                    d = dict(d, stale=True)
                return d
        except Exception:
            pass
        sess = store.read_status()
        raw = None
        if sess and not sess[0].get("stale"):
            raw = sess[0].get("state") or None
        return {"raw": raw,
                "state": raw or ("busy" if _current_app_session() else "idle"),
                "anim": None,
                "mood": store.load_config().get("mood", "neutral"),
                "eventMap": None,
                "arrows": True, "followCursor": True, "drag": False}

    # ------------------------------------------------------ task orchard
    def get_orchard_state(self):
        """Task Orchard: the garden state for the dashboard â€” every tree
        (sorted: ripe first, then growing, seed, done, pruned), the next tree
        the pet tends (the SAME pure store rule the pet's waggle bubble uses),
        terroir yields per soil, and whether the weekly prune ran today."""
        d = store.read_tasks()
        tasks = d.get("tasks") or []
        rank = {"ripe": 0, "growing": 1, "seed": 2, "done": 3, "pruned": 4}
        trees = sorted((dict(t) for t in tasks if isinstance(t, dict)),
                       key=lambda t: (rank.get(t.get("status"), 9),
                                      -float(t.get("invested") or 0)))
        try:
            from desktop import main as _app
            app = _app.foreground_app()
        except Exception:
            app = ""
        return {"trees": trees,
                "nextTask": store.orchard_next_task(tasks, app),
                "terroir": d.get("terroir") or {},
                "prunedToday": str(d.get("pruneDate") or "")
                               == time.strftime("%Y-%m-%d")}

    def orchard_plant(self, title=None, soil="other", estMin=30, gamble=False):
        """Plant a task-tree. Strict validation (P10 style): 1-60 char title,
        known soil id, estMin 1-600 minutes, gamble coerced to bool. The
        control process writes the tree; the pet process owns all growth."""
        if not isinstance(title, str):
            return False
        title = title.strip()
        if not title or len(title) > 60:
            return False
        soil = str(soil or "other")
        if soil not in store.ORCHARD_SOILS:
            return False
        est = _safe_int(estMin, 0)
        if est < 1 or est > 600:
            return False
        now = time.time()
        task = {"id": "t%d-%d" % (int(now * 1000), random.randint(0, 9999)),
                "title": title, "soil": soil, "estMin": est, "invested": 0,
                "status": "seed", "planted": now, "updated": now,
                "lastTs": now, "gambled": bool(gamble), "doneAt": None,
                "harvested": False}

        def add(cur):
            cur.setdefault("tasks", []).append(task)
            return cur

        return store.update_tasks(add)

    def orchard_harvest(self, task_id=None):
        """Harvest-request for one tree: marks it done (doneAt) under the
        tasks.json lock. The pet settles the harvest on its next tick â€” XP,
        terroir tally, and the gamble wither check are engine-side (it owns
        growth), so this never awards anything itself. Returns False when the
        tree isn't harvestable (already done / not past its estimate)."""
        if not isinstance(task_id, str):
            return False
        result = {}

        def mark(cur):
            for t in cur.get("tasks") or []:
                if not isinstance(t, dict) or t.get("id") != task_id:
                    continue
                est = max(1, int(t.get("estMin") or 0)) * 60
                past = float(t.get("invested") or 0) >= est
                if t.get("status") == "ripe" or (
                        t.get("status") in ("seed", "growing") and past):
                    t["status"] = "done"
                    t["doneAt"] = time.time()
                    t["updated"] = t["doneAt"]
                    result["ok"] = True
                return cur
            return None  # unknown id: nothing written

        store.update_tasks(mark)
        return bool(result.get("ok"))

    def orchard_delete(self, task_id=None):
        """Remove one tree from the garden â€” the pet never grows it again.
        Returns False when no such tree exists."""
        if not isinstance(task_id, str):
            return False

        def rem(cur):
            before = cur.get("tasks") or []
            cur["tasks"] = [t for t in before
                            if not (isinstance(t, dict) and t.get("id") == task_id)]
            return cur if len(cur["tasks"]) != len(before) else None

        return store.update_tasks(rem)

    def get_weekly_wrapped(self):
        """'Your Week in Focus' summary: totals, best day, top app, streak,
        XP earned â€” rendered client-side; copy-to-clipboard share text."""
        out = {"days": 7, "weekSeconds": 0, "bestDay": None, "topApp": None,
               "streak": 0, "xp": 0, "focusSessions": 0, "prevWeekSeconds": 0}
        d = store.read_wellbeing()
        today = datetime.date.today()
        history = {}
        app_hist = {}
        if d:
            history = d.get("history") if isinstance(d.get("history"), dict) else {}
            app_hist = d.get("appHistory") if isinstance(d.get("appHistory"), dict) else {}
            history = store._fold_today(history, d)
        week, prev = store.week_window(history, today=today)
        out["weekSeconds"] = sum(week.values())
        out["prevWeekSeconds"] = sum(prev.values())
        if out["weekSeconds"] > 0:
            best = max(week, key=week.get)
            out["bestDay"] = {"date": best, "seconds": week[best]}
        app_tot = {}
        for i in range(7):
            day = (today - datetime.timedelta(days=i)).isoformat()
            day_map = app_hist.get(day)
            if isinstance(day_map, dict):
                for app, secs in day_map.items():
                    if isinstance(secs, (int, float)):
                        app_tot[app] = app_tot.get(app, 0) + int(secs)
        if d and d.get("date") == today.isoformat():
            for app, secs in (d.get("apps") or {}).items():
                if isinstance(secs, (int, float)):
                    app_tot[app] = app_tot.get(app, 0) + int(secs)
        if app_tot:
            top = max(app_tot, key=app_tot.get)
            out["topApp"] = {"app": top, "seconds": app_tot[top]}
        # streak + XP + session count
        c = store.load_config()
        out["xp"] = int(c.get("xp", 0))
        out["level"] = int(c.get("level", 1))
        profile = self.get_pet_profile()
        out["streak"] = profile["streak"]
        # count focus sessions in the activity log this week
        try:
            pet_id = sprites.PETS[_pet_idx(c)]["id"]
            with open(store.activity_log_path(pet_id),
                      encoding="utf-8") as fh:
                for line in fh:
                    try:
                        e = json.loads(line)
                    except Exception:
                        continue
                    if e.get("kind") == "focusDone" and \
                            time.time() - (e.get("t") or 0) < store.WEEK_SECS:
                        out["focusSessions"] += 1
        except Exception:
            pass
        return out

    def get_week_apps(self, days=7):
        """Per-app totals for the last N days (ascending; today folded in)."""
        days = max(1, min(_safe_int(days, 7), 30))
        out = {}
        d = store.read_wellbeing()
        today = datetime.date.today()
        app_hist = d.get("appHistory") if (d and isinstance(d.get("appHistory"), dict)) else {}
        for i in range(days):
            day = (today - datetime.timedelta(days=i)).isoformat()
            day_map = app_hist.get(day)
            if isinstance(day_map, dict):
                for app, secs in day_map.items():
                    if isinstance(secs, (int, float)):
                        out[app] = out.get(app, 0) + int(secs)
        if d and d.get("date") == today.isoformat() and isinstance(d.get("apps"), dict):
            for app, secs in d["apps"].items():
                if isinstance(secs, (int, float)):
                    out[app] = out.get(app, 0) + int(secs)
        rows = [{"app": a, "seconds": s} for a, s in out.items() if s >= store.WEEK_APP_MIN_SECS]
        rows.sort(key=lambda x: -x["seconds"])
        return rows[:store.TOP_APPS_LIMIT]

    def next_pet(self):
        c = store.load_config()
        c["petIdx"] = (_pet_idx(c) + 1) % len(sprites.PETS)
        store.save_config(c)
        return True

    def prev_pet(self):
        c = store.load_config()
        c["petIdx"] = (_pet_idx(c) - 1) % len(sprites.PETS)
        store.save_config(c)
        return True

    def save_config(self, conf):
        c = store.load_config()
        c.update(_sanitize_config(conf))  # merge â€” never drop petVisible or pending commands
        store.save_config(c)
        return True

    def _cmd(self, key, val=1):
        """Write a one-shot command, merging under the cross-process lock so a
        concurrent settings save from the pet process can't be clobbered."""
        try:
            with store._config_lock() as fd:
                if fd is None:
                    return
                c = store._read_locked_fd(fd)
                if not isinstance(c, dict):
                    c = {}
                c[key] = val
                store._write_locked_fd(fd, c)
        except Exception:
            pass

    def hide_pet(self):
        self._cmd("hidePet")
        return True

    def show_pet(self):
        self._cmd("showPet")
        return True

    def hide_control(self):
        if self._control is not None:
            try:
                self._control.hide()
            except Exception:
                pass
        return True

    def quit(self):
        """Graceful shutdown: signal threads, save state, then exit."""
        self._shutdown = True
        self._cmd("quit")
        # Give daemon threads a moment to finish their current tick and save state.
        # render_loop and watcher will exit on their next loop iteration.
        try:
            time.sleep(0.6)
        except Exception:
            pass
        sys.exit(0)

