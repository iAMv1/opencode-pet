"""Data layer: file paths, config/status/wellbeing persistence, shared stats.

Everything reads the module globals at call time (never via `from .store
import X` copies in other modules) so tests can repoint the paths with
monkeypatch and --web --pet-dir can redirect them at runtime.
"""

import colorsys
import contextlib
import datetime
import json
import msvcrt
import os
import threading
import time

from . import win32

# ---------------------------------------------------------------- paths
PET_DIR = os.path.join(os.path.expanduser("~"), ".opencode", "pet")
CONFIG_FILE = os.path.join(PET_DIR, "config.json")
WELLBEING_FILE = os.path.join(PET_DIR, "wellbeing.json")
FOCUS_FILE = os.path.join(PET_DIR, "focus.json")

# ---------------------------------------------------------------- time windows
STALE_MS = 25000            # a status file this old counts as stale
ACTIVE_MS = 30000           # OS counts as idle after this much input silence
STATUS_PRUNE_MS = 300000    # status files older than 5 min are deleted
CONFIG_READ_RETRIES = 3
CONFIG_READ_RETRY_SLEEP = 0.01
WELLBEING_READ_RETRIES = 3
WELLBEING_READ_RETRY_SLEEP = 0.01
WELLBEING_SAVE_INTERVAL = 20.0   # seconds between wellbeing.json rewrites
SLEEP_GAP_SECS = 60              # a longer tick delta is a gap, not usage
HISTORY_WINDOW_DAYS = 30         # pruning window for stored history
HISTORY_MAX_DAYS = 90            # get_wellbeing_history clamp (heatmap)
PEAKS_MAX_DAYS = 30              # get_focus_peaks clamp
WEEK_SECS = 7 * 86400            # focus-session count window

# ---------------------------------------------------------------- activity log (P10)
# activity-<petid>.jsonl appends forever; cap it on size AND age so a month of
# events (well beyond any dashboard window) can't grow the file unboundedly.
ACTIVITY_MAX_BYTES = 512 * 1024   # prune once the file passes this
ACTIVITY_PRUNE_LINES = 2000       # keep the newest N lines on a prune
ACTIVITY_PRUNE_DAYS = 30          # events older than this are dropped
ACTIVITY_PRUNE_KEY = "pruneDate"  # config guard: at most one prune per day

# ---------------------------------------------------------------- focus rules
STREAK_MIN_SECS = 30 * 60        # default daily focus streak threshold
STREAK_LOOKBACK_DAYS = 400       # how far back a streak chain is examined
APP_MIN_SECS = 30                # floor for today's top-app lists
WEEK_APP_MIN_SECS = 60           # floor for weekly per-app lists
TOP_APPS_LIMIT = 8
EVOLVE_LEVEL_2 = 5
EVOLVE_LEVEL_3 = 10
GOAL_DEFAULT_MIN = 120

# ---------------------------------------------------------------- rituals (P7)
# Personal rituals derived from the user's OWN history — never canned quests.
RITUAL_MAX_DAILY = 3           # at most 3 rituals per day, in priority order
RITUAL_GUARD_MIN_SECS = 3600   # guard_hour fires only for a >= 1h avg best hour
RITUAL_BEAT_MIN_SECS = 3600    # beat_yesterday fires only when yesterday >= 1h
RITUAL_IDLE_RATIO = 0.30       # yesterday idle share above this -> break_the_idle
RITUAL_BREAK_TARGET_MIN = 120  # break_the_idle target: 2h active
RITUAL_NIGHT_TARGET_MIN = 60   # night_guard target: 1 deep hour after midnight
RITUAL_NIGHT_HOURS = (0, 6)    # night_guard window (inclusive)
RITUAL_LARK_HOURS = (5, 12)    # first_light window (inclusive)

# ---------------------------------------------------------------- barter (P7)
# Attention barter: metamorphosis stages are TRADED for real banked focus
# minutes — no currency abstraction. Each stage is one step of the visual
# form; stage N unlocks when barterStage == N-1 (barterStage = stages done).
BARTER_OFFERS = [
    {"stage": 1, "costMinutes": 300,  "name": "Perk up ears",
     "desc": "A hint of life returns to my ears \u2014 attention, felt."},
    {"stage": 2, "costMinutes": 600,  "name": "Grow whiskers",
     "desc": "Whiskers grow sharp \u2014 I can read your focus now."},
    {"stage": 3, "costMinutes": 900,  "name": "Shift coat",
     "desc": "My coat takes on the colours of your rhythm."},
    {"stage": 4, "costMinutes": 1500, "name": "Full form",
     "desc": "The full form of your attention, made manifest."},
]
BARTER_EXPIRE_DAYS = 3         # an unconfirmed offer lapses quietly after 3 days

# ---------------------------------------------------------------- chronotype (P5)
CHRONO_MIN_DAYS = 3            # hourHistory days needed before metamorphosis
CHRONO_REVIEW_DAYS = 7         # weekly fingerprint re-review (chronoWeekDate)
CHRONO_WINDOW_DAYS = 30        # fingerprint analysis window (matches history prune)
CHRONO_ACTIVE_FLOOR = 600      # avg seconds/hour to count an hour as "active"
CHRONO_BAND_SHARE = 0.35       # min weighted share of a time band to claim it
CHRONO_COVERAGE = 20           # hours with data >= this -> all-day, no rhythm
CHRONO_SPLIT_GAP_H = 6         # far-apart second peak -> hybrid/erratic schedule
CHRONO_SPLIT_SHARE = 0.25      # that second peak must hold this share of total

# ---------------------------------------------------------------- day-body (P6)
QUIET_MIN_SECS = 600           # < 10 min tracked today -> the pet sleeps
FOG_IDLE_RATIO = 0.40          # > 40% of tracked time idle -> fog (pet droops)
FOG_RAMP = 0.60                # idle ratio where fog intensity hits 1.0
BLOOM_FOCUS_SECS = 3600        # >= 1h continuous focus -> bloom
EMBER_SATURATED = 4            # >= 4 saturated hours today -> ember
EMBER_RAMP = 6                 # saturated hours where ember intensity hits 1.0
STORM_ERROR_STEP = 0.15        # storm intensity climbs 0.15 per error cluster
STORM_WILT_INTENSITY = 0.6     # focus wilt storm intensity
FLOW_RAMP_SECS = 8 * 3600      # tracked time where flow intensity hits 1.0

# Aura per embodied state: (r, g, b, a) overlay, or None = no extra aura
# (quiet/flow keep whatever the chrono gene already glows).
EMBODY_AURA = {
    "fog":   (125, 128, 145, 46),
    "bloom": (255, 205, 110, 60),
    "storm": (226, 84, 84, 55),
    "ember": (255, 118, 46, 55),
    "quiet": None,
    "flow":  None,
}

EMBODY_LABELS = {
    "fog":          "Your day feels foggy \u2014 %s idle",
    "bloom_goal":   "Your day is in full bloom \u2014 daily goal met!",
    "bloom_focus":  "Your day is in full bloom \u2014 %dh of deep focus",
    "storm_error":  "A session errored \u2014 I felt the static",
    "storm_wilt":   "Your focus wilted \u2014 the day feels stormy",
    "ember":        "Embers burning \u2014 %d deep hours today",
    "quiet":        "The day is quiet \u2014 I'm resting too",
    "flow":         "Steady flow \u2014 the day hums along",
}


def day_health(wellbeing, errors=0, focus=None, goal_min=GOAL_DEFAULT_MIN, now=None):
    """Embodied day state — the pet's body IS the dashboard. Pure: the engine
    aura and the dashboard card both build on this one rule, so they can never
    disagree.

    wellbeing: dict with date/apps/hourToday (the engine's live state or the
    wellbeing.json file — same shape). errors: count of today's error/retry
    transitions from the activity log. focus: optional {"active", "elapsed",
    "wilted"} for a live focus session. goal_min: the daily focus-goal
    minutes. Returns {"state", "intensity", "label"} with intensity 0-1
    scaled by the magnitude driving the state.

    Priority: storm > quiet > fog > bloom > ember > flow. Quiet exits before
    fog so a day that hasn't started sleeps instead of drooping — with the
    pet running overnight, idle dominates the first tracked minutes either
    way, and "fog on an empty day" would fire before the user ever sits down.
    """
    now = now if now is not None else time.time()
    today = datetime.date.fromtimestamp(now).isoformat()
    d = wellbeing or {}
    apps = d.get("apps") if d.get("date") == today and isinstance(d.get("apps"), dict) else {}
    total = int(sum(v for v in apps.values() if isinstance(v, (int, float))))
    idle = int(apps.get("Idle", 0) or 0)
    focused = max(0, total - idle)
    f = focus or {}
    if int(errors or 0) > 0 or f.get("wilted"):
        if int(errors or 0) > 0:
            return {"state": "storm",
                    "intensity": min(1.0, 0.5 + int(errors) * STORM_ERROR_STEP),
                    "label": EMBODY_LABELS["storm_error"]}
        return {"state": "storm", "intensity": STORM_WILT_INTENSITY,
                "label": EMBODY_LABELS["storm_wilt"]}
    if total < QUIET_MIN_SECS:
        return {"state": "quiet", "intensity": 1.0 - total / QUIET_MIN_SECS,
                "label": EMBODY_LABELS["quiet"]}
    if total > 0 and idle / total > FOG_IDLE_RATIO:
        pct = int(round(idle * 100.0 / total))
        return {"state": "fog", "intensity": min(1.0, idle / total / FOG_RAMP),
                "label": EMBODY_LABELS["fog"] % ("%d%%" % pct)}
    if focused >= max(1, int(goal_min or GOAL_DEFAULT_MIN)) * 60:
        return {"state": "bloom", "intensity": 1.0,
                "label": EMBODY_LABELS["bloom_goal"]}
    elapsed = float(f.get("elapsed", 0) or 0)
    if elapsed >= BLOOM_FOCUS_SECS:
        return {"state": "bloom", "intensity": min(1.0, elapsed / BLOOM_FOCUS_SECS),
                "label": EMBODY_LABELS["bloom_focus"] % (int(elapsed) // 3600)}
    hours = d.get("hourToday") if d.get("date") == today \
        and isinstance(d.get("hourToday"), dict) else {}
    saturated = [h for h, s in hours.items()
                 if isinstance(s, (int, float)) and s >= CHRONO_ACTIVE_FLOOR]
    if len(saturated) >= EMBER_SATURATED:
        return {"state": "ember", "intensity": min(1.0, len(saturated) / EMBER_RAMP),
                "label": EMBODY_LABELS["ember"] % len(saturated)}
    return {"state": "flow", "intensity": min(1.0, total / FLOW_RAMP_SECS),
            "label": EMBODY_LABELS["flow"]}


# ---------------------------------------------------------------- memory / wake
MEMORY_MIN_DEFAULT = 60          # minutes of work time between memory bubbles
MEMORY_MAX_DEFAULT = 3           # max memory bubbles per day
WAKE_COOLDOWN_SECS = 4 * 3600    # min gap between long-idle wake greetings
NIGHT_OWL_MIN_SECS = 4 * 3600    # a "night-owl day" has this much in hours 0-6
LONG_DAY_MIN_SECS = 9 * 3600     # a "long day" epoch threshold
TEN_HOUR_WINDOW_SECS = 10 * 3600 # 10-day rolling total for the ten-hours epoch
XP_500_EPOCH = 500               # XP threshold for the five-hundred epoch

# ---------------------------------------------------------------- epoch markers
# Life-transition markers (P4): each fires once, guarded by config epochFlags.
# Order = definition order; evaluate_epochs returns them in this order.
EPOCHS = [
    ("first_focus", "First Focus", "Your first completed focus session"),
    ("first_week", "First Week", "7 days of history recorded"),
    ("ten_hour_total", "Ten Hours", "10h of focus across 10 days"),
    ("long_day", "Long Day", "First 9+ hour day"),
    ("night_owl", "Night Owl", "First 4h+ night (midnight to 6am)"),
    ("week_streak", "Week Streak", "First 7-day focus streak"),
    ("xp_500", "Five Hundred", "First 500 XP earned"),
    ("thirty_days", "One Month", "30 days of history recorded"),
]

def goal_minutes(cfg):
    try:
        return max(1, int(cfg.get("goalMin", GOAL_DEFAULT_MIN)))
    except (TypeError, ValueError):
        return GOAL_DEFAULT_MIN


def pomo_next_long(count):
    """True when the break after the NEXT completed pomodoro is long — every
    4th session earns a long break. Shared by the engine (bubble) and the
    dashboard (get_pomo_state) so the rule lives in one place."""
    return (int(count) + 1) % 4 == 0

# ---------------------------------------------------------------- config
def activity_log_path(pet_id):
    """Path of one pet's activity log — computed at call time so tests can
    repoint PET_DIR. One pet, one memory (same rule as engine._log)."""
    return os.path.join(PET_DIR, "activity-%s.jsonl" % pet_id)


def prune_activity_log(pet_id, config=None):
    """Cap a pet's activity log: size > ACTIVITY_MAX_BYTES, or events older
    than ACTIVITY_PRUNE_DAYS. Rewrites once per day (config pruneDate guard),
    keeping the newest ACTIVITY_PRUNE_LINES lines that are still fresh.

    Never raises and never touches the file when it is fine — the engine's
    append path must not break because a prune failed. Returns True when a
    prune actually rewrote the file (the once/day guard is then persisted).
    """
    path = activity_log_path(pet_id)
    cfg = config or {}
    today = datetime.date.today().isoformat()
    try:
        if str(cfg.get(ACTIVITY_PRUNE_KEY) or "") == today:
            return False
        size = os.path.getsize(path)
    except OSError:
        return False
    cutoff = time.time() - ACTIVITY_PRUNE_DAYS * 86400
    # cheap trigger check: size is a stat; the age check reads ONE line (the
    # oldest event is the first line of an append-only file).
    if size <= ACTIVITY_MAX_BYTES:
        try:
            with open(path, encoding="utf-8") as fh:
                first = fh.readline()
        except OSError:
            return False
        try:
            oldest = json.loads(first).get("t")
        except Exception:
            oldest = None
        if not (isinstance(oldest, (int, float)) and oldest < cutoff):
            return False
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.readlines()
        kept = []
        for line in lines[-ACTIVITY_PRUNE_LINES:]:
            try:
                e = json.loads(line)
                if isinstance(e.get("t"), (int, float)) and e["t"] < cutoff:
                    continue
            except Exception:
                continue
            kept.append(line)
        with open(path, "w", encoding="utf-8") as fh:
            fh.writelines(kept)
    except OSError:
        return False
    save_config({ACTIVITY_PRUNE_KEY: today})
    return True


def load_config():
    default = {"petIdx": 0, "alwaysOnTop": True, "walk": 100, "breakMin": 50,
               "goalMin": GOAL_DEFAULT_MIN, "lastGoalDate": "",
               "stretchMin": 45, "chimes": True,
               "pomoMin": 25, "pomoShort": 5, "pomoLong": 15,
               "pomoCount": 0, "pomoDate": "",
               "wakeDate": "", "wakeIdleAt": 0,
               "memoryMin": MEMORY_MIN_DEFAULT, "memoryMax": MEMORY_MAX_DEFAULT,
               "memoryDate": "", "memoryCount": 0, "epochFlags": [],
               "chronoType": "larval", "chronoDate": "", "chronoWeekDate": "",
               "ritualDate": "", "ritualList": [], "ritualDone": [],
               "ritualCloseDate": "",
               "barterBank": 0, "barterStage": 0, "barterOfferDate": "",
               "alertDate": "",
               "reactTyping": True, "reactCursor": True,
               "perchChatter": True, "agentMirror": True, "wanderIdle": True}
    # A concurrent locked save in the other process briefly blocks reads of
    # the locked byte (ERROR_LOCK_VIOLATION); retry a couple of times rather
    # than falling back to defaults for a transient microsecond window.
    for _ in range(CONFIG_READ_RETRIES):
        try:
            with open(CONFIG_FILE, encoding="utf-8") as fh:
                c = json.load(fh)
            if isinstance(c, dict):
                default.update(c)
            return default
        except OSError:
            time.sleep(CONFIG_READ_RETRY_SLEEP)
        except Exception:
            return default
    return default


_CONFIG_THREAD_LOCK = threading.Lock()
_LOCK_TRIES = 50
_LOCK_WAIT_MS = 20


def _lock_with_retry(fd, tries=_LOCK_TRIES, wait_ms=_LOCK_WAIT_MS):
    """Acquire the byte-range lock without the ~10s stall LK_LOCK can block
    for (that would freeze the watcher thread on contention). LK_NBLCK fails
    immediately; writers hold the lock for microseconds, so a short retry
    almost always succeeds, then we give up and rely on the thread lock."""
    for _ in range(tries):
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            time.sleep(wait_ms / 1000.0)
    return False


@contextlib.contextmanager
def _config_lock():
    """Serialize config.json access across BOTH processes and threads.

    The pet and control processes both read-modify-write config.json; without
    a lock an interleaved read/read/write/write silently loses keys (TOCTOU
    race). The msvcrt byte-range lock serializes across processes on Windows;
    the module-level threading.Lock serializes within this process, because
    Windows byte-range locks conflict even between two handles of the same
    process. If the file lock is unavailable we degrade to the thread lock
    alone rather than blocking forever.
    """
    _CONFIG_THREAD_LOCK.acquire()
    fd = None
    yielded = False
    try:
        os.makedirs(PET_DIR, exist_ok=True)
        fd = os.open(CONFIG_FILE, os.O_RDWR | os.O_CREAT)
        _lock_with_retry(fd)
        yielded = True
        yield fd
    except OSError:
        if yielded:
            raise  # exception from the consumer body — never swallow it
        yield None  # only for failures BEFORE the yield (open/lock)
    finally:
        if fd is not None:
            try:
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
            os.close(fd)
        _CONFIG_THREAD_LOCK.release()


def _read_locked_fd(fd):
    """Read config through the lock-holding fd.

    Windows byte-range locks block READS of the locked region from any OTHER
    handle (ERROR_LOCK_VIOLATION — unlike POSIX advisory locks), so a plain
    open() inside the lock fails and the merge silently sees an empty file.
    Seeking and reading the lock-owning handle is the only correct path.
    """
    os.lseek(fd, 0, os.SEEK_SET)
    try:
        raw = os.read(fd, 1 << 20)
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return {}


def _write_locked_fd(fd, data):
    """Write `data` through a lock-held fd. Windows refuses writes into a
    byte-range-locked region from a DIFFERENT handle (ERROR_LOCK_VIOLATION), so
    a separate open() in "w" mode would silently fail and leave the file
    truncated. Seeking/truncating/writing the lock-holding fd is the only
    correct path."""
    os.lseek(fd, 0, os.SEEK_SET)
    os.ftruncate(fd, 0)
    payload = json.dumps(data).encode("utf-8")
    while payload:
        n = os.write(fd, payload)
        payload = payload[n:]
    os.fsync(fd)


def save_config(conf):
    """Persist config, merging with whatever is already on disk.

    The pet process and the control process both write config.json (the pet
    writes its own resolved config + petVisible; the control writes user
    settings + one-shot commands). A bare write would clobber the other
    process's keys, so the whole read-merge-write happens under a
    cross-process file lock (see _config_lock) and writes go through the
    lock-holding handle.
    """
    try:
        with _config_lock() as fd:
            if fd is None:
                return
            existing = _read_locked_fd(fd)
            merged = dict(existing) if isinstance(existing, dict) else {}
            merged.update(conf)
            _write_locked_fd(fd, merged)
    except Exception:
        pass


# ---------------------------------------------------------------- status
def read_status():
    try:
        files = [f for f in os.listdir(PET_DIR) if f.startswith("status-") and f.endswith(".json")]
    except OSError:
        return []
    now_ms = int(time.time() * 1000)
    out = []
    for fn in files:
        try:
            with open(os.path.join(PET_DIR, fn), encoding="utf-8") as fh:
                d = json.load(fh)
            d["stale"] = now_ms - (d.get("updatedAt") or 0) > STALE_MS
            out.append(d)
        except Exception:
            pass
    out.sort(key=lambda s: s.get("updatedAt") or 0, reverse=True)
    return out


def current_app_session():
    """Expose active desktop work when no tool-specific status file exists."""
    app = win32.foreground_app()
    if not app or app in ("Explorer", "Program Manager") or win32.last_input_ms() >= ACTIVE_MS:
        return None
    now_ms = int(time.time() * 1000)
    return {
        "sessionID": "desktop-activity",
        "state": "busy",
        "title": app + " activity",
        "toolLabel": app,
        "message": "Active desktop work",
        "updatedAt": now_ms,
        "direction": "right",
    }


# ---------------------------------------------------------------- wellbeing
def read_wellbeing():
    """Load wellbeing.json, retrying on transient OSError (the pet rewrites
    it non-atomically every WELLBEING_SAVE_INTERVAL s). None when unreadable.

    The one shared read path for the pet engine and every dashboard API, so
    the retry policy and corrupt-file handling live in exactly one place.
    """
    for _ in range(WELLBEING_READ_RETRIES):
        try:
            with open(WELLBEING_FILE, encoding="utf-8") as fh:
                return json.load(fh)
        except OSError:
            time.sleep(WELLBEING_READ_RETRY_SLEEP)
        except Exception:
            return None
    return None


def _fold_today(history, d):
    """Fold a wellbeing dict's live running total (today's `apps` map) into a
    history copy, so a fresh session counts immediately. Returns a new dict;
    the caller's history is never mutated."""
    today = datetime.date.today().isoformat()
    if d and d.get("date") == today and isinstance(d.get("apps"), dict):
        running = int(sum(v for v in d["apps"].values() if isinstance(v, (int, float))))
        if running > 0:
            history = dict(history)
            history[today] = history.get(today, 0) + running
    return history


def week_window(history, days=7, today=None):
    """Split a per-day history dict into (this week, previous week) maps.

    Insertion order runs most-recent-first so `max(map, key=map.get)` ties
    resolve to the newest day — the same rule the dashboard analyses used
    before the split.
    """
    today = today or datetime.date.today()
    week, prev = {}, {}
    for i in range(days * 2):
        day = (today - datetime.timedelta(days=i)).isoformat()
        (week if i < days else prev)[day] = int(history.get(day, 0))
    return week, prev


def hour_buckets(d, days, today=None):
    """Aggregate hour-of-day focus seconds from a wellbeing dict over the
    last `days` calendar days, folding today's live hourToday buckets in."""
    today = today or datetime.date.today()
    buckets = [0] * 24
    if not d:
        return buckets
    hour_hist = d.get("hourHistory") if isinstance(d.get("hourHistory"), dict) else {}
    for i in range(days):
        day = (today - datetime.timedelta(days=i)).isoformat()
        day_map = hour_hist.get(day)
        if isinstance(day_map, dict):
            for h, s in day_map.items():
                if isinstance(s, (int, float)):
                    try:
                        buckets[int(h) % 24] += int(s)
                    except (TypeError, ValueError):
                        pass
    if d.get("date") == today.isoformat() and isinstance(d.get("hourToday"), dict):
        for h, s in d["hourToday"].items():
            if isinstance(s, (int, float)):
                try:
                    buckets[int(h) % 24] += int(s)
                except (TypeError, ValueError):
                    pass
    return buckets


def hour_label(hour):
    """24h -> '9 AM' / '12 PM' style label (tie-in with the peaks UI)."""
    hour = int(hour) % 24
    if hour == 0:
        return "12 AM"
    if hour < 12:
        return "%d AM" % hour
    if hour == 12:
        return "12 PM"
    return "%d PM" % (hour - 12)


# ---------------------------------------------------------------- chronotype (P5)
def chronotype_profile(hour_history):
    """Per-hour average focus over available days + the active-hours list.

    A day counts when it has any hour buckets; averages are over those days
    only (empty days are skipped, not zero-counted), so one clean day weighs
    the same as a full one. Returns:
      hours        : {hour: avg seconds} for hours with any focus
      active_hours : sorted hours averaging >= CHRONO_ACTIVE_FLOOR
      peak_hour    : busiest hour (ties -> earliest), -1 when no data
      peakLabel    : '1 AM'-style label for the peak hour ("" when no data)
      days         : number of days with data
    """
    days = 0
    totals = [0] * 24
    for day_map in (hour_history or {}).values():
        if not isinstance(day_map, dict):
            continue
        if not any(isinstance(s, (int, float)) and s > 0 for s in day_map.values()):
            continue
        days += 1
        for h, s in day_map.items():
            if isinstance(s, (int, float)) and (isinstance(h, int) or str(h).isdigit()):
                totals[int(h) % 24] += int(s)
    hours = {}
    if days:
        hours = {h: totals[h] // days for h in range(24) if totals[h] > 0}
    active = [h for h in range(24) if hours.get(h, 0) >= CHRONO_ACTIVE_FLOOR]
    peak = max(range(24), key=lambda h: (totals[h], -h)) if days else -1
    return {"hours": hours, "active_hours": active, "peak_hour": peak,
            "peakLabel": hour_label(peak) if days else "", "days": days}


def chronotype_class(profile):
    """Classify a chronotype profile into one of the chrono ids.

    Order matters: ERRATIC first (all-day uniform coverage, or two real
    masses of work far apart — neither is a stable rhythm), then the
    strongest time band — night 0-6, lark 5-12, midday 10-16 — provided it
    holds at least CHRONO_BAND_SHARE of total seconds; otherwise BALANCED
    (the default).
    """
    hours = profile.get("hours") or {}
    if not hours:
        return "balanced"
    total = sum(hours.values())
    if total <= 0:
        return "balanced"
    # every hour of the day has data -> all-day schedule, no rhythm
    if len(hours) >= CHRONO_COVERAGE:
        return "erratic"
    peak = max(hours, key=lambda h: (hours[h], -h))
    # a second real mass of work, far from the peak -> split schedule
    runner = 0
    for h, s in hours.items():
        if abs(h - peak) >= CHRONO_SPLIT_GAP_H and s > runner:
            runner = s
    if runner >= CHRONO_SPLIT_SHARE * total and runner >= hours[peak] * 0.5:
        return "erratic"
    bands = {"night_owl": range(0, 7), "lark": range(5, 13), "midday": range(10, 17)}
    scores = {cid: sum(hours.get(h, 0) for h in hrs) / total
              for cid, hrs in bands.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] >= CHRONO_BAND_SHARE else "balanced"


# Data-driven gene manifest: each chrono id -> species/color/pattern/activity
# genes. These are the pet's OWN species names — never existing pet names.
GENE_MANIFEST = {
    "larval":    {"species": "larval",     "color": "gray",     "pattern": "undetermined", "activity": "unshaped"},
    "night_owl": {"species": "nocturnal",  "color": "indigo",   "pattern": "starlight",    "activity": "after-midnight"},
    "lark":      {"species": "sunrise",    "color": "amber",    "pattern": "dawn",         "activity": "early-morning"},
    "midday":    {"species": "daylight",   "color": "golden",   "pattern": "sun",          "activity": "midday"},
    "erratic":   {"species": "hybrid",     "color": "shifting", "pattern": "patchwork",    "activity": "any-hour"},
    "balanced":  {"species": "steady",     "color": "sage",     "pattern": "rhythm",       "activity": "steady-hours"},
}


def gene_manifest(chronotype, profile=None):
    """The pet's chrono-gene manifest for a class — deterministic per class.
    `profile` is kept in the signature so a later data-driven refinement can
    tune genes from the hour fingerprint (peak, spread) without an API change."""
    return dict(GENE_MANIFEST.get(chronotype or "larval", GENE_MANIFEST["larval"]))


READOUTS = {
    "night_owl": "Nocturnal genes detected \u2014 I see your %s self.",
    "lark":      "Sunrise genes \u2014 I rise when you rise (%s).",
    "midday":    "Daylight genes \u2014 your noon engine peaks at %s.",
    "erratic":   "Hybrid genes \u2014 your %s self keeps me guessing.",
    "balanced":  "Steady genes \u2014 a calm rhythm, peaked at %s.",
    "larval":    "My genes are still forming \u2014 I need more days to read you.",
}


def chrono_readout(chronotype, profile=None):
    """Gene readout line for a chrono id, filled with the peak-hour label."""
    line = READOUTS.get(chronotype or "larval", READOUTS["larval"])
    peak = (profile or {}).get("peakLabel") or "midnight"
    return line % peak if "%s" in line else line


# Aura colour per chrono id: (rgb, alpha) + the hour window the gene is
# awake in (None = always awake). None colour = hue shifts by day (erratic).
CHRONO_AURA_SPEC = {
    "night_owl": ((99, 102, 241, 60), (0, 6)),
    "lark":      ((255, 178, 90, 60), (5, 12)),
    "midday":    ((255, 205, 92, 60), (10, 16)),
    "erratic":   (None, None),
    "balanced":  ((141, 196, 157, 30), None),
}


def chrono_aura(chronotype, hour=None, day_of_year=None):
    """Aura colour for a chrono gene at a given hour, or None when the gene
    is dormant (outside its active window / still larval). Pure — the engine
    only draws what this returns."""
    spec = CHRONO_AURA_SPEC.get(chronotype)
    if not spec:
        return None
    color, window = spec
    hour = int(hour or 0) % 24
    if window and not (window[0] <= hour <= window[1]):
        return None
    if color is None:  # erratic: shifting hue by day-of-year
        hue = (((day_of_year or 1) * 137.5) % 360) / 360.0
        r, g, b = colorsys.hsv_to_rgb(hue, 0.65, 1.0)
        return (int(r * 255), int(g * 255), int(b * 255), 55)
    return color


def chrono_next_review(week_date, today=None):
    """ISO date of the next weekly fingerprint review after a review date."""
    today = today or datetime.date.today()
    try:
        last = datetime.date.fromisoformat(str(week_date or ""))
    except (TypeError, ValueError):
        return today.isoformat()
    return (last + datetime.timedelta(days=CHRONO_REVIEW_DAYS)).isoformat()


# ---------------------------------------------------------------- shared rules
def streak_from_history(history, threshold=STREAK_MIN_SECS):
    """Consecutive days ending today or yesterday with >= `threshold` focus.

    Shared by the pet process (PetEngine._streak_days) and the control/web
    process (ControlApi.get_pet_profile) so the rule lives in one place.
    Today with < threshold doesn't break the chain — the day isn't over yet.
    The threshold is per-day seconds; the focus streak passes 30min, the
    daily-goal streak passes goalMin*60.
    """
    today = datetime.date.today()
    streak = 0
    for back in range(0, STREAK_LOOKBACK_DAYS):
        day = (today - datetime.timedelta(days=back)).isoformat()
        if int(history.get(day, 0)) >= threshold:
            streak += 1
        elif back == 0:
            continue  # today may still be building; check yesterday
        else:
            break
    return streak


def evolution_stage(level):
    """Level -> evolution stage: name + emoji + aura colour + sprite suffix.

    Launch ships PROGRAMMATIC evolution (a coloured aura glow + label baked
    from the SAME sprite sheet — no new art needed). When real per-stage
    sprite sheets are added later, drop them in desktop/sprites as
    ``pet-<id>-stageN.webp`` (N = 1/2/3) and _load_sheet prefers them; the
    rest of the app (stage name, badge, aura) needs no changes.
    """
    level = int(level or 1)
    if level >= EVOLVE_LEVEL_3:
        return {"id": "stage3", "name": "Evolved", "emoji": "\u2728",
                "aura": (226, 162, 60, 40), "suffix": "stage3"}
    if level >= EVOLVE_LEVEL_2:
        return {"id": "stage2", "name": "Growing", "emoji": "\ud83c\udf31",
                "aura": (93, 215, 155, 34), "suffix": "stage2"}
    return {"id": "stage1", "name": "Baby", "emoji": "\ud83d\udc0a",
            "aura": (93, 185, 216, 26), "suffix": "stage1"}


def focus_progress(active, started_at, target_min, now=None):
    """0..1 progress of a live focus session — one pure rule shared by the
    pet engine and the dashboard ring so they always agree."""
    if not active:
        return 0.0
    el = (now if now is not None else time.time()) - float(started_at)
    return max(0.0, min(1.0, el / max(1, float(target_min) * 60)))


# ---------------------------------------------------------------- dream journal
def _fmt_hours(secs):
    """Seconds -> '9.3h' style label for dream lines."""
    return "%.1fh" % (int(secs) / 3600.0)


def deepest_day(history):
    """(date, seconds) of the day with the most focus in a history dict.
    Ties resolve to the newest day (same rule as week_window)."""
    hist = history or {}
    if not hist:
        return None, 0
    day = max(hist, key=lambda d: (int(hist.get(d, 0) or 0), d))
    return day, int(hist.get(day, 0) or 0)


def latest_hour(hour_history):
    """(hour, seconds) of the busiest hour-of-day across ALL recorded days.
    Ties resolve to the earliest hour."""
    agg = [0] * 24
    for day_map in (hour_history or {}).values():
        if not isinstance(day_map, dict):
            continue
        for h, s in day_map.items():
            if isinstance(s, (int, float)) and (isinstance(h, int) or str(h).isdigit()):
                agg[int(h) % 24] += int(s)
    best = max(range(24), key=lambda h: (agg[h], -h))
    return best, agg[best]


def _dream_day(d):
    """(date, seconds) of the latest COMPLETED day with data: the newest
    calendar day before today that has recorded focus, folding the file's
    live apps map in when the file itself holds that day (pet was off)."""
    today = datetime.date.today().isoformat()
    hist = d.get("history") if isinstance(d.get("history"), dict) else {}
    candidates = set()
    fdate = d.get("date")
    if isinstance(fdate, str) and fdate and fdate < today:
        candidates.add(fdate)
    for day in hist:
        if isinstance(day, str) and day < today:
            candidates.add(day)
    for day in sorted(candidates, reverse=True):
        secs = int(hist.get(day, 0) or 0)
        if d.get("date") == day and isinstance(d.get("apps"), dict):
            secs += int(sum(v for v in d["apps"].values() if isinstance(v, (int, float))))
        if secs > 0:
            return day, secs
    return None, 0


def build_dream(wellbeing):
    """Yesterday's digest for the wake ritual — a pure, deterministic string.

    Picks one template by the shape of yesterday's data (deepest day, record
    day, night owl, idle-heavy, most apps, quiet, or a plain summary). No
    randomness: the same wellbeing dict always yields the same dream, so the
    pet's bubble and the dashboard card can never disagree. Empty string when
    there is no completed day of data yet.
    """
    d = wellbeing
    if not isinstance(d, dict):
        return ""
    hist = d.get("history") if isinstance(d.get("history"), dict) else {}
    hour_hist = d.get("hourHistory") if isinstance(d.get("hourHistory"), dict) else {}
    app_hist = d.get("appHistory") if isinstance(d.get("appHistory"), dict) else {}
    day, total = _dream_day(d)
    if day is None or total <= 0:
        return ""
    # yesterday's own hour buckets (falls back to the global best hour)
    day_hours = hour_hist.get(day) if isinstance(hour_hist.get(day), dict) else {}
    best_h, best_s = latest_hour(hour_hist)
    best_line = ""
    if (day_hours or best_s > 0) and best_s > 0:
        best_line = " Best hour: %s." % hour_label(best_h)
    # per-app breakdown for that day (history + live apps map)
    day_apps = dict(app_hist.get(day)) if isinstance(app_hist.get(day), dict) else {}
    if d.get("date") == day and isinstance(d.get("apps"), dict):
        for a, s in d["apps"].items():
            if isinstance(s, (int, float)):
                day_apps[a] = day_apps.get(a, 0) + int(s)
    deepest, _ = deepest_day(hist)
    if day == deepest and total >= LONG_DAY_MIN_SECS:
        return ("I dreamt of terminals\u2026 yesterday was your record day \u2014 %s.%s"
                % (_fmt_hours(total), best_line))
    if day == deepest:
        return ("I dreamt of terminals\u2026 yesterday was your deepest day (%s).%s"
                % (_fmt_hours(total), best_line))
    if best_h < 6 and best_s > 0:
        return ("I dreamt of terminals\u2026 best hour %s \u2014 you're a night owl.%s"
                % (hour_label(best_h), best_line))
    idle = int(day_apps.get("Idle", 0) or 0)
    if total > 0 and idle >= total * 0.5:
        return "I dreamt of terminals\u2026 yesterday was mostly idle. Rest counts too."
    app_names = [a for a in day_apps if a != "Idle"]
    if len(app_names) >= 5:
        return "I dreamt of terminals\u2026 yesterday you touched %d apps." % len(app_names)
    if total < 3600:
        return "I dreamt of terminals\u2026 yesterday was quiet \u2014 I slept well too."
    top = max(app_names, key=day_apps.get) if app_names else ""
    line = "I dreamt of terminals\u2026 yesterday: %s." % _fmt_hours(total)
    if top:
        line += " %s led the way." % top
    return line


# ---------------------------------------------------------------- memory lane (P8)
LANE_DAYS = 7                 # the lane always shows the last 7 calendar days
LANE_IDLE_RATIO = 0.45        # idle share above this -> "foggy day" note
LANE_QUIET_MAX_SECS = 3600    # below this total -> "a still day" note
LANE_MULTI_PET_MIN = 2        # pet switches >= this many -> multi-pet note
VOICE_MAX_LINES = 4           # at most 4 pet-voice narrations per week
VOICE_WALL_HOURS = 8          # a day is "wall-to-wall" with this many saturated hours
VOICE_WALL_DAYS = 3           # ...and the week needs at least this many such days
VOICE_IDLE_RATIO = 0.30       # idle share above this -> idle-fog voice line
VOICE_APPS_MIN = 5            # distinct apps >= this many -> "N hats" voice line
VOICE_STREAK_MIN = 3          # streak >= this many days -> praise voice line


def _day_apps(app_hist, day, d=None):
    """Per-day app map for one date, folding the file's live apps map in
    when the file itself holds that day (same rule as build_dream)."""
    apps = dict(app_hist.get(day)) if isinstance(app_hist.get(day), dict) else {}
    if d and d.get("date") == day and isinstance(d.get("apps"), dict):
        for a, s in d["apps"].items():
            if isinstance(s, (int, float)):
                apps[a] = apps.get(a, 0) + int(s)
    return apps


def _day_hours(hour_hist, day, d=None):
    """Per-day hour buckets for one date (int keys), folding today's live
    hourToday in (same rule as hour_buckets)."""
    hours = {}
    raw = hour_hist.get(day)
    if isinstance(raw, dict):
        for h, s in raw.items():
            if isinstance(s, (int, float)) and (isinstance(h, int) or str(h).isdigit()):
                hours[int(h) % 24] = hours.get(int(h) % 24, 0) + int(s)
    if d and d.get("date") == day and isinstance(d.get("hourToday"), dict):
        for h, s in d["hourToday"].items():
            if isinstance(s, (int, float)):
                try:
                    hours[int(h) % 24] = hours.get(int(h) % 24, 0) + int(s)
                except (TypeError, ValueError):
                    pass
    return hours


def day_note(day, data):
    """Pet-voice one-liner for one lane day, chosen by the REAL shape of its
    data (the same rule the API card shows, so they can never disagree).

    Priority: record (deepest of the lane) > night-owl > quiet > idle-heavy
    > multi-pet > error > pattern. Deterministic: the same data always
    yields the same line, and the pet's memory lane is its own narration —
    numbers and templates only, no randomness.
    """
    data = data or {}
    total = int(data.get("total", 0) or 0)
    if total <= 0:
        return "a still day \u2014 nothing recorded, I rested too"
    if total == int(data.get("weekMax", 0) or 0):
        return "your deepest day \u2014 %s" % _fmt_hours(total)
    hours = data.get("hours") or {}
    if _range_secs(hours, 0, 6) >= NIGHT_OWL_MIN_SECS:
        return "I watched you work past 3am \u2014 the night was yours"
    if total < LANE_QUIET_MAX_SECS:
        return "a still day \u2014 I rested with you"
    apps = data.get("apps") or {}
    idle = int(apps.get("Idle", 0) or 0)
    if idle >= total * LANE_IDLE_RATIO:
        return "a foggy day \u2014 %d%% of it was idle" % (idle * 100 // total)
    if int(data.get("petSwitches", 0) or 0) >= LANE_MULTI_PET_MIN:
        return "you visited %d forms that day" % (int(data.get("petSwitches", 0)) + 1)
    if int(data.get("errors", 0) or 0) > 0:
        return "a day with static \u2014 I felt the glitches"
    top = max((a for a in apps if a != "Idle"), key=apps.get, default="")
    if top:
        return "a steady day \u2014 %s, and %s led the way" % (_fmt_hours(total), top)
    return "a steady day \u2014 %s" % _fmt_hours(total)


def build_lane(wellbeing, events=None, days=LANE_DAYS):
    """The pet's memory lane: one narrated entry per day for the last `days`
    calendar days (ascending, today last), computed from REAL data.

    Each entry is {date, totalMin, appTop, hourPeak, note}: totalMin is the
    day's tracked minutes (idle included, matching history semantics), appTop
    the day's top non-idle app (None when none), hourPeak the busiest hour
    (ties -> earliest; None when no data), note the pet's line from day_note.
    `events` is an optional list of activity-log dicts for per-day error and
    pet-switch counts. Pure + deterministic: the same inputs always yield
    the same lane.
    """
    d = wellbeing
    if not isinstance(d, dict):
        d = {}
    history = d.get("history") if isinstance(d.get("history"), dict) else {}
    app_hist = d.get("appHistory") if isinstance(d.get("appHistory"), dict) else {}
    hour_hist = d.get("hourHistory") if isinstance(d.get("hourHistory"), dict) else {}
    today = datetime.date.today()
    week_days = [(today - datetime.timedelta(days=i)).isoformat()
                 for i in range(days - 1, -1, -1)]
    per_errors = {}
    per_switches = {}
    for e in events or []:
        if not isinstance(e, dict):
            continue
        day = time.strftime("%Y-%m-%d", time.localtime(e.get("t", 0) or 0))
        if e.get("kind") == "state" and e.get("state") in ("error", "retry"):
            per_errors[day] = per_errors.get(day, 0) + 1
        elif e.get("kind") == "petSwitch":
            per_switches[day] = per_switches.get(day, 0) + 1
    per_day = {}
    for day in week_days:
        total = int(history.get(day, 0) or 0)
        if d.get("date") == day:
            running = int(sum(v for v in (d.get("apps") or {}).values()
                              if isinstance(v, (int, float))))
            if running > 0:
                total += running
        per_day[day] = total
    week_max = max(per_day.values()) if per_day else 0
    out = []
    for day in week_days:
        apps = _day_apps(app_hist, day, d)
        app_names = [a for a in apps if a != "Idle"
                     and isinstance(apps.get(a), (int, float)) and apps[a] > 0]
        app_top = max(app_names, key=apps.get) if app_names else None
        hours = _day_hours(hour_hist, day, d)
        peak = -1
        if hours:
            peak = max(hours, key=lambda h: (hours[h], -h))  # ties -> earliest
        data = {"total": per_day[day], "apps": apps, "hours": hours,
                "errors": per_errors.get(day, 0),
                "petSwitches": per_switches.get(day, 0), "weekMax": week_max}
        out.append({"date": day,
                    "totalMin": int(per_day[day]) // 60,
                    "appTop": app_top,
                    "hourPeak": peak if peak >= 0 else None,
                    "note": day_note(day, data)})
    return out


def voice_insights(history, hour_history, app_history, focus=None, today=None):
    """Pet-voice narrations of the last 7 days, 0..VOICE_MAX_LINES lines.

    Each line fires on REAL week data, in priority order: wall-to-wall
    deep-work days, midnight outshining afternoons, idle-fog share, app
    variety ("N hats"), the honest focus-candle confession (started sessions
    with zero completions \u2014 non-punitive), and streak praise. Capped at
    4 so the pet narrates, never floods. `focus` is an optional
    {"starts", "done"} week count from the activity log.
    """
    today = today or datetime.date.today()
    hist = history or {}
    hh = hour_history or {}
    ah = app_history or {}
    week_days = [(today - datetime.timedelta(days=i)).isoformat() for i in range(7)]
    lines = []
    # deep work: >= VOICE_WALL_DAYS days with >= VOICE_WALL_HOURS saturated hours
    wall = 0
    night = afternoon = 0
    for day in week_days:
        day_map = hh.get(day)
        if not isinstance(day_map, dict):
            continue
        if sum(1 for s in day_map.values()
               if isinstance(s, (int, float)) and s >= CHRONO_ACTIVE_FLOOR) >= VOICE_WALL_HOURS:
            wall += 1
        for h, s in day_map.items():
            if not isinstance(s, (int, float)):
                continue
            try:
                h = int(h) % 24
            except (TypeError, ValueError):
                continue
            if h < 6:
                night += int(s)
            elif 12 <= h < 18:
                afternoon += int(s)
    if wall >= VOICE_WALL_DAYS:
        lines.append("%d days this week had wall-to-wall hours \u2014 "
                     "that's how work becomes monuments" % wall)
    if night > 0 and night > afternoon:
        lines.append("your midnight hours outshine your afternoons")
    # idle-fog share of the week's tracked time
    idle = total = 0
    app_names = set()
    for day in week_days:
        day_map = ah.get(day)
        if not isinstance(day_map, dict):
            continue
        for a, s in day_map.items():
            if not isinstance(s, (int, float)):
                continue
            total += int(s)
            if a == "Idle":
                idle += int(s)
            elif int(s) > 0:
                app_names.add(a)
    if total > 0 and idle >= total * VOICE_IDLE_RATIO:
        lines.append("%d%% of your week slipped into idle fog" % (idle * 100 // total))
    if len(app_names) >= VOICE_APPS_MIN:
        lines.append("you wore %d hats this week" % len(app_names))
    f = focus or {}
    starts = int(f.get("starts", 0) or 0)
    done = int(f.get("done", 0) or 0)
    if starts > 0 and done == 0:
        lines.append("you've lit %d candles but let them all burn out \u2014 "
                     "I'm here when you want to keep one" % starts)
    streak = streak_from_history(hist)
    if streak >= VOICE_STREAK_MIN:
        lines.append("%d days in a row \u2014 I'm counting with you" % streak)
    return lines[:VOICE_MAX_LINES]


def week_end_review(history, today=None):
    """Sunday-evening week close in the pet's voice: the week's REAL total
    plus a tease of next week's ritual (guard the user's sharpest hour)."""
    week, _ = week_window(history or {}, today=today or datetime.date.today())
    total = sum(week.values())
    return ("The week closed at %s \u2014 next week I'll guard your "
            "sharpest hour." % _fmt_hours(total))


# ---------------------------------------------------------------- epoch markers
def _epoch_conditions(history, hour_history, config, xp, focus_count=0):
    """Set of epoch ids whose thresholds the data now crosses (regardless of
    whether they were celebrated before). Pure; the engine/UI both build on it."""
    cfg = config or {}
    today = datetime.date.today()
    hist = history or {}
    hour_hist = hour_history or {}

    def day_secs(day):
        return int(hist.get(day, 0) or 0)

    days = [dd for dd in hist if isinstance(dd, str) and dd <= today.isoformat()]
    active_days = [dd for dd in days if day_secs(dd) > 0]
    out = set()
    if int(focus_count or 0) >= 1:
        out.add("first_focus")
    if len(active_days) >= 7:
        out.add("first_week")
    last10 = [(today - datetime.timedelta(days=i)).isoformat() for i in range(10)]
    if sum(day_secs(dd) for dd in last10) >= TEN_HOUR_WINDOW_SECS:
        out.add("ten_hour_total")
    if any(day_secs(dd) >= LONG_DAY_MIN_SECS for dd in days):
        out.add("long_day")
    for day_map in hour_hist.values():
        if not isinstance(day_map, dict):
            continue
        night = sum(int(s) for h, s in day_map.items()
                    if isinstance(s, (int, float))
                    and (isinstance(h, int) or str(h).isdigit()) and int(h) < 6)
        if night >= NIGHT_OWL_MIN_SECS:
            out.add("night_owl")
            break
    if streak_from_history(hist) >= 7:
        out.add("week_streak")
    if int(xp or 0) >= XP_500_EPOCH:
        out.add("xp_500")
    if len(active_days) >= 30:
        out.add("thirty_days")
    return out


def evaluate_epochs(history, hour_history, config, xp, focus_count=0):
    """Crossed life-transition markers NOT yet recorded in config['epochFlags'].

    Returns [(id, name, desc), ...] in EPOCHS definition order. Each epoch
    fires exactly once in its life: once an id lands in epochFlags it is
    filtered out here, so re-evaluating is idempotent."""
    crossed = _epoch_conditions(history, hour_history, config, xp, focus_count)
    flags = set((config or {}).get("epochFlags") or [])
    return [(eid, name, desc) for (eid, name, desc) in EPOCHS
            if eid in crossed and eid not in flags]


def best_streak(history, threshold=STREAK_MIN_SECS):
    """Longest consecutive run of >= threshold days anywhere in a history
    dict (the all-time record, not the live chain). Used by memory bubbles to
    tell "never done before" from "matches your best"."""
    hist = history or {}
    best = run = 0
    prev = None
    for dd in sorted(hist):
        ok = int(hist.get(dd, 0) or 0) >= threshold
        if ok and prev is not None:
            prev_d = datetime.date.fromisoformat(prev)
            gap = (datetime.date.fromisoformat(dd) - prev_d).days
            run = run + 1 if gap == 1 else 1
        else:
            run = 1 if ok else 0
        prev = dd
        if run > best:
            best = run
    return best


# ---------------------------------------------------------------- rituals (P7)
def _bucket_secs(hours, target):
    """Seconds in one hour bucket, tolerant of int OR string hour keys."""
    if not isinstance(hours, dict):
        return 0
    try:
        target = int(target)
    except (TypeError, ValueError):
        return 0
    total = 0
    for k, v in hours.items():
        try:
            if int(k) == target and isinstance(v, (int, float)):
                total += int(v)
        except (TypeError, ValueError):
            continue
    return total


def _range_secs(hours, lo, hi):
    """Seconds across hour buckets lo..hi inclusive (e.g. night 0-6)."""
    return sum(_bucket_secs(hours, h) for h in range(lo, hi + 1))


def ritual_progress(ritual, wellbeing, config, now=None):
    """Live {current, done} for ONE ritual against today's REAL data.

    Pure and shared by the pet engine and the dashboard card so they can
    never disagree. current is in minutes; done is current >= target.
    """
    r = ritual or {}
    kind = r.get("kind")
    d = wellbeing or {}
    today = datetime.date.fromtimestamp(now if now is not None else time.time()).isoformat()
    apps = d.get("apps") if d.get("date") == today and isinstance(d.get("apps"), dict) else {}
    hours = d.get("hourToday") if d.get("date") == today and isinstance(d.get("hourToday"), dict) else {}
    hist = d.get("history") if isinstance(d.get("history"), dict) else {}
    secs = 0
    if kind in ("guard_hour", "first_light"):
        h = int(r.get("hour") or -1)
        if h >= 0:
            secs = _bucket_secs(hours, h)
    elif kind == "beat_yesterday":
        secs = int(sum(v for v in apps.values() if isinstance(v, (int, float))))
        if secs <= 0:
            secs = int(hist.get(today, 0) or 0)
    elif kind == "break_the_idle":
        total = int(sum(v for v in apps.values() if isinstance(v, (int, float))))
        secs = max(0, total - int(apps.get("Idle", 0) or 0))
    elif kind == "night_guard":
        secs = _range_secs(hours, *RITUAL_NIGHT_HOURS)
    target = max(1, int(r.get("target") or 0))
    current = int(secs) // 60
    return {"current": current, "done": current >= target}


def derive_rituals(wellbeing, focus_count, config):
    """Today's personal rituals, derived from the user's OWN history.

    Up to RITUAL_MAX_DAILY in priority order: guard_hour (historical best
    hour with >= 1h avg), beat_yesterday (yesterday's total, >= 1h),
    break_the_idle (yesterday > 30% idle), night_guard (night-owl chrono),
    first_light (lark chrono). Each dict is {id, name, desc, target, current,
    done, kind} — kind == id, plus "hour" for the hour-scoped kinds (frozen
    at derivation so later data can't move the goalposts).
    """
    d = wellbeing or {}
    hist = d.get("history") if isinstance(d.get("history"), dict) else {}
    hour_hist = d.get("hourHistory") if isinstance(d.get("hourHistory"), dict) else {}
    app_hist = d.get("appHistory") if isinstance(d.get("appHistory"), dict) else {}
    today = datetime.date.today()
    yday = (today - datetime.timedelta(days=1)).isoformat()
    # yesterday's total + per-app map (fold the live apps map when the file
    # itself still holds yesterday — same rule as _fold_today)
    ysecs = int(hist.get(yday, 0) or 0)
    yapps = dict(app_hist.get(yday)) if isinstance(app_hist.get(yday), dict) else {}
    if d.get("date") == yday and isinstance(d.get("apps"), dict):
        for a, s in d["apps"].items():
            if isinstance(s, (int, float)):
                ysecs += int(s)
                yapps[a] = yapps.get(a, 0) + int(s)
    chrono = str((config or {}).get("chronoType", "larval") or "larval")
    profile = chronotype_profile(hour_hist)
    peak = profile.get("peak_hour", -1)
    peak_avg = profile.get("hours", {}).get(peak, 0) if peak >= 0 else 0

    out = []
    # 1. guard_hour: the user's own sharpest hour, protected
    if peak >= 0 and peak_avg >= RITUAL_GUARD_MIN_SECS:
        out.append({"id": "guard_hour", "kind": "guard_hour",
                    "name": "Guard the hour",
                    "desc": "Protect your %s-%s \u2014 it's your sharpest hour"
                            % (hour_label(peak), hour_label(peak + 1)),
                    "target": 30, "hour": peak})
    # 2. beat_yesterday: match yesterday's own total
    if ysecs >= RITUAL_BEAT_MIN_SECS:
        out.append({"id": "beat_yesterday", "kind": "beat_yesterday",
                    "name": "Match yesterday",
                    "desc": "You did %.1fh yesterday \u2014 match it"
                            % (ysecs / 3600.0),
                    "target": max(30, int(ysecs) // 60)})
    # 3. break_the_idle: reclaim a day that slipped into idle
    if ysecs > 0 and int(yapps.get("Idle", 0) or 0) / ysecs > RITUAL_IDLE_RATIO:
        out.append({"id": "break_the_idle", "kind": "break_the_idle",
                    "name": "Break the idle",
                    "desc": "Yesterday %d%% was idle \u2014 reclaim 2h"
                            % (int(yapps.get("Idle", 0) or 0) * 100 // ysecs),
                    "target": RITUAL_BREAK_TARGET_MIN})
    # 4. night_guard: a night owl's deep hour after midnight
    if chrono == "night_owl":
        out.append({"id": "night_guard", "kind": "night_guard",
                    "name": "Night guard",
                    "desc": "Guard the witching hours \u2014 1 deep hour after midnight",
                    "target": RITUAL_NIGHT_TARGET_MIN})
    # 5. first_light: a lark's morning hour
    if chrono == "lark":
        lark_h = -1
        for h in range(RITUAL_LARK_HOURS[0], RITUAL_LARK_HOURS[1] + 1):
            if profile.get("hours", {}).get(h, 0) > profile.get("hours", {}).get(lark_h, 0):
                lark_h = h
        if lark_h >= 0:
            out.append({"id": "first_light", "kind": "first_light",
                        "name": "First light",
                        "desc": "Rise with the sun \u2014 your %s hour awaits"
                                % hour_label(lark_h),
                        "target": 30, "hour": lark_h})
    out = out[:RITUAL_MAX_DAILY]
    # freeze live progress at derivation time (recomputed live later)
    for r in out:
        p = ritual_progress(r, d, config)
        r["current"] = p["current"]
        r["done"] = p["done"]
    return out


# ---------------------------------------------------------------- barter (P7)
def barter_next_offer(stage):
    """The next tradable form stage for a barterStage, or None when every
    stage is done. barterStage = stages completed (0 = no stages yet)."""
    try:
        i = int(stage or 0)
    except (TypeError, ValueError):
        i = 0
    if i < 0:
        i = 0
    if i >= len(BARTER_OFFERS):
        return None
    return dict(BARTER_OFFERS[i])
