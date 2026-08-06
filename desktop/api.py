"""ControlApi — the JS bridge contract for the pet dashboard/control UI.

Runs in the SEPARATE control process (or the --web server). Talks to the pet
via config.json + one-shot commands, so the pet process never hosts a browser.
"""

import datetime
import json
import os
import sys
import time

from . import engine, sprites, store

# Methods the --web RPC bridge accepts; must stay in sync with the desktop
# ControlApi (guarded by tests/test_spec_contract.py).
_WEB_METHODS = [
    "get_config", "get_previews", "get_sessions", "get_logs",
    "get_wellbeing", "get_wellbeing_history", "get_wellbeing_insights",
    "get_focus_state", "start_focus", "stop_focus", "set_focus_tag", "get_pet_profile",
    "get_goal_state", "get_pomo_state", "get_weekly_wrapped", "get_week_apps",
    "get_focus_peaks", "get_memory_state", "get_chronotype", "get_day_health",
    "get_rituals", "get_barter_state", "barter_pay",
    "save_config", "next_pet", "prev_pet", "hide_pet", "show_pet",
    "hide_control", "quit",
]
# Methods that make no sense from a browser tab: there is no control window
# to hide (the tab IS the UI), so hide_control is a no-op. quit is NOT a
# no-op: the dashboard's Quit button means "quit the pet app", and the real
# pet process reads the quit one-shot command from config.json — so we write
# the command (like ControlApi.quit does) but never os._exit(0) the SERVER.
_WEB_NOP = frozenset(["hide_control"])


def _current_app_session():
    """Resolve current_app_session through the desktop.main namespace: the
    test suite monkeypatches main.current_app_session, so the lookup must
    happen at call time (lazy import — api is imported BY main)."""
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
        c["petName"] = sprites.PETS[c.get("petIdx", 0) % len(sprites.PETS)]["name"]
        sess = store.read_status()
        c["state"] = (sess[0].get("state") or "idle") if sess and not sess[0].get("stale") else ("busy" if _current_app_session() else "idle")
        return c

    def get_previews(self):
        return sprites.build_previews()

    def get_sessions(self):
        # ACTIVE sessions only — working/thinking/error/celebrating right now.
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
        pet_id = sprites.PETS[store.load_config().get("petIdx", 0) % len(sprites.PETS)]["id"]
        log_path = os.path.join(store.PET_DIR, "activity-%s.jsonl" % pet_id)
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
        days = int(days) if days is not None else 7  # 0 => 1 via the clamp below
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
        """
        d = store.read_wellbeing()
        if d is None:
            return {"weekSeconds": 0, "prevWeekSeconds": 0, "deltaPct": None,
                    "bestDay": None, "todaySeconds": 0, "topApp": None}
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
        return {
            "weekSeconds": week_secs,
            "prevWeekSeconds": prev_secs,
            "deltaPct": delta,
            "bestDay": best_day,
            "todaySeconds": running,
            "topApp": top_app,
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
          runnerUp        : second-busiest hour (or None) — shows the spread
          spanLabel       : "mornings" / "afternoons" / "evenings" / "nights"
                            for the best hour, for a friendlier UI line
        """
        days = int(days) if days is not None else 7  # 0 => 1 via the clamp below
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
        the session ends; a new session starts untagged."""
        tag = (tag or "").strip()[:40]
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
        self._cmd("focusStart", int(minutes) if minutes else engine.FOCUS_DEFAULT_MIN)
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

        Returns {goalMin, todaySeconds, met, streak} — todaySeconds folds the
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

    def get_chronotype(self):
        """Chronotype (P5): the pet's gene state read from the user's REAL
        hour fingerprint — the same pure store rules the pet engine uses, so
        the dashboard card can never disagree with the bubble."""
        c = store.load_config()
        chrono_type = str(c.get("chronoType", "larval") or "larval")
        d = store.read_wellbeing()
        hour_history = d.get("hourHistory") if (d and isinstance(d.get("hourHistory"), dict)) else {}
        profile = store.chronotype_profile(hour_history)
        return {"chronoType": chrono_type,
                "chronoDate": str(c.get("chronoDate", "") or ""),
                "genes": store.gene_manifest(chrono_type, profile),
                "fingerprintHours": [{"hour": h, "seconds": profile["hours"].get(h, 0)}
                                     for h in range(24)],
                "activeHours": profile["active_hours"],
                "peakHour": profile["peakLabel"],
                "dataDays": profile["days"],
                "neededDays": store.CHRONO_MIN_DAYS,
                "nextReview": store.chrono_next_review(c.get("chronoWeekDate")),
                "readout": store.chrono_readout(chrono_type, profile)}

    def get_day_health(self):
        """Day-body (P6): the pet's embodied day state — the SAME pure store
        rule the pet engine draws, so the card can never disagree with the
        aura. Errors come from this pet's activity log, focus from focus.json.

        since = wall-clock epoch the current state began (from the pet's own
        embody log); 0 when the engine hasn't logged one yet.
        """
        d = store.read_wellbeing()
        pet_id = sprites.PETS[store.load_config().get("petIdx", 0) % len(sprites.PETS)]["id"]
        log_path = os.path.join(store.PET_DIR, "activity-%s.jsonl" % pet_id)
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

        Returns {count, nextIsLong, pomoMin, pomoShort, pomoLong} — count is
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
        """Today's personal rituals (P7) with LIVE progress — the same pure
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

    def get_weekly_wrapped(self):
        """'Your Week in Focus' summary: totals, best day, top app, streak,
        XP earned — rendered client-side; copy-to-clipboard share text."""
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
            pet_id = sprites.PETS[c.get("petIdx", 0) % len(sprites.PETS)]["id"]
            with open(os.path.join(store.PET_DIR, "activity-%s.jsonl" % pet_id),
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
        days = max(1, min(int(days) if days else 7, 30))
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
        c["petIdx"] = (int(c.get("petIdx", 0)) + 1) % len(sprites.PETS)
        store.save_config(c)
        return True

    def prev_pet(self):
        c = store.load_config()
        c["petIdx"] = (int(c.get("petIdx", 0)) - 1) % len(sprites.PETS)
        store.save_config(c)
        return True

    def save_config(self, conf):
        c = store.load_config()
        c.update(conf)  # merge — never drop petVisible or pending commands
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
