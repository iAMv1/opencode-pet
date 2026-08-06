"""PetEngine: physics, sprite slicing, state resolution, focus/growth logic.

Renders via win32.PetWindow. OS activity (last_input_ms/foreground_app) is
resolved through the desktop.main namespace at call time so the test suite's
monkeypatches on main.last_input_ms keep working.
"""

import datetime
import json
import math
import os
import random
import time

from PIL import Image, ImageDraw, ImageFont

from . import sounds, sprites, store, win32

# ---------------------------------------------------------------- focus sessions
FOCUS_DEFAULT_MIN = 25
FOCUS_MAX_MIN = 180
FOCUS_WILT_IDLE_SECS = 45     # idle this long wilts the sprout
FOCUS_BUBBLE_SECS = 4.0
FOCUS_CAST_SECS = 1.0
FOCUS_ATTENTION_SECS = 3.0

# ---------------------------------------------------------------- XP / growth
XP_BASE = 100
XP_STEP = 50
XP_FOCUS_BONUS = 50
XP_GOAL_BONUS = 20
XP_STREAK_BONUS = 25
XP_TOOL_EARN = 2
XP_COMPLETE_BONUS = 5
STREAK_BONUS_MULTIPLE = 5
LEVEL_BUBBLE_SECS = 4.0
LEVEL_ATTENTION_SECS = 3.0
GOAL_BUBBLE_SECS = 4.0
GOAL_CAST_SECS = 1.0

# ---------------------------------------------------------------- break tracker
BREAK_COOLDOWN_SECS = 300   # min time between break nudges
BREAK_NUDGE_SECS = 5        # nudge bubble lifetime
BREAK_TIRED_MULTIPLE = 2    # working 2x breakMin => tired mood
SNOOZE_DEFAULT_MIN = 5      # break snooze length when the command lacks a value

# ---------------------------------------------------------------- stretch nudge
STRETCH_DEFAULT_MIN = 45    # continuous-work threshold (0 = off)
STRETCH_COOLDOWN_SECS = 1800  # max 1 stretch nudge per 30 min
XP_STRETCH = 2

# ---------------------------------------------------------------- memory / wake ritual
WAKE_BUBBLE_SECS = 5.0      # wake greeting bubble lifetime
WAKE_LINES = [
    "Back! I kept the seat warm.",
    "You were gone a while \u2014 welcome back.",
    "Rise and shine. Terminals missed you.",
    "Awake again. Let's make it count.",
]
MEMORY_BUBBLE_SECS = 5.0    # memory recall bubble lifetime
MEMORY_SHIMMER_SECS = 4.0   # brief happy shimmer after a recall (no XP)
XP_EPOCH = 25               # epoch crossings ARE earned milestones
EPOCH_BUBBLE_SECS = 5.0     # epoch celebration bubble lifetime

# ---------------------------------------------------------------- chronotype (P5)
XP_METAMORPH = 50           # metamorphosis into a chrono gene — a real milestone
CHRONO_BUBBLE_SECS = 5.0    # metamorph / drift bubble lifetime

# ---------------------------------------------------------------- day-body (P6)
EMBODY_TICK_SECS = 30       # re-embody cadence (plus force on goal/focus events)
STATIC_BUBBLE_SECS = 600    # max one error-static bubble per 10 min

# ---------------------------------------------------------------- rituals (P7)
XP_RITUAL = 15              # a completed personal ritual IS earned, not spam
RITUAL_BUBBLE_SECS = 5.0    # ritual completion / day-close bubble lifetime

# ---------------------------------------------------------------- barter (P7)
XP_BARTER = 20              # a traded form stage — the user's attention, paid
BARTER_BUBBLE_SECS = 5.0    # barter ask / ceremony bubble lifetime
BARTER_SHIMMER_SECS = 90    # periodic cast shimmer between stages (visual only)

# ---------------------------------------------------------------- physics
PHYS_TICK_MS = 16.7
PHYS_STEP_CLAMP_MS = 50     # clamp huge frame deltas (lag spike = jump)
PHYS_GRAVITY = 0.35
PHYS_POKE_VY = 1.4
PHYS_JUMP_VY = 3.0
PHYS_BOUNCE_VY = 3.0        # land harder than this -> bounce
PHYS_BOUNCE = 0.35          # bounce restitution
PHYS_WALL_JUMP_VY = 2.6
WALK_CHANCE_ACTIVE = 0.45
WALK_SPEED_MIN = 0.7
WALK_SPEED_RANGE = 0.9
ROAM_INITIAL_MS = 4000
ROAM_MIN_MS = 3500
ROAM_RANGE_MS = 3500
REST_MIN_MS = 7000
REST_RANGE_MS = 8000
WALK_MIN_MS = 1200
WALK_RANGE_MS = 1800
REST_AFTER_WALK_MIN_MS = 6000
REST_AFTER_WALK_RANGE_MS = 6000

# ---------------------------------------------------------------- bubbles
BUBBLE_PAD = 8
BUBBLE_HEIGHT = 22
BUBBLE_RADIUS = 10
BUBBLE_TOP = 4
BUBBLE_TAIL_HALF = 5
BUBBLE_TAIL_HEIGHT = 6
BUBBLE_MARGIN = 8           # canvas edge margin for the bubble
TOOL_BUBBLE_SECS = 3.5
PERSONALITY_BUBBLE_SECS = 4
APP_BUBBLE_SECS = 3
CAST_DURATION_SECS = 0.9
STATUS_DOT_R = 6


class PetEngine:
    """Physics + sprite slicing + state resolution, renders via PetWindow."""

    FPS = 30
    TICK = 1.0 / FPS

    def __init__(self):
        self.win = win32.PetWindow()
        self.win.engine = self
        self.cfg = store.load_config()
        self.pet = sprites.PETS[self.cfg["petIdx"] % len(sprites.PETS)]
        self.sheet = None
        self._load_sheet()
        self._init_physics()
        self._init_focus()
        self._init_growth()
        self._init_memory()
        self._init_chrono()
        self._init_embody()
        self._init_rituals()
        self._init_barter()
        self._load_wellbeing()
        self._load_focus_state()
        self._build_frame_cache()
        self._shutdown = False
        self._watch_failures = 0  # consecutive read_dir_changes failures -> fallback to polling

    def _init_physics(self):
        self.dragging = False
        self.phys = {"x": 80, "y": 0, "vx": 0, "vy": 0, "grounded": True,
                     "mode": "idle", "t": 0, "walkT": 0, "spawned": False}
        self.area = (0, 0, 1920, 1040)
        self.sessions = []
        self.os_app = ""
        self.os_active = False
        self.roam_after_ms = ROAM_INITIAL_MS
        self.walk_factor = self.cfg["walk"] / 100.0
        self.anim = sprites.pet_states(self.pet)[0]
        self.frame_idx = 0
        self.acc = 0.0
        self.bubble_text = ""
        self.bubble_until = 0.0
        self.running = True
        self._frame_cache = {}
        self._last_act = 0.0
        self._last_content = None
        self._last_pos = None
        self._last_log = 0.0
        self._prev_state = "_start"
        self._prev_tool = ""
        self._last_active_min = 0.0
        self._last_poke_log = 0.0
        self._stale_emotion = None   # BUG-3: preserve last emotion across stale boundary
        self.break_min = int(self.cfg.get("breakMin", 50))
        self.break_track_start = None
        self._break_shown = False
        self._last_break = 0.0
        self._snooze_min = 0          # pending one-shot break snooze (minutes)
        self.stretch_min = int(self.cfg.get("stretchMin", STRETCH_DEFAULT_MIN))
        self._stretch_start = None    # continuous-work marker (None = not working)
        self._last_stretch = 0.0
        self.chimes_on = bool(self.cfg.get("chimes", True))
        self.attention_until = 0.0
        self.cast = None  # focus-completion cast flash (small independent event)
        self._wb = {}
        self._wb_date = time.strftime("%Y-%m-%d")
        self._wb_t = time.time()
        self._last_wb_save = 0.0
        self._history = {}   # date "YYYY-MM-DD" -> total focused seconds (past days)
        self._app_history = {}  # date "YYYY-MM-DD" -> {app: seconds} (per-day breakdown)
        self._hour_today = {}   # today's {hour: seconds} — folded into _hour_history at rollover
        self._hour_history = {}  # date "YYYY-MM-DD" -> {hour: seconds} (per-day, per-hour)
        self._font = None  # lazy font cache (truetype() is ~5ms — load once)

    def _init_focus(self):
        # focus sessions (inverse-Tamagotchi)
        self.focus_active = False
        self.focus_started = 0.0
        self.focus_target_min = int(self.cfg.get("focusMin", FOCUS_DEFAULT_MIN))
        self.focus_wilted = False
        self._focus_app = ""
        self._focus_tag = ""

    def _init_growth(self):
        # daily focus goal (config: goalMin minutes; lastGoalDate = last day met)
        self.goal_min = store.goal_minutes(self.cfg)
        self._last_goal_date = str(self.cfg.get("lastGoalDate", "") or "")
        # pet growth (XP / level / mood)
        self.xp = int(self.cfg.get("xp", 0))
        self.level = int(self.cfg.get("level", 1))
        self.mood = "neutral"
        self._last_tool_earn = ""

    def _init_memory(self):
        # wake ritual: idle->active transitions + the once-per-day dream
        self._was_active = False
        self._idle_since = time.time()
        self._first_tick = True
        self._last_idle_wake = float(self.cfg.get("wakeIdleAt", 0) or 0)
        # episodic memory bubbles: memoryMin minutes of WORK time between
        # recalls (jittered 0.75-1.25x -> 45-75 min at the default 60), max
        # memoryMax per day (counter in config so restarts can't reset it)
        self.memory_min = max(1, int(self.cfg.get("memoryMin", store.MEMORY_MIN_DEFAULT)))
        self.memory_max = max(1, int(self.cfg.get("memoryMax", store.MEMORY_MAX_DEFAULT)))
        self._memory_work = 0.0
        self._next_memory_work = self.memory_min * 60 * random.uniform(0.75, 1.25)
        self._shimmer_until = 0.0
        self._shimmer_mood = None
        # epoch crossings: one celebration per marker, ever
        self._last_fc_read = 0.0
        self._focus_count_cache = 0

    def _init_chrono(self):
        # P5: the pet's chrono-genes come from the user's REAL hour
        # fingerprint. larval until enough days of hourHistory exist; then
        # chronoDate/chronoWeekDate in config guard the one-time metamorph
        # and the weekly drift re-review (both survive restarts).
        self.chrono_type = str(self.cfg.get("chronoType", "larval") or "larval")
        self.chrono_date = str(self.cfg.get("chronoDate", "") or "")
        self.chrono_week_date = str(self.cfg.get("chronoWeekDate", "") or "")
        self._chrono_checked = ""      # date of the last fingerprint evaluation
        self._chrono_glow_cache = {}   # gene aura -> prerendered glow

    def _init_embody(self):
        # P6: the pet's body IS the dashboard — day-health shown as aura +
        # mood instead of meters. Re-derived every EMBODY_TICK_SECS (and on
        # goal/focus events); aura overlay only, no sprite changes.
        self._embody_state = "flow"
        self._embody_intensity = 0.0
        self._embody_since = time.time()
        self._embody_aura = None       # store.EMBODY_AURA tuple or None
        self._embody_glow_cache = {}   # (r,g,b,a) -> prerendered glow
        self._last_embody = 0.0
        self._last_static_bubble = 0.0  # error-static bubble cooldown

    def _init_rituals(self):
        # P7: personal rituals derived from the user's OWN history. Derived
        # once per day (ritualDate in config guards restarts); ritualDone
        # lists the ids completed today so XP awards exactly once per ritual.
        rl = self.cfg.get("ritualList")
        self._rituals = [dict(r) for r in rl if isinstance(r, dict)] \
            if isinstance(rl, list) else []
        self._ritual_done = set(self.cfg.get("ritualDone") or [])
        self._dayclose_date = str(self.cfg.get("ritualCloseDate", "") or "")

    def _init_barter(self):
        # P7: attention barter — banked focus minutes traded for form stages.
        # bank/stage/offerDate live in config (survive restarts); the seconds
        # accumulator flushes whole minutes to the bank at most once/min.
        self._barter_bank = int(self.cfg.get("barterBank", 0) or 0)
        self._barter_stage = int(self.cfg.get("barterStage", 0) or 0)
        self._barter_offer_date = str(self.cfg.get("barterOfferDate", "") or "")
        self._barter_acc = 0.0
        self._last_barter_shimmer = 0.0
        self._barter_glow_cache = {}   # stage -> prerendered radiance glow

    def _log(self, kind, **data):
        """Append one JSON line to THIS pet's activity log — one pet, one memory."""
        try:
            log_path = os.path.join(store.PET_DIR, "activity-%s.jsonl" % self.pet["id"])
            with open(log_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"t": time.time(), "kind": kind, **data}) + "\n")
        except Exception:
            pass

    def _chime(self, kind):
        """Sound a native chime for an engine event (config-gated, always safe)."""
        if not getattr(self, "chimes_on", True):
            return
        try:
            sounds.play(kind)
        except Exception:
            pass

    def _prune_status(self):
        """Dead session files accumulate forever; drop anything older than 5 min."""
        try:
            now_ms = time.time() * 1000
            for f in os.listdir(store.PET_DIR):
                if f.startswith("status-") and f.endswith(".json"):
                    p = os.path.join(store.PET_DIR, f)
                    if now_ms - os.path.getmtime(p) * 1000 > store.STATUS_PRUNE_MS:
                        try:
                            os.unlink(p)
                        except Exception:
                            pass
        except Exception:
            pass

    def _load_wellbeing(self):
        d = store.read_wellbeing()
        if not isinstance(d, dict):
            return
        if isinstance(d.get("history"), dict):
            self._history = dict(d["history"])
        if isinstance(d.get("appHistory"), dict):
            self._app_history = dict(d["appHistory"])
        self._hour_history = {
            day: {int(h): v for h, v in day_map.items()
                  if isinstance(v, (int, float))
                  and (isinstance(h, int) or h.isdigit())}
            for day, day_map in d["hourHistory"].items()
            if isinstance(day_map, dict)} if isinstance(d.get("hourHistory"), dict) else {}
        hour_today_raw = {
            int(k): v for k, v in d["hourToday"].items()
            if isinstance(v, (int, float))
            and (isinstance(k, int) or k.isdigit())
        } if isinstance(d.get("hourToday"), dict) else {}
        self._hour_today = {}
        # Drop non-numeric app values: a corrupt file must never let a
        # TypeError reach _track_app_time/_rollover_wellbeing and kill the
        # render loop (there is no try/except on that thread path).
        apps = {k: v for k, v in d.get("apps", {}).items()
                if isinstance(v, (int, float))}
        if d.get("date") == self._wb_date:
            self._wb = apps
            self._hour_today = hour_today_raw
        elif d.get("date"):
            # The file holds a PREVIOUS day (pet was off / older build):
            # keep its date so the first _track_app_time folds that day
            # into history instead of silently dropping it.
            self._wb_date = d["date"]
            self._wb = apps
            # Preserve the previous day's hour-of-day distribution too,
            # or the peaks analysis silently loses that day's shape.
            if hour_today_raw:
                day_hours = dict(self._hour_history.get(self._wb_date, {}))
                for hour, secs in hour_today_raw.items():
                    day_hours[hour] = day_hours.get(hour, 0) + secs
                self._hour_history[self._wb_date] = day_hours

    def _save_wellbeing(self):
        try:
            os.makedirs(store.PET_DIR, exist_ok=True)
            json.dump({"date": self._wb_date, "apps": self._wb,
                       "history": getattr(self, "_history", {}),
                       "appHistory": getattr(self, "_app_history", {}),
                       "hourToday": getattr(self, "_hour_today", {}),
                       "hourHistory": getattr(self, "_hour_history", {})},
                      open(store.WELLBEING_FILE, "w", encoding="utf-8"))
        except Exception:
            pass

    # --------------------------------------------------------- focus sessions
    def _load_focus_state(self):
        try:
            with open(store.FOCUS_FILE, encoding="utf-8") as fh:
                d = json.load(fh)
            self.focus_active = bool(d.get("active"))
            self.focus_started = float(d.get("startedAt", 0))
            self.focus_target_min = int(d.get("targetMin", self.focus_target_min))
            self.focus_wilted = bool(d.get("wilted"))
            self._focus_app = d.get("app", "")
            self._focus_tag = d.get("tag", "") or ""
        except Exception:
            pass

    def _focus_tag_now(self):
        """Authoritative session tag from focus.json (the dashboard writes it
        directly via set_focus_tag), falling back to "" when unreadable."""
        try:
            with open(store.FOCUS_FILE, encoding="utf-8") as fh:
                return (json.load(fh).get("tag") or "").strip()
        except Exception:
            return ""

    def _save_focus_state(self):
        try:
            os.makedirs(store.PET_DIR, exist_ok=True)
            json.dump({"active": self.focus_active, "startedAt": self.focus_started,
                       "targetMin": self.focus_target_min, "wilted": self.focus_wilted,
                       "app": self._focus_app, "progress": self._focus_progress(),
                       "tag": self._focus_tag},
                      open(store.FOCUS_FILE, "w", encoding="utf-8"))
        except Exception:
            pass

    def _focus_progress(self):
        return store.focus_progress(self.focus_active, self.focus_started, self.focus_target_min)

    def start_focus(self, minutes=None):
        """Begin a focus session. The sprout grows while the user stays in one
        app; leaving wilts it. Completing awards XP."""
        if minutes:
            self.focus_target_min = max(1, min(int(minutes), FOCUS_MAX_MIN))
        self.focus_active = True
        self.focus_started = time.time()
        self.focus_wilted = False
        self._focus_app = self.os_app or "Desktop"
        self._focus_tag = ""  # a new session starts untagged
        self._log("focusStart", targetMin=self.focus_target_min, app=self._focus_app)
        self._save_focus_state()
        self._chime("start")
        return True

    def stop_focus(self, completed=False):
        if not self.focus_active and not completed:
            return False
        was_active = self.focus_active
        self.focus_active = False
        if was_active:
            if completed:
                self._log("focusDone", minutes=self.focus_target_min,
                          tag=self._focus_tag_now() or self._focus_app)
                self._pomo_tick()
                self._chime("complete")
            elif self.focus_wilted:
                self._log("focusWilt", minutes=self.focus_target_min)
            else:
                self._log("focusEnd", minutes=self.focus_target_min, completed=False)
        self._save_focus_state()
        return True

    def _pomo_tick(self):
        """Pomodoro cycle: one completed focus session = one tomato per day.
        Every 4th session earns a long break; a new day resets the count."""
        today = time.strftime("%Y-%m-%d")
        c = store.load_config()
        count = int(c.get("pomoCount", 0))
        if c.get("pomoDate") != today:
            count = 0
        count += 1
        long = count % 4 == 0
        pomo_short = int(c.get("pomoShort", 5) or 5)
        pomo_long = int(c.get("pomoLong", 15) or 15)
        self.cfg["pomoCount"] = count
        self.cfg["pomoDate"] = today
        self.cfg["pomoShort"] = pomo_short
        self.cfg["pomoLong"] = pomo_long
        try:
            c["pomoCount"] = count
            c["pomoDate"] = today
            store.save_config(c)
        except Exception:
            pass
        now = time.time()
        self.bubble_text = "Pomodoro %d done! Take a %s break" % (
            count, "long" if long else "short")
        self.bubble_until = now + FOCUS_BUBBLE_SECS

    def _focus_tick(self):
        """Runs at ~2Hz while a session is live: grow, wilt on app-switch or
        idle, complete at the target."""
        if not self.focus_active:
            return
        now = time.time()
        if now - self.focus_started >= self.focus_target_min * 60:
            self.focus_active = False
            self.focus_wilted = False
            self._log("focusDone", minutes=self.focus_target_min,
                      tag=self._focus_tag_now() or self._focus_app)
            self._award_xp(XP_FOCUS_BONUS, "focus")
            self.mood = "happy"
            self._save_focus_state()
            self._chime("complete")
            # celebration reaction
            self.bubble_text = "Focus complete! +50 XP \u2728"
            self.bubble_until = now + FOCUS_BUBBLE_SECS
            # pomodoro cycle (bubble wins over the XP line: the count is the
            # rarer, more actionable celebration)
            self._pomo_tick()
            self.attention_until = now + FOCUS_ATTENTION_SECS
            self.cast = {"until": now + FOCUS_CAST_SECS, "started": now}  # completion -> cast flash
            self._embody_tick(now, force=True)  # P6: completion -> bloom/flow now
            return
        # wilt when the user leaves the session app or goes idle > 45s
        if self.os_active and self.os_app and self.os_app != self._focus_app:
            if not self.focus_wilted:
                self.focus_wilted = True
                self._log("focusWilt", app=self.os_app, fromApp=self._focus_app)
                self.bubble_text = "Hey, you left! My sprout is sad \ud83c\udf31"
                self.bubble_until = now + FOCUS_BUBBLE_SECS
                self._save_focus_state()
                self._embody_tick(now, force=True)  # P6: wilted focus -> storm
        elif not self.os_active and now - self._wb_t > FOCUS_WILT_IDLE_SECS:
            if not self.focus_wilted:
                self.focus_wilted = True
                self._log("focusWilt", reason="idle")
                self.bubble_text = "Zzz\u2026 sprout needs you awake \ud83c\udf31"
                self.bubble_until = now + FOCUS_BUBBLE_SECS
                self._save_focus_state()
                self._embody_tick(now, force=True)  # P6: wilted focus -> storm

    # ------------------------------------------------------------ XP / growth
    @staticmethod
    def _xp_needed(level):
        return XP_BASE + (level - 1) * XP_STEP

    def _award_xp(self, amount, reason):
        self.xp += amount
        leveled = False
        while self.xp >= self._xp_needed(self.level):
            self.xp -= self._xp_needed(self.level)
            self.level += 1
            leveled = True
            self._log("levelUp", level=self.level)
        if leveled:
            self.mood = "happy"
            self.bubble_text = "Level %d! \ud83c\udf89" % self.level
            self.bubble_until = time.time() + LEVEL_BUBBLE_SECS
            self.attention_until = time.time() + LEVEL_ATTENTION_SECS
        self._save_growth()

    def _save_growth(self):
        try:
            c = store.load_config()
            c["xp"] = self.xp
            c["level"] = self.level
            c["mood"] = self.mood
            c["focusMin"] = self.focus_target_min
            store.save_config(c)
        except Exception:
            pass

    def _mood_tick(self):
        """Recalculate mood from recent state when nothing else changed it."""
        # memory recall shimmer: restore the pre-recall mood after a few secs
        if getattr(self, "_shimmer_until", 0) and time.time() >= self._shimmer_until:
            if self.mood == "happy" and getattr(self, "_shimmer_mood", None) is not None:
                self.mood = self._shimmer_mood
            self._shimmer_until = 0.0
            self._shimmer_mood = None
        if self.mood in ("happy",):
            return  # keep celebration mood until something else happens
        if self.os_active and self.break_min > 0 and self.break_track_start \
                and time.time() - self.break_track_start >= self.break_min * 60 * BREAK_TIRED_MULTIPLE:
            self.mood = "tired"

    def _earn_tool_xp(self, tool):
        """Small XP for completing tool calls (once per tool id)."""
        if tool and tool != self._last_tool_earn:
            self._last_tool_earn = tool
            self._award_xp(XP_TOOL_EARN, "tool")

    def _streak_days(self):
        """Consecutive days (ending today or yesterday) with >= 30min focus."""
        return store.streak_from_history(self._history)

    def _goal_tick(self):
        """Daily focus goal: celebrate once per day when today's total passes
        goalMin. lastGoalDate in config guards against re-awarding after a
        restart (this check runs every 0.5s tick, so the guard must be the
        date in config, not in-memory state)."""
        goal_secs = self.goal_min * 60
        if goal_secs <= 0 or self._last_goal_date == self._wb_date:
            return
        total = int(sum(v for k, v in self._wb.items()
                        if k != "Idle" and isinstance(v, (int, float)))) if self._wb else 0
        if total < goal_secs:
            return
        now = time.time()
        self._award_xp(XP_GOAL_BONUS, "goal")
        self._last_goal_date = self._wb_date
        try:
            c = store.load_config()
            c["lastGoalDate"] = self._wb_date
            store.save_config(c)
        except Exception:
            pass
        self.mood = "happy"
        self.mood = "happy"
        self.bubble_text = "Daily goal met!"
        self.bubble_until = now + GOAL_BUBBLE_SECS
        self.attention_until = now + FOCUS_ATTENTION_SECS
        self.cast = {"until": now + GOAL_CAST_SECS, "started": now}  # celebration cast flash
        self._log("goal", goalMin=self.goal_min)
        self._embody_tick(now, force=True)  # P6: goal met -> bloom immediately

    def _rollover_wellbeing(self):
        """The day changed: fold the finished day's total into history and
        persist immediately, then prune to a bounded window so the file never
        grows without bound."""
        total = int(sum(v for v in self._wb.values()
                        if isinstance(v, (int, float)))) if self._wb else 0
        if total > 0:
            self._history[self._wb_date] = self._history.get(self._wb_date, 0) + total
        # fold per-app breakdown too (top-app / weekly-app charts); guard the
        # attribute so a bare/legacy engine state can never crash the render loop
        if self._wb and getattr(self, "_app_history", None) is not None:
            day_apps = dict(self._app_history.get(self._wb_date, {}))
            for app, secs in self._wb.items():
                if isinstance(secs, (int, float)):
                    day_apps[app] = day_apps.get(app, 0) + int(secs)
            self._app_history[self._wb_date] = day_apps
        # fold the finished day's per-hour buckets for the best-time analysis
        # (getattr guards keep bare/legacy engine states off the crash path)
        if getattr(self, "_hour_today", None) and getattr(self, "_hour_history", None) is not None:
            day_hours = dict(self._hour_history.get(self._wb_date, {}))
            for hour, secs in self._hour_today.items():
                if isinstance(secs, (int, float)):
                    day_hours[hour] = day_hours.get(hour, 0) + int(secs)
            self._hour_history[self._wb_date] = day_hours
        if getattr(self, "_hour_today", None) is not None:
            self._hour_today = {}  # new day starts clean
        # streak bonus: a full day of >=30min focus extends the chain
        if total >= store.STREAK_MIN_SECS:
            s = self._streak_days()
            if s and s % STREAK_BONUS_MULTIPLE == 0:
                self._award_xp(XP_STREAK_BONUS, "streak")
        # Calendar arithmetic (not seconds-based): around DST the naive
        # now - N*86400 form can skip/duplicate a calendar day.
        cutoff = (datetime.date.today() - datetime.timedelta(days=store.HISTORY_WINDOW_DAYS - 1)).isoformat()
        self._history = {k: v for k, v in self._history.items() if k >= cutoff}
        if getattr(self, "_app_history", None) is not None:
            self._app_history = {k: v for k, v in self._app_history.items() if k >= cutoff}
        if getattr(self, "_hour_history", None) is not None:
            self._hour_history = {k: v for k, v in self._hour_history.items() if k >= cutoff}
        self._save_wellbeing()

    def _track_app_time(self):
        """Digital-wellbeing: attribute elapsed time to the active app."""
        now = time.time()
        date = time.strftime("%Y-%m-%d")
        if date != self._wb_date:
            self._rollover_wellbeing()
            self._wb_date = date
            self._wb = {}
        dt = now - self._wb_t
        self._wb_t = now
        if dt <= 0:
            return
        # Laptop sleep / lock screen can pause the process for hours; a giant
        # delta is a gap, not usage — crediting it would inflate one app's
        # wellbeing total and poison the daily stats.
        if dt > store.SLEEP_GAP_SECS:
            return
        if not self.os_active:
            app = "Idle"
        else:
            app = self.os_app or "Desktop"
            if app in ("Explorer", "Program Manager"):
                app = "Desktop"
            self._memory_work = getattr(self, "_memory_work", 0.0) + dt  # work time feeds recalls
            # P7: banked attention — active (non-idle) seconds accrue toward
            # the barter bank; the engine flushes whole minutes later
            self._barter_acc = getattr(self, "_barter_acc", 0.0) + dt
        self._wb[app] = self._wb.get(app, 0) + dt
        # hour-of-day bucket (used by the "best focus time" analysis)
        if getattr(self, "_hour_today", None) is not None:
            hour = time.localtime(now).tm_hour
            self._hour_today[hour] = self._hour_today.get(hour, 0) + dt
        if now - self._last_wb_save >= store.WELLBEING_SAVE_INTERVAL:
            self._last_wb_save = now
            self._save_wellbeing()

    def _log_activity(self):
        now = time.time()
        if now - self._last_log < 1.0:
            return
        self._last_log = now
        st = self.sessions[0] if self.sessions else None
        fresh = st and not st.get("stale")
        # mirror _state(): a fresh session with null/unknown state logs as idle
        our = (st.get("state") or "idle") if fresh else ("busy" if self.os_active else "waiting")
        if our != self._prev_state:
            self._log("state", state=our, sessionID=(st.get("sessionID") if st else None))
            self._prev_state = our
        tool = st.get("toolLabel") if st else ""
        if tool and tool != self._prev_tool:
            self._log("tool", tool=tool, sessionID=(st.get("sessionID") if st else None))
            self._prev_tool = tool
        if self.os_active and now - self._last_active_min >= 60:
            self._last_active_min = now
            self._log("active", app=self.os_app)
        elif self.os_active:
            self._last_active_min = now

    def _build_frame_cache(self):
        """Pre-render every sprite frame once per pet: crop+resize is the
        expensive part; per-frame render becomes a cached paste.
        Built into a local dict and swapped in atomically so the render
        thread never sees an empty cache mid-rebuild."""
        cache = {}
        if self.sheet:
            w = self.pet["frameW"] * self.pet["scale"]
            h = self.pet["frameH"] * self.pet["scale"]
            for st in sprites.pet_states(self.pet):
                for i in range(st["frames"]):
                    sx = i * self.pet["frameW"]
                    sy = st["row"] * self.pet["frameH"]
                    try:
                        f = self.sheet.crop((sx, sy, sx + self.pet["frameW"], sy + self.pet["frameH"]))
                        cache[(st["id"], i)] = f.resize((w, h), Image.NEAREST)
                    except Exception:
                        pass
        self._frame_cache = cache

    def _load_sheet(self):
        # Prefer a real per-stage sprite sheet when it exists (future art):
        # pet-<id>-stageN.webp beside the base sheet. Falls back to the base
        # sheet so launch ships with the programmatic aura only.
        p = sprites.sprite_path(self.pet["file"])
        # _load_sheet can run before the growth attrs are set during __init__
        staged = store.evolution_stage(getattr(self, "level", 1))["suffix"]
        base, ext = os.path.splitext(self.pet["file"])
        staged_file = base + "-" + staged + ext
        sp = sprites.sprite_path(staged_file)
        if os.path.exists(sp):
            p = sp
        try:
            im = Image.open(p)
            im.load()
            self.sheet = im.convert("RGBA")
        except Exception:
            self.sheet = None

    STATE_COLORS = {
        "idle": (96, 96, 116), "busy": (246, 179, 92), "thinking": (127, 200, 232),
        "error": (255, 123, 132), "success": (95, 221, 157), "celebrating": (255, 210, 125),
        "waiting": (112, 112, 122), "retry": (127, 200, 232), "stale": (112, 112, 122),
    }

    def _state_aura(self):
        """Small status dot in the top-right corner: colour = what your AI
        tools / terminal are doing. Soft pulse, no big background circle."""
        try:
            st = self._state()
            col = self.STATE_COLORS.get(st, (96, 96, 116))
            r = STATUS_DOT_R
            w = r * 2 + 4
            h = r * 2 + 4
            if getattr(self, "_sa_cache", None) is None:
                self._sa_cache = {}
            key = (col[0], col[1], col[2], w, h)
            glow = self._sa_cache.get(key)
            if glow is None:
                glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
                dr = ImageDraw.Draw(glow)
                for rr in range(r, 0, -2):
                    a = int(160 * (1 - rr / r) ** 2)
                    if a > 0:
                        dr.ellipse((2 + r - rr, 2 + r - rr, 2 + r + rr, 2 + r + rr),
                                   fill=(col[0], col[1], col[2], a))
                self._sa_cache[key] = glow
            now = time.time()
            live = st in ("busy", "thinking", "retry")
            alarm = st in ("error", "celebrating")
            if live:
                p = 0.5 + 0.5 * math.sin(now * 3.2)
            elif alarm:
                p = 0.5 + 0.5 * math.sin(now * 5.5)
            else:
                p = 0.5 + 0.5 * math.sin(now * 1.1)
            out = glow.copy()
            dr = ImageDraw.Draw(out)
            ra = min(255, int((110 if alarm else 70) + (80 if alarm else 55) * p))
            dr.ellipse((2, 2, 2 + r * 2, 2 + r * 2),
                       outline=(col[0], col[1], col[2], ra), width=2)
            return out
        except Exception:
            return None

    def _stage_aura(self):
        """Cached soft radial glow for the current evolution stage."""
        try:
            st = store.evolution_stage(self.level)
            if getattr(self, "_aura_cache", None) is None:
                self._aura_cache = {}
            key = st["id"]
            if key not in self._aura_cache:
                w = max(8, int(self.pet["frameW"] * self.pet["scale"]))
                h = max(8, int(self.pet["frameH"] * self.pet["scale"]))
                glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
                dr = ImageDraw.Draw(glow)
                cx, cy = w // 2, int(h * 0.52)
                r = max(6, int(min(w, h) * 0.42))
                for rr in range(r, 0, -2):
                    a = int(st["aura"][3] * (1 - rr / r) ** 2)
                    if a <= 0:
                        continue
                    dr.ellipse((cx - rr, cy - rr, cx + rr, cy + rr),
                               fill=(st["aura"][0], st["aura"][1], st["aura"][2], a))
                self._aura_cache[key] = glow
            return self._aura_cache[key]
        except Exception:
            return None

    def set_pet(self, idx):
        idx %= len(sprites.PETS)
        self.cfg["petIdx"] = idx
        store.save_config(self.cfg)
        self.pet = sprites.PETS[idx]
        self._log("petSwitch", toIdx=idx)  # the NEW pet remembers the switch
        self._load_sheet()
        self.anim = sprites.pet_states(self.pet)[0]
        self.frame_idx = 0
        self._build_frame_cache()

    def set_walk(self, pct):
        self.walk_factor = max(0.0, min(1.0, pct / 100.0))

    def poke(self):
        """Single click — a small surprised hop. Physics does the arc."""
        p = self.phys
        if p["grounded"] and not self.dragging:
            p["vy"] = -PHYS_POKE_VY
            p["grounded"] = False
        if time.time() - self._last_poke_log > 1.0:
            self._last_poke_log = time.time()
            self._log("poke")

    def jump(self):
        """Double click — a real leap."""
        if not self.dragging:
            self.phys["vy"] = -PHYS_JUMP_VY
            self.phys["grounded"] = False
        self._log("jump")

    def set_topmost(self, on):
        self.win.set_topmost(on)

    def set_visible(self, vis):
        if vis:
            self.win.show()
        else:
            self.win.hide()
        try:
            c = store.load_config()
            c["petVisible"] = bool(vis)
            store.save_config(c)
        except Exception:
            pass

    def _raw_state(self):
        st = self.sessions[0] if self.sessions else None
        if st and not st.get("stale"):
            return st.get("state")   # may be None
        return None

    def _state(self):
        raw = self._raw_state()
        if raw is not None:
            return raw
        st = self.sessions[0] if self.sessions else None
        if st and not st.get("stale"):
            # Fresh session with null/unknown state: treat as idle rather than
            # falling through to busy/waiting (BUG-9).
            return "idle"
        # BUG-3: use preserved stale emotion before falling back to busy/idle.
        # When nothing is driving the pet (no active session, OS idle), it
        # settles into a calm IDLE rest instead of the restless "waiting" gait —
        # so "screen idle => pet idle", matching how a companion should behave.
        return self._stale_emotion or ("busy" if self.os_active else "idle")

    def _anim_id(self):
        our = self._state()
        m = self.pet.get("map") or sprites.DEFAULT_MAP
        if not self.phys["grounded"]:
            if any(s["id"] == "jumping" for s in sprites.pet_states(self.pet)):
                return "jumping"
            # fall through to map lookup instead
        if time.time() < self.attention_until and any(s["id"] == "waving" for s in sprites.pet_states(self.pet)):
            return "waving"
        if self.phys["mode"] == "walk" and self.phys["vx"] != 0:
            if self.phys["vx"] < 0 and any(s["id"] == "running-left" for s in sprites.pet_states(self.pet)):
                return "running-left"
            if any(s["id"] == "running-right" for s in sprites.pet_states(self.pet)):
                return "running-right"
        if our == "busy" and self.sessions:
            d = self.sessions[0].get("direction")
            if d == "left" and any(s["id"] == "running-left" for s in sprites.pet_states(self.pet)):
                return "running-left"
            if d == "right" and any(s["id"] == "running-right" for s in sprites.pet_states(self.pet)):
                return "running-right"
        return m.get(our) or "idle"

    def _phys(self, dtms):
        s = min(dtms, PHYS_STEP_CLAMP_MS) / PHYS_TICK_MS
        left, top, right, bottom = self.area
        w = self.pet["frameW"] * self.pet["scale"]
        h = self.pet["frameH"] * self.pet["scale"]
        floor = bottom - h
        p = self.phys
        if not p["grounded"]:
            p["vy"] += PHYS_GRAVITY * s
            p["y"] += p["vy"] * s
            if p["y"] >= floor:
                p["y"] = floor
                if p["vy"] > PHYS_BOUNCE_VY:
                    p["vy"] = -p["vy"] * PHYS_BOUNCE
                else:
                    p["vy"] = 0
                    p["grounded"] = True
        else:
            # Only snap to floor if not drag-pinned. A drag drop should stay
            # where the user placed it (free vertical positioning).
            if not p.get("pinned_y"):
                p["y"] = floor
        if p["y"] < top:
            p["y"] = top
            if p["vy"] < 0:
                p["vy"] = 0
        if p["mode"] == "walk":
            p["x"] += p["vx"] * s
        if p["x"] <= left:
            p["x"] = left
            p["vx"] = abs(p["vx"])
            if p["grounded"]:
                p["vy"] = -PHYS_WALL_JUMP_VY
                p["grounded"] = False
        if p["x"] >= right - w:
            p["x"] = right - w
            p["vx"] = -abs(p["vx"])
            if p["grounded"]:
                p["vy"] = -PHYS_WALL_JUMP_VY
                p["grounded"] = False
        p["t"] += dtms
        if p["grounded"] and p["mode"] == "idle" and p["t"] > self.roam_after_ms:
            p["t"] = 0
            # Only a pet that is actively engaged (working/thinking, or any
            # foreground activity) prowls around. When the screen has been idle
            # the pet stays put — no random roaming while it is resting.
            working = self._state() in ("busy", "thinking") or self.os_active
            chance = (WALK_CHANCE_ACTIVE if working else 0.0) * self.walk_factor
            if random.random() < chance:
                p["mode"] = "walk"
                p["vx"] = (1 if random.random() < 0.5 else -1) * (WALK_SPEED_MIN + random.random() * WALK_SPEED_RANGE)
                p["walkT"] = 0
                self.roam_after_ms = ROAM_MIN_MS + random.random() * ROAM_RANGE_MS
            else:
                self.roam_after_ms = REST_MIN_MS + random.random() * REST_RANGE_MS
        if p["mode"] == "walk":
            p["walkT"] += dtms
            if p["grounded"] and p["walkT"] > WALK_MIN_MS + random.random() * WALK_RANGE_MS:
                p["mode"] = "idle"
                p["vx"] = 0
                p["t"] = 0
                self.roam_after_ms = REST_AFTER_WALK_MIN_MS + random.random() * REST_AFTER_WALK_RANGE_MS

    def _compose(self):
        w = self.pet["frameW"] * self.pet["scale"]
        h = self.pet["frameH"] * self.pet["scale"]
        canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        # status dot: small glanceable indicator in the top-right corner.
        # Colour = what your AI tools / terminal are doing.
        saura = self._state_aura()
        if saura:
            canvas.alpha_composite(saura, (w - saura.width, 0))
        # P5: chrono-gene aura behind the pet (visual overlay, no new art)
        cglow = self._chrono_glow()
        if cglow:
            canvas.alpha_composite(cglow)
        # P6: embodied day-state aura on top — the pet LOOKS like your day
        eglow = self._embody_glow()
        if eglow:
            canvas.alpha_composite(eglow)
        # P7: attention-barter radiance — glow tier per traded form stage
        bglow = self._barter_glow()
        if bglow:
            canvas.alpha_composite(bglow)
        if self.sheet:
            st = sprites.pet_states(self.pet)
            anim = next((a for a in st if a["id"] == self._anim_id()), st[0])
            if anim["id"] != self.anim["id"]:
                self.anim = anim
                self.frame_idx = 0
                self.acc = 0
            frame = self._frame_cache.get((self.anim["id"], self.frame_idx))
            if frame:
                canvas.alpha_composite(frame)
        # focus-completion cast flash (independent event; self-expiring)
        if self.cast:
            if time.time() < self.cast["until"]:
                canvas = self._draw_cast(canvas, min(1.0, (time.time() - self.cast["started"]) / CAST_DURATION_SECS))
            else:
                self.cast = None
        # bubble above the pet's head
        if self.bubble_text and time.time() < self.bubble_until:
            canvas = self._draw_bubble(canvas, self.bubble_text)
        return canvas

    def _draw_cast(self, canvas, t):
        """Brief, celebratory energy burst behind the pet on focus completion.
        Pure additive overlay; the caller clears the event once it expires."""
        w, h = canvas.size
        cx, cy = w * 0.5, h * 0.56
        ring = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(ring)
        a = int((1 - t) * 165)
        lw = max(2, int((1 - t) * 7))
        for i, col in enumerate([(246, 179, 92, a), (255, 122, 106, max(0, a - 70))]):
            rr = int((8 + t * (w * 0.55)) + i * 6)
            d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], outline=col, width=lw)
        for k in range(6):
            ang = k * (2 * math.pi / 6) + t * 1.6
            rr = int((8 + t * (w * 0.55)) * (0.8 + 0.25 * t))
            ex = int(cx + math.cos(ang) * rr * 1.1)
            ey = int(cy - (h * 0.18) * t - math.sin(ang) * rr * 0.35)
            ea = max(0, 215 - int(t * 200))
            d.ellipse([ex - 2, ey - 2, ex + 2, ey + 2], fill=(255, 209, 137, ea))
        canvas.alpha_composite(ring)
        return canvas

    def _font_cache(self):
        """truetype() is the single most expensive call in _draw_bubble; load once."""
        if getattr(self, "_font", None) is None:
            try:
                self._font = ImageFont.truetype("segoeui.ttf", 14)
            except Exception:
                self._font = ImageFont.load_default()
        return self._font

    @staticmethod
    def _fit_text(text, font, avail):
        """Truncate a label with an ellipsis so it fits `avail` pixels.

        Binary search on the visible length: font.getlength() costs ~50us, so
        the naive linear walk is O(n) calls and dominates _draw_bubble on long
        labels (measured ~15ms/frame with a 200-char label). Binary search
        cuts that to O(log n) calls (~8).
        """
        if not text:
            return ""
        if font.getlength(text) <= avail:
            return text
        lo, hi = 0, len(text)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if font.getlength(text[:mid] + "\u2026") <= avail:
                lo = mid
            else:
                hi = mid - 1
        return (text[:lo] + "\u2026") if lo else text[:1]

    def _draw_bubble(self, canvas, text):
        w = canvas.width
        pad = BUBBLE_PAD
        font = self._font_cache()
        # truncate with ellipsis so the label never overflows the canvas
        avail = max(16, w - BUBBLE_MARGIN - pad * 2)
        text = self._fit_text(text, font, avail)
        tw = font.getlength(text)
        bw = min(tw + pad * 2, w - BUBBLE_MARGIN)
        bh = BUBBLE_HEIGHT
        bx = max(0, (w - bw) // 2)
        by = max(0, BUBBLE_TOP)
        d = ImageDraw.Draw(canvas)
        d.rounded_rectangle((bx, by, bx + bw, by + bh), radius=BUBBLE_RADIUS, fill=(255, 255, 255, 245))
        d.polygon([(bx + bw // 2 - BUBBLE_TAIL_HALF, by + bh), (bx + bw // 2 + BUBBLE_TAIL_HALF, by + bh),
                   (bx + bw // 2, by + bh + BUBBLE_TAIL_HEIGHT)], fill=(255, 255, 255, 245))
        d.text((bx + pad, by + 3), text, font=font, fill=(30, 30, 46, 255))
        return canvas

    def loop(self):
        if not self.phys["spawned"]:
            self._spawn()
        self._frame_advance()
        self._present()

    def _spawn(self):
        self.phys["spawned"] = True
        left, top, right, bottom = self.area
        w = self.pet["frameW"] * self.pet["scale"]
        self.phys["x"] = (left + right) / 2 - w / 2
        self.phys["y"] = bottom - self.pet["frameH"] * self.pet["scale"]

    def _frame_advance(self):
        dt = self.TICK * 1000
        if not self.dragging:
            self._phys(dt)
        self._log_activity()
        self.acc += dt
        per = self.anim["durationMs"] / max(1, self.anim["frames"])
        if per > 0:
            while self.acc >= per:
                self.acc -= per
                self.frame_idx = (self.frame_idx + 1) % max(1, self.anim["frames"])

    def _present(self):
        # dirty-flag: full UpdateLayeredWindow only when CONTENT changed;
        # position-only changes move the cheap SetWindowPos way.
        px, py = int(round(self.phys["x"])), int(round(self.phys["y"]))
        bubble_on = bool(self.bubble_text and time.time() < self.bubble_until)
        content = (self.anim["id"], self.frame_idx, bubble_on, self.bubble_text)
        if self.dragging:
            return  # manual drag owns the window position until release
        if content != self._last_content:
            self._last_content = content
            self._last_pos = (px, py)
            img = self._compose()
            self.win.render(img, px, py)
        elif (px, py) != self._last_pos:
            self._last_pos = (px, py)
            self.win.move(px, py)

    # personality reactions keyed on state transitions (error -> empathy,
    # completion after work -> cheer). Local only; keeps the pet alive.
    REACTIONS = {
        "error": [
            "Ouch — that one stung. Want me to watch the retry? 👁",
            "Exit %d — rough. I'll stay by your side. 💙",
            "Bounced hard. I'm right here.",
            "That one blipped — I've got you.",
        ],
        "success": [
            "Nice! Done. ✨",
            "Look at you go — nailed it! 🎉",
            "Clean exit. That's how it's done.",
            "Smooth. Another win.",
        ],
    }

    # Personality bubbles keyed on state — richer than REACTIONS because they
    # run on every transition (not just first-seen), with a 6s decay window
    # so the same line doesn't re-fire every tick while the state persists.
    BUBBLES = {
        "thinking": [
            "Hmm… thinking about it 🤔",
            "Processing… patience ✨",
            "Reasoning through this…",
            "Connecting the dots 🔮",
            "Almost there…",
            "Pondering…",
        ],
        "busy": [
            "On it 🔧",
            "Working the gears",
            "In the flow",
            "Making moves",
        ],
        "waiting": [
            "Waiting on you…",
            "Still here whenever you are",
            "Standing by 👀",
            "Whenever you're ready",
            "Not going anywhere",
        ],
        "error": [
            "That one hurt 😣",
            "Oof — rough exit",
            "Hang on, retry? 💪",
            "Tough one. I'm still here.",
        ],
        "success": [
            "Nice — done! 🎉",
            "Crisp. Nailed it ✨",
            "Another one in the bag",
            "Smooth. Another win.",
            "Look at that — clean.",
        ],
        "idle": [
            "Just vibing 😌",
            "Chilling for now",
            "All quiet on my end",
            "Ready when you are",
        ],
        "failed": [
            "That one hurt 😣",
            "Oof — rough exit",
            "Hang on, retry? 💪",
        ],
    }

    def update_sessions(self, sessions):
        # BUG-3: preserve the last-known emotion whenever the top (most recent)
        # session goes stale or disappears, so a timed-out session keeps showing
        # its real emotion (failed/thinking/...) instead of collapsing to
        # busy/waiting. A new fresh session clears the preserved emotion.
        prev_top = self.sessions[0] if self.sessions else None
        new_top = sessions[0] if sessions else None
        prev_fresh = prev_top is not None and not prev_top.get("stale")
        new_fresh = new_top is not None and not new_top.get("stale")
        if prev_fresh and not new_fresh:
            self._stale_emotion = prev_top.get("state")
        elif new_fresh:
            self._stale_emotion = None
        self.sessions = sessions
        # personality + growth on real transitions of the top session
        if new_top and new_fresh:
            st = new_top.get("state")
            tool = new_top.get("toolLabel") or ""
            if st == "error" and (not prev_top or prev_top.get("state") != "error"):
                line = random.choice(self.REACTIONS["error"])
                self.bubble_text = line
                self.bubble_until = time.time() + 5
            elif st == "success" and prev_top and prev_top.get("state") == "busy":
                self.bubble_text = random.choice(self.REACTIONS["success"])
                self.bubble_until = time.time() + 4
                self._award_xp(XP_COMPLETE_BONUS, "complete")
            elif st == "busy" and tool:
                self._earn_tool_xp(tool)

    def config_watch(self):
        """Apply config + one-shot commands written by the control app (separate process)."""
        try:
            with open(store.CONFIG_FILE, encoding="utf-8") as fh:
                c = json.load(fh)
        except Exception:
            return
        if c.get("quit"):
            try:
                self._clear_command("quit")
            except Exception:
                pass
            os._exit(0)
        changed = False
        if isinstance(c.get("petIdx"), int) and c["petIdx"] % len(sprites.PETS) != self.cfg["petIdx"] % len(sprites.PETS):
            self.set_pet(c["petIdx"])
            changed = True
        if isinstance(c.get("walk"), int) and c["walk"] != self.cfg.get("walk"):
            self.set_walk(c["walk"])
            self.cfg["walk"] = c["walk"]
            changed = True
        if isinstance(c.get("breakMin"), int):
            self.break_min = max(0, int(c["breakMin"]))
            self.cfg["breakMin"] = self.break_min
        if isinstance(c.get("stretchMin"), int):
            self.stretch_min = max(0, int(c["stretchMin"]))
            self.cfg["stretchMin"] = self.stretch_min
        if c.get("chimes") is not None:
            self.chimes_on = bool(c["chimes"])
            self.cfg["chimes"] = self.chimes_on
        if c.get("breakSnooze") is not None:
            # one-shot command: arm the next break nudge to snooze, then delete
            # the key so it can't re-trigger every poll cycle
            try:
                self._snooze_min = max(1, int(c["breakSnooze"]))
            except (TypeError, ValueError):
                self._snooze_min = SNOOZE_DEFAULT_MIN
            try:
                self._clear_command("breakSnooze")
            except Exception:
                pass
        if isinstance(c.get("goalMin"), int):
            self.goal_min = store.goal_minutes(c)
        if c.get("alwaysOnTop") is not None and bool(c["alwaysOnTop"]) != bool(self.cfg.get("alwaysOnTop", True)):
            self.set_topmost(bool(c["alwaysOnTop"]))
            self.cfg["alwaysOnTop"] = bool(c["alwaysOnTop"])
            changed = True
        if c.get("hidePet"):
            self.set_visible(False)
            self._clear_command("hidePet")
        if c.get("showPet"):
            self.set_visible(True)
            self._clear_command("showPet")
        if c.get("focusStart") is not None:
            mins = int(c["focusStart"]) if isinstance(c["focusStart"], (int, float)) else None
            try:
                self.start_focus(mins)
            finally:
                # clear even on failure so a bad command can't retrigger
                # every poll cycle
                self._clear_command("focusStart")
        if c.get("focusStop"):
            try:
                self.stop_focus()
            finally:
                self._clear_command("focusStop")
        if c.get("barterPay"):
            # P7: one-shot attention-barter confirmation from the dashboard
            try:
                self._barter_pay()
            finally:
                # clear even on failure so a bad command can't retrigger
                self._clear_command("barterPay")
        if changed:
            store.save_config(self.cfg)

    @staticmethod
    def _clear_command(key):
        try:
            with store._config_lock() as fd:
                if fd is None:
                    return
                c = store._read_locked_fd(fd)
                if not isinstance(c, dict):
                    return
                c.pop(key, None)
                store._write_locked_fd(fd, c)
        except Exception:
            pass

    def update_activity(self):
        now = time.time()
        if now - self._last_act < 0.5:
            return  # foreground_app() is expensive; throttle to 2 Hz
        self._last_act = now
        # Interop through the desktop.main namespace (not a direct import):
        # the test suite monkeypatches main.last_input_ms/foreground_app, so
        # the lookup must happen here at call time.
        from desktop import main as _app
        self.os_active = _app.last_input_ms() < store.ACTIVE_MS
        self.os_app = _app.foreground_app()
        self._update_bubble(now)
        self._break_nudge(now)
        self._stretch_nudge(now)
        # focus session lifecycle (grow / wilt / complete) + mood + tool XP
        self._focus_tick()
        if self.os_active:
            self._mood_tick()
        self._track_app_time()
        # daily focus goal runs last so its bubble wins over tool/state lines
        self._goal_tick()
        # P4: wake ritual (dream + long-idle greeting), episodic recall, and
        # epoch crossings run AFTER goal so the substantive moments win the
        # bubble over tool/state lines.
        self._wake_tick(now)
        self._memory_tick(now)
        self._epoch_tick(now)
        # P5: chronotype metamorphosis + weekly drift (once per day; cheap)
        self._chrono_tick(now)
        # P6: day-body (30s cadence; goal/focus events force an earlier pass)
        self._embody_tick(now)
        # P7: personal rituals + attention barter (daily derive + live progress)
        self._ritual_tick(now)
        self._barter_tick(now)

    def _update_bubble(self, now):
        if now >= self.bubble_until:
            self.bubble_text = ""
        st = self.sessions[0] if self.sessions else None
        fresh = st and not st.get("stale")
        state = st.get("state") if fresh else None
        tool = (st.get("toolLabel") or "").strip() if (fresh and state == "busy") else ""

        # 1. Tool-use line (busy + tool): the most useful real-time cue.
        if tool:
            friendly = {
                "bash": "Running a shell command",
                "grep": "Searching the codebase",
                "glob": "Finding files",
                "read": "Reading a file",
                "write": "Writing a file",
                "edit": "Editing a file",
            }
            base = tool.split(" ")[0].lower()
            label = friendly.get(base, tool)
            if base in friendly and len(tool.split(" ")) <= 1:
                self.bubble_text = label
            else:
                self.bubble_text = tool
            self.bubble_until = now + TOOL_BUBBLE_SECS
        # 2. Personality lines keyed on state transitions.
        elif state in self.BUBBLES:
            line = self._personality(state, now=now)
            if line:
                self.bubble_text = line
                self.bubble_until = now + PERSONALITY_BUBBLE_SECS
        # 3. No active sessions, OS is active → show foreground app.
        elif not fresh and self.os_active and self.os_app and self.os_app not in ("Explorer", "Program Manager", ""):
            self.bubble_text = "In " + self.os_app
            self.bubble_until = now + APP_BUBBLE_SECS
        # 4. Nothing to say.
        elif not self.os_active and not fresh:
            self.bubble_text = ""
            self.bubble_until = 0

    def _personality(self, state_key, ttl=6, now=None):
        """Pick a personality line with decay suppression so we don't re-fire
        the same line every tick while a state persists."""
        last = getattr(self, "_last_bubble_state", None)
        last_at = getattr(self, "_last_bubble_state_at", 0)
        if state_key == last and now - last_at < ttl:
            return None
        lines = self.BUBBLES.get(state_key) or []
        if not lines:
            return None
        line = random.choice(lines)
        self._last_bubble_state = state_key
        self._last_bubble_state_at = now
        return line

    def _break_nudge(self, now):
        # focus streak -> break nudge (distraction tracker). Runs LAST so the
        # nudge wins over any tool/app bubble for its 5s.
        if self.os_active:
            if self.break_track_start is None:
                self.break_track_start = now
            elif self.break_min > 0 and not self._break_shown \
                    and now - self.break_track_start >= self.break_min * 60 \
                    and now - self._last_break > BREAK_COOLDOWN_SECS:
                snooze = self._snooze_min
                if snooze > 0:
                    # one-shot snooze: replace the nudge with a deferral, then
                    # re-arm the streak clock so the nudge re-fires in N min
                    self._snooze_min = 0
                    self._last_break = now
                    self._stretch_start = now
                    self.break_track_start = now + snooze * 60 - self.break_min * 60
                    self.bubble_text = "Snoozed %d min \u2014 see you at %s" % (
                        snooze, time.strftime("%H:%M", time.localtime(now + snooze * 60)))
                    self.bubble_until = now + BREAK_NUDGE_SECS
                    self._log("breakSnooze", mins=snooze)
                    self._chime("break")
                    return
                self._break_shown = True
                self._last_break = now
                self._stretch_start = now
                mins = int((now - self.break_track_start) / 60)
                self.bubble_text = "Time for a break \u2014 stretch!"
                self.bubble_until = now + BREAK_NUDGE_SECS
                self.attention_until = now + FOCUS_ATTENTION_SECS
                self._log("break", mins=mins)
                self.mood = "tired"
                self._chime("break")
        else:
            self.break_track_start = None
            self._break_shown = False
            self._stretch_start = None
            self.bubble_text = ""
            self.bubble_until = 0

    def _stretch_nudge(self, now):
        """Continuous-work stretch reminder: fires once per stretchMin of
        unbroken work (idle resets the clock, break bubbles count as rest)."""
        if not self.os_active:
            self._stretch_start = None
            return
        if self.stretch_min <= 0:
            return
        if self._stretch_start is None:
            self._stretch_start = now
            return
        if now - self._last_stretch < STRETCH_COOLDOWN_SECS:
            return
        since = now - max(self._stretch_start, self._last_break)
        if since >= self.stretch_min * 60:
            self._stretch_start = now
            self._last_stretch = now
            self.bubble_text = "Stretch! Neck + shoulders \U0001f9d8"
            self.bubble_until = now + BREAK_NUDGE_SECS
            self._award_xp(XP_STRETCH, "stretch")
            self._log("stretch", mins=int(since / 60))
            self._chime("stretch")

    # ------------------------------------------------------- wake ritual + dream
    def _try_dream(self, now):
        """First wake of a new day: bubble the dream journal digest of
        yesterday. Once per day, guarded by the wakeDate config key (survives
        restarts). No data yet -> stay quiet and retry on the next wake."""
        today = time.strftime("%Y-%m-%d")
        if str(self.cfg.get("wakeDate") or "") == today:
            return
        d = store.read_wellbeing()
        dream = store.build_dream(d) if isinstance(d, dict) else ""
        if not dream:
            return
        self.cfg["wakeDate"] = today
        try:
            c = store.load_config()
            c["wakeDate"] = today
            store.save_config(c)
        except Exception:
            pass
        self.bubble_text = dream
        self.bubble_until = now + WAKE_BUBBLE_SECS
        self.attention_until = now + FOCUS_ATTENTION_SECS
        self._log("dream")

    def _wake_tick(self, now):
        """Wake moments: process start of a new day (dream) and the first
        non-idle after a long idle (greeting, 4h cooldown)."""
        if self._first_tick:
            self._first_tick = False
            if self.os_active:
                self._try_dream(now)
                self._was_active = True
                return
        if self.os_active and not self._was_active:
            idle_secs = now - self._idle_since
            if idle_secs > store.SLEEP_GAP_SECS \
                    and now - self._last_idle_wake >= store.WAKE_COOLDOWN_SECS:
                self._last_idle_wake = now
                try:
                    c = store.load_config()
                    c["wakeIdleAt"] = now
                    store.save_config(c)
                except Exception:
                    pass
                self.bubble_text = random.choice(WAKE_LINES)
                self.bubble_until = now + WAKE_BUBBLE_SECS
                self._log("wake", idleSecs=int(idle_secs))
            self._try_dream(now)
        elif not self.os_active and self._was_active:
            self._idle_since = now
        self._was_active = self.os_active

    # ------------------------------------------------------- episodic memory
    def _read_memory_events(self, limit=200):
        """Last N events from THIS pet's activity log (one pet, one memory)."""
        try:
            with open(os.path.join(store.PET_DIR, "activity-%s.jsonl" % self.pet["id"]),
                      encoding="utf-8") as fh:
                lines = fh.readlines()
            out = []
            for line in lines[-limit:]:
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
            return out
        except Exception:
            return []

    def _memory_line(self):
        """Pick one recall with REAL numbers from the activity log. Template
        priority is deterministic: streak record, longest session, pet
        switches, first session of the day, weekly session count, fallback."""
        events = self._read_memory_events()
        now = time.time()
        today = time.strftime("%Y-%m-%d")
        focus_done = [e for e in events if e.get("kind") == "focusDone"]
        # 1. streak milestone: "never done before" vs "matches your best"
        cur = self._streak_days()
        if cur >= 3:
            cutoff = (datetime.date.today() - datetime.timedelta(days=cur)).isoformat()
            before = {d: v for d, v in self._history.items() if d < cutoff}
            best_prev = store.best_streak(before)
            if cur > best_prev:
                return ("%d days in a row \u2014 never done before." % cur, "streak_record")
            if cur == best_prev:
                return ("%d days in a row \u2014 matches your best run." % cur, "streak_match")
        # 2. session length record
        if focus_done:
            longest = max(focus_done, key=lambda e: float(e.get("minutes", 0) or 0))
            mins = int(longest.get("minutes", 0) or 0)
            if mins >= 25:
                day = time.strftime("%b %d", time.localtime(longest.get("t", now)))
                return ("Longest session: %d min, %s." % (mins, day), "session_record")
        # 3. pet-switch memory (real user reality: high switch frequency)
        switches = [e for e in events if e.get("kind") == "petSwitch"]
        if len(switches) >= 2:
            day = time.strftime("%b %d", time.localtime(switches[0].get("t", now)))
            same = all(time.strftime("%Y-%m-%d", time.localtime(s.get("t", now))) ==
                       time.strftime("%Y-%m-%d", time.localtime(switches[0].get("t", now)))
                       for s in switches)
            when = "on %s" % day if same else "recently"
            return ("You swapped pets %d times %s." % (len(switches), when), "pet_switch")
        # 4. first session of the day
        starts = [e for e in events if e.get("kind") == "focusStart"
                  and time.strftime("%Y-%m-%d", time.localtime(e.get("t", now))) == today]
        if starts:
            first = min(starts, key=lambda e: e.get("t", now))
            hm = time.strftime("%H:%M", time.localtime(first.get("t", now)))
            return ("First focus today at %s \u2014 a fresh start." % hm, "first_of_day")
        # 5. recent-focused-session count
        done_week = [e for e in focus_done if now - (e.get("t") or 0) < store.WEEK_SECS]
        if len(done_week) >= 2:
            return ("%d focus sessions in the last 7 days." % len(done_week), "session_count")
        # 6. fallback
        if len(events) >= 5:
            return ("I remember %d moments with you \u2014 busy day." % len(events), "busy_day")
        return ("I remember this week. The quiet ones count too.", "quiet_week")

    def _memory_tick(self, now):
        """Episodic recall: after memoryMin minutes of WORK time (jittered),
        bubble a real past event. No XP — a bubble and a brief mood shimmer
        only. Max memoryMax recalls per day (config-guarded daily counter)."""
        if not self.os_active:
            return
        if self._memory_work < self._next_memory_work:
            return
        c = store.load_config()
        today = time.strftime("%Y-%m-%d")
        if c.get("memoryDate") != today:
            count = 0
        else:
            count = int(c.get("memoryCount", 0) or 0)
        if count >= self.memory_max:
            self._memory_work = 0.0  # budget spent for today; stop accumulating
            return
        line, tpl = self._memory_line()
        if not line:
            return
        self._memory_work = 0.0
        self._next_memory_work = self.memory_min * 60 * random.uniform(0.75, 1.25)
        try:
            c2 = store.load_config()
            c2["memoryCount"] = count + 1
            c2["memoryDate"] = today
            store.save_config(c2)
        except Exception:
            pass
        self.cfg["memoryCount"] = count + 1
        self.cfg["memoryDate"] = today
        self.bubble_text = line
        self.bubble_until = now + MEMORY_BUBBLE_SECS
        self._log("memory", template=tpl)
        # mood shimmer (aura) instead of XP: brief happy, then restore
        self._shimmer_mood = self.mood
        self.mood = "happy"
        self._shimmer_until = now + MEMORY_SHIMMER_SECS

    def _focus_count(self):
        """All-time completed focus sessions for THIS pet (cached 60s — the
        log read is the only slightly-pricey part of the epoch check)."""
        now = time.time()
        if now - self._last_fc_read < 60:
            return self._focus_count_cache
        self._last_fc_read = now
        n = 0
        try:
            with open(os.path.join(store.PET_DIR, "activity-%s.jsonl" % self.pet["id"]),
                      encoding="utf-8") as fh:
                for line in fh:
                    try:
                        if json.loads(line).get("kind") == "focusDone":
                            n += 1
                    except Exception:
                        continue
        except Exception:
            pass
        self._focus_count_cache = n
        return n

    def _epoch_tick(self, now):
        """Life-transition markers: when a pure threshold in the data crosses,
        celebrate ONCE (25 XP — these ARE earned, not spam) and record the
        epoch id in config so it can never re-fire."""
        flags = list(self.cfg.get("epochFlags") or [])
        crossed = store.evaluate_epochs(self._history, self._hour_history,
                                        self.cfg, self.xp, self._focus_count())
        if not crossed:
            return
        eid, name, desc = crossed[0]
        flags.append(eid)
        self.cfg["epochFlags"] = flags
        try:
            c = store.load_config()
            c["epochFlags"] = flags
            store.save_config(c)
        except Exception:
            pass
        self._award_xp(XP_EPOCH, "epoch")
        self.mood = "happy"
        self.bubble_text = "%s \u2014 %s" % (name, desc)
        self.bubble_until = now + EPOCH_BUBBLE_SECS
        self.attention_until = now + FOCUS_ATTENTION_SECS
        self._log("epoch", id=eid, name=name)

    # ------------------------------------------------------- chronotype (P5)
    def _save_chrono(self):
        try:
            c = store.load_config()
            c["chronoType"] = self.chrono_type
            c["chronoDate"] = self.chrono_date
            c["chronoWeekDate"] = self.chrono_week_date
            store.save_config(c)
        except Exception:
            pass

    def _chrono_review_due(self, today):
        if not self.chrono_week_date:
            return True
        try:
            last = datetime.date.fromisoformat(self.chrono_week_date)
        except ValueError:
            return True
        return (datetime.date.today() - last).days >= store.CHRONO_REVIEW_DAYS

    def _chrono_tick(self, now):
        """P5 metamorphosis + weekly drift. Evaluates the hour fingerprint
        once per day; the chronoDate/chronoWeekDate config guards make the
        metamorph (one-time) and the drift (max one per week) both idempotent.
        The scan is cheap (<=30 days x 24 hours) but the once-per-day gate
        keeps it off the 2Hz tick path anyway."""
        today = time.strftime("%Y-%m-%d")
        if getattr(self, "_chrono_checked", "") == today:
            return
        self._chrono_checked = today
        profile = store.chronotype_profile(self._hour_history)
        if self.chrono_type == "larval":
            if profile["days"] < store.CHRONO_MIN_DAYS:
                return
            self._metamorph(store.chronotype_class(profile), profile, now)
            return
        if self._chrono_review_due(today):
            self._chrono_review(profile, now)

    def _metamorph(self, cls, profile, now):
        """Larva -> chrono gene: the pet's species becomes the user's REAL
        schedule. One-time (chronoDate guard), 50 XP, cast flash, log."""
        self.chrono_type = cls
        self.chrono_date = time.strftime("%Y-%m-%d")
        self.chrono_week_date = time.strftime("%Y-%m-%d")  # first review in 7 days
        self._save_chrono()
        genes = store.gene_manifest(cls, profile)
        self._award_xp(XP_METAMORPH, "metamorph")
        self.mood = "happy"
        self.bubble_text = store.chrono_readout(cls, profile)
        self.bubble_until = now + CHRONO_BUBBLE_SECS
        self.attention_until = now + FOCUS_ATTENTION_SECS
        self.cast = {"until": now + FOCUS_CAST_SECS, "started": now}
        self._log("metamorph", to=cls, species=genes["species"], genes=genes)
        self._chime("complete")

    def _chrono_review(self, profile, now):
        """Weekly fingerprint re-read. chronoWeekDate advances every review;
        a class change fires a drift event (bubble + log + new aura) — at
        most one per week because the next review is a week away."""
        cls = store.chronotype_class(profile)
        prev = self.chrono_type
        self.chrono_week_date = time.strftime("%Y-%m-%d")
        if cls != prev and cls != "larval":
            self.chrono_type = cls
            self._save_chrono()
            self.bubble_text = "My genes are drifting\u2026"
            self.bubble_until = now + CHRONO_BUBBLE_SECS
            self.attention_until = now + FOCUS_ATTENTION_SECS
            self._log("drift", to=cls, fromType=prev)
        else:
            self._save_chrono()  # review happened, nothing drifted

    def _chrono_glow(self):
        """Radial aura behind the pet for the active chrono gene — visual
        overlay only, the sprite sheet never changes. Dormant outside the
        gene's hour window (night owl glows 0-6h, lark at dawn, ...)."""
        try:
            col = store.chrono_aura(self.chrono_type,
                                    hour=time.localtime().tm_hour,
                                    day_of_year=datetime.date.today().timetuple().tm_yday)
            if not col:
                return None
            cache = getattr(self, "_chrono_glow_cache", None)
            if cache is None:
                self._chrono_glow_cache = cache = {}
            key = col
            glow = cache.get(key)
            if glow is None:
                w = max(8, int(self.pet["frameW"] * self.pet["scale"]))
                h = max(8, int(self.pet["frameH"] * self.pet["scale"]))
                glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
                dr = ImageDraw.Draw(glow)
                cx, cy = w // 2, int(h * 0.52)
                r = max(6, int(min(w, h) * 0.42))
                for rr in range(r, 0, -2):
                    a = int(col[3] * (1 - rr / r) ** 2)
                    if a <= 0:
                        continue
                    dr.ellipse((cx - rr, cy - rr, cx + rr, cy + rr),
                               fill=(col[0], col[1], col[2], a))
                self._chrono_glow_cache[key] = glow
            return glow
        except Exception:
            return None

    # ------------------------------------------------------- day-body (P6)
    def _errors_today(self, now=None):
        """Count today's error/retry transitions from THIS pet's activity log.
        The engine logs one 'state' line per transition, so each line is one
        error cluster."""
        today = time.strftime("%Y-%m-%d", time.localtime(now or time.time()))
        n = 0
        try:
            with open(os.path.join(store.PET_DIR, "activity-%s.jsonl" % self.pet["id"]),
                      encoding="utf-8") as fh:
                for line in fh:
                    try:
                        e = json.loads(line)
                    except Exception:
                        continue
                    if e.get("kind") == "state" and e.get("state") in ("error", "retry") \
                            and time.strftime("%Y-%m-%d",
                                              time.localtime(e.get("t", 0))) == today:
                        n += 1
        except Exception:
            pass
        return n

    def _embody_tick(self, now, force=False):
        """Re-derive the embodied day state (every 30s, plus force on
        goal/focus events) and apply the visual overlay — aura colour/glow
        + a bubble-less mood hint. No sprite changes: the pet LOOKS like the
        day through the aura surface only."""
        if not force and now - getattr(self, "_last_embody", 0.0) < EMBODY_TICK_SECS:
            return
        self._last_embody = now
        errors = self._errors_today(now)
        focus = {"active": bool(getattr(self, "focus_active", False)),
                 "elapsed": (now - float(getattr(self, "focus_started", now) or now))
                            if getattr(self, "focus_active", False) else 0.0,
                 "wilted": bool(getattr(self, "focus_wilted", False))}
        h = store.day_health({"date": getattr(self, "_wb_date", time.strftime("%Y-%m-%d")),
                              "apps": getattr(self, "_wb", {}) or {},
                              "hourToday": getattr(self, "_hour_today", {}) or {}},
                             errors=errors, focus=focus, goal_min=self.goal_min, now=now)
        if h["state"] != self._embody_state:
            self._embody_state = h["state"]
            self._embody_since = now
            self._embody_glow_cache.clear()
            self._log("embody", state=h["state"], intensity=round(h["intensity"], 2))
        self._embody_intensity = h["intensity"]
        self._embody_aura = store.EMBODY_AURA.get(h["state"])
        # bubble-less mood hint: a foggy day reads as tired (sticky like the
        # break-nudge tired, until the next mood-setting event)
        if h["state"] == "fog" and self.mood not in ("happy", "tired"):
            self.mood = "tired"
        # error static: one bubble per error cluster, max one per 10 min
        if h["state"] == "storm" and errors > 0 \
                and now - self._last_static_bubble >= STATIC_BUBBLE_SECS:
            self._last_static_bubble = now
            self.bubble_text = store.EMBODY_LABELS["storm_error"]
            self.bubble_until = now + FOCUS_BUBBLE_SECS
            self._log("static", errors=errors)

    def _embody_glow(self):
        """Soft radial aura for the embodied day state, alpha scaled by
        intensity. None when the state carries no extra aura (quiet/flow keep
        the chrono gene's glow)."""
        try:
            spec = getattr(self, "_embody_aura", None)
            if not spec:
                return None
            a = int(spec[3] * (0.35 + 0.65 * getattr(self, "_embody_intensity", 0.5)))
            if a <= 0:
                return None
            col = (spec[0], spec[1], spec[2], a)
            cache = getattr(self, "_embody_glow_cache", None)
            if cache is None:
                self._embody_glow_cache = cache = {}
            glow = cache.get(col)
            if glow is None:
                w = max(8, int(self.pet["frameW"] * self.pet["scale"]))
                h = max(8, int(self.pet["frameH"] * self.pet["scale"]))
                glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
                dr = ImageDraw.Draw(glow)
                cx, cy = w // 2, int(h * 0.52)
                r = max(6, int(min(w, h) * 0.42))
                for rr in range(r, 0, -2):
                    aa = int(a * (1 - rr / r) ** 2)
                    if aa <= 0:
                        continue
                    dr.ellipse((cx - rr, cy - rr, cx + rr, cy + rr),
                               fill=(spec[0], spec[1], spec[2], aa))
                cache[col] = glow
            return glow
        except Exception:
            return None

    # ------------------------------------------------------- rituals (P7)
    def _ritual_wellbeing(self):
        """The engine's live wellbeing shape — the same dict shape the
        dashboard reads from disk, so derive/progress can't disagree."""
        return {"date": self._wb_date, "apps": self._wb or {},
                "hourToday": getattr(self, "_hour_today", {}) or {},
                "history": getattr(self, "_history", {}) or {},
                "hourHistory": getattr(self, "_hour_history", {}) or {},
                "appHistory": getattr(self, "_app_history", {}) or {}}

    def _save_ritual_state(self):
        try:
            c = store.load_config()
            c["ritualDate"] = str(self.cfg.get("ritualDate", "") or "")
            c["ritualList"] = self._rituals
            c["ritualDone"] = sorted(self._ritual_done)
            c["ritualCloseDate"] = self._dayclose_date
            store.save_config(c)
        except Exception:
            pass

    def _ritual_tick(self, now):
        """Personal rituals: derive fresh each day (ritualDate guard, survives
        restarts), track live progress against REAL data, celebrate each
        completion once (+15 XP — earned, not spam), and close the day quietly
        at 22:00 with no punishment for what went unfinished."""
        today = time.strftime("%Y-%m-%d")
        if str(self.cfg.get("ritualDate") or "") != today:
            self._rituals = store.derive_rituals(
                self._ritual_wellbeing(), self._focus_count(), self.cfg)
            self._ritual_done = set()
            self.cfg["ritualDate"] = today
            self.cfg["ritualList"] = self._rituals
            self._save_ritual_state()
        if not self._rituals:
            return
        wb = self._ritual_wellbeing()
        # live progress + one celebration per tick (bubble wins)
        for r in self._rituals:
            if r.get("id") in self._ritual_done:
                continue
            p = store.ritual_progress(r, wb, self.cfg, now=now)
            r["current"] = p["current"]
            r["done"] = p["done"]
            if p["done"]:
                self._ritual_done.add(r["id"])
                self._save_ritual_state()
                self._award_xp(XP_RITUAL, "ritual")
                self.mood = "happy"
                self.bubble_text = "Ritual complete: %s" % r["name"]
                self.bubble_until = now + RITUAL_BUBBLE_SECS
                self.attention_until = now + FOCUS_ATTENTION_SECS
                self._log("ritual", id=r["id"], name=r["name"])
                break
        # quiet end-of-day close: only when the day's rituals exist, the hour
        # has passed 22:00, and at least one went unfinished. No XP, no chime.
        # Defers while a substantive bubble (dream/goal/celebration) is live —
        # a quiet line never interrupts a moment.
        if time.localtime(now).tm_hour >= 22 \
                and self._dayclose_date != today \
                and now >= self.attention_until \
                and any(not r.get("done") for r in self._rituals):
            self._dayclose_date = today
            self.cfg["ritualCloseDate"] = today
            self._save_ritual_state()
            self.bubble_text = "Tomorrow's a new day"
            self.bubble_until = now + RITUAL_BUBBLE_SECS
            self._log("dayclose",
                      pending=sum(1 for r in self._rituals if not r.get("done")))

    # ------------------------------------------------------- barter (P7)
    def _save_barter(self):
        try:
            c = store.load_config()
            c["barterBank"] = self._barter_bank
            c["barterStage"] = self._barter_stage
            c["barterOfferDate"] = self._barter_offer_date
            store.save_config(c)
        except Exception:
            pass
        self.cfg["barterBank"] = self._barter_bank
        self.cfg["barterStage"] = self._barter_stage
        self.cfg["barterOfferDate"] = self._barter_offer_date

    def _barter_pay(self):
        """Confirm the standing offer: deduct banked minutes, advance one form
        stage, celebrate (20 XP + ceremony). Returns False when the offer is
        not tradable yet — the dashboard only shows the button when it is."""
        offer = store.barter_next_offer(self._barter_stage)
        if not offer or self._barter_bank < offer["costMinutes"]:
            return False
        now = time.time()
        self._barter_bank -= offer["costMinutes"]
        self._barter_stage = offer["stage"]
        self._barter_offer_date = ""
        self._save_barter()
        self._award_xp(XP_BARTER, "barter")
        self.mood = "happy"
        self.bubble_text = "Shift complete: %s \u2728" % offer["name"]
        self.bubble_until = now + BARTER_BUBBLE_SECS
        self.attention_until = now + FOCUS_ATTENTION_SECS
        self.cast = {"until": now + FOCUS_CAST_SECS, "started": now}
        self._log("barter", stage=offer["stage"], cost=offer["costMinutes"],
                  name=offer["name"])
        return True

    def _barter_tick(self, now):
        """Attention barter: flush accrued seconds to the bank, run the offer
        lifecycle (ask when the bank covers the next stage, expire quietly
        after BARTER_EXPIRE_DAYS with the bank kept — no punishment), and
        shimmer the form aura periodically between stages."""
        acc = getattr(self, "_barter_acc", 0.0)
        if acc >= 60.0:
            whole = int(acc // 60.0)
            acc -= whole * 60.0
            self._barter_bank += whole
            self._save_barter()
        self._barter_acc = acc
        offer = store.barter_next_offer(self._barter_stage)
        if offer:
            today = time.strftime("%Y-%m-%d")
            od = self._barter_offer_date
            days = 0
            if od:
                try:
                    days = (datetime.date.today()
                            - datetime.date.fromisoformat(od)).days
                except (TypeError, ValueError):
                    days = store.BARTER_EXPIRE_DAYS
            if od and od != today and days >= store.BARTER_EXPIRE_DAYS:
                # the offer window closed quietly — bank kept, no punishment.
                # Marking today suppresses the re-ask until tomorrow.
                self._barter_offer_date = today
                self._save_barter()
            elif od != today and self._barter_bank >= offer["costMinutes"]:
                # ask (or re-offer after a quiet expiry): once per day
                self._barter_offer_date = today
                self._save_barter()
                self.bubble_text = ("I can shift form \u2014 trade %d "
                                    "focus-minutes?" % offer["costMinutes"])
                self.bubble_until = now + BARTER_BUBBLE_SECS
                self._log("barterAsk", stage=offer["stage"],
                          cost=offer["costMinutes"])
        # visual tier: periodic cast shimmer once a form stage is earned
        if self._barter_stage > 0 and not self.cast \
                and now - self._last_barter_shimmer >= BARTER_SHIMMER_SECS:
            self._last_barter_shimmer = now
            self.cast = {"until": now + 0.6, "started": now}

    def _barter_glow(self):
        """Attention-barter radiance: a warm glow whose size and alpha rise
        with each traded stage (0-4) — visual milestone only, no sprite."""
        try:
            stage = int(getattr(self, "_barter_stage", 0) or 0)
            if stage <= 0:
                return None
            cache = getattr(self, "_barter_glow_cache", None)
            if cache is None:
                self._barter_glow_cache = cache = {}
            glow = cache.get(stage)
            if glow is None:
                w = max(8, int(self.pet["frameW"] * self.pet["scale"]))
                h = max(8, int(self.pet["frameH"] * self.pet["scale"]))
                glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
                dr = ImageDraw.Draw(glow)
                cx, cy = w // 2, int(h * 0.52)
                a = min(255, 16 + stage * 24)
                r = max(6, int(min(w, h) * (0.42 + 0.05 * stage)))
                for rr in range(r, 0, -2):
                    aa = int(a * (1 - rr / r) ** 2)
                    if aa <= 0:
                        continue
                    dr.ellipse((cx - rr, cy - rr, cx + rr, cy + rr),
                               fill=(255, 214, 140, aa))
                cache[stage] = glow
            return glow
        except Exception:
            return None
