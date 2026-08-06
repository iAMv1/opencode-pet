"""Data layer: file paths, config/status/wellbeing persistence, shared stats.

Everything reads the module globals at call time (never via `from .store
import X` copies in other modules) so tests can repoint the paths with
monkeypatch and --web --pet-dir can redirect them at runtime.
"""

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

# ---------------------------------------------------------------- focus rules
STREAK_MIN_SECS = 30 * 60        # default daily focus streak threshold
STREAK_LOOKBACK_DAYS = 400       # how far back a streak chain is examined
APP_MIN_SECS = 30                # floor for today's top-app lists
WEEK_APP_MIN_SECS = 60           # floor for weekly per-app lists
TOP_APPS_LIMIT = 8
EVOLVE_LEVEL_2 = 5
EVOLVE_LEVEL_3 = 10
GOAL_DEFAULT_MIN = 120

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
def load_config():
    default = {"petIdx": 0, "alwaysOnTop": True, "walk": 100, "breakMin": 50,
               "goalMin": GOAL_DEFAULT_MIN, "lastGoalDate": "",
               "stretchMin": 45, "chimes": True,
               "pomoMin": 25, "pomoShort": 5, "pomoLong": 15,
               "pomoCount": 0, "pomoDate": ""}
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
