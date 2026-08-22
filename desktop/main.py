"""OpenCode Pet — standalone desktop pet. Entry point.

Architecture (why):
  - The PET is a GDI layered window (UpdateLayeredWindow): per-pixel alpha is
    guaranteed, the window is exactly sprite-sized, and dragging anywhere is
    native (WM_NCHITTEST -> HTCAPTION). WebView2's compositor ignores OS-level
    transparency, which is why the previous box/pink/white attempts failed.
  - The CONTROL app is a pywebview window in its own process: pet picker +
    behavior settings. It talks to the pet through config.json + one-shot
    commands, so the pet process never hosts a browser.
  - All data is LOCAL (config.json + status files in ~/.opencode/pet). Nothing
    leaves the machine.

Run as `python desktop/main.py`, `python -m desktop.main`, or from a frozen
build. This module is the package front door: it re-exports everything the
rest of the app (and the test suite) imports from `desktop.main`.
"""

import ctypes
import os
import sys
import threading
import time

# `python desktop/main.py` runs this file as __main__ with no package context,
# so the repo root must be on sys.path before any package imports below.
if __package__ is None:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image, ImageFont  # noqa: E402 — re-exported for tests

from desktop.api import ControlApi, _WEB_METHODS, _WEB_NOP  # noqa: E402
from desktop.engine import PetEngine  # noqa: E402
from desktop.sprites import DEFAULT_MAP, PET_STATES, PETS, pet_states  # noqa: E402
from desktop.store import (  # noqa: E402
    ACTIVE_MS, CONFIG_FILE, FOCUS_FILE, PET_DIR, STALE_MS, WELLBEING_FILE,
    _fold_today, current_app_session, evolution_stage, load_config,
    pomo_next_long, read_status, save_config, streak_from_history,
)
from desktop.tray import create_tray  # noqa: E402
from desktop.web import run_control, run_web, spawn_control  # noqa: E402
from desktop.win32 import (  # noqa: E402
    LASTINPUTINFO, PetWindow, cursor_pos, foreground_app, kernel32,
    last_input_ms, read_dir_changes, user32, workarea,
)

# watcher thread tuning
WATCH_SLEEP_SECS = 0.15
WATCH_POLL_FALLBACK_SECS = 2.0  # fallback when file watch is broken
WATCH_PRUNE_SECS = 30


def _parse_web_args():
    """Pull --port/--pet-dir/--selftest-tail out of sys.argv for --web mode.
    Returns (port, pet_dir, tail) or None when the args are invalid."""
    args = sys.argv[sys.argv.index("--web") + 1:]
    port = 0
    pet_dir = None
    tail = None
    i = 0
    while i < len(args):
        if args[i] == "--port":
            if i + 1 >= len(args):
                print("--web: --port needs a value"); return None
            try:
                port = int(args[i + 1])
            except ValueError:
                print("--web: invalid --port %r (must be an integer)" % args[i + 1]); return None
            i += 2
        elif args[i] == "--pet-dir":
            if i + 1 >= len(args):
                print("--web: --pet-dir needs a value"); return None
            pet_dir = args[i + 1]; i += 2
        elif args[i] == "--selftest-tail":
            if i + 1 >= len(args):
                print("--web: --selftest-tail needs a value"); return None
            try:
                with open(args[i + 1], encoding="utf-8") as fh:
                    tail = fh.read()
            except Exception:
                tail = None
            i += 2
        else:
            i += 1
    return port, pet_dir, tail


def main():
    if "--control" in sys.argv:
        run_control()
        return
    if "--web" in sys.argv:
        parsed = _parse_web_args()
        if parsed is None:
            return
        port, pet_dir, tail = parsed
        run_web(port=port, pet_dir=pet_dir, extra_tail=tail)
        return

    mutex = kernel32.CreateMutexW(None, False, "OpenCodePet_SingleInstance")
    if ctypes.get_last_error() == 183:
        # Refuse to start ONLY when the owning instance's pet window is actually
        # alive. A leaked mutex handle held by a crashed/orphaned child (e.g. a
        # --control WebView2 subprocess) must not block a fresh launch.
        try:
            alive_win = bool(user32.FindWindowW("OpenCodePetLayer", None))
        except Exception:
            alive_win = True
        if alive_win:
            print("OpenCode Pet is already running.", file=sys.stderr)
            sys.exit(0)
        # zombie mutex (no live window): take over by continuing to boot
    os.makedirs(PET_DIR, exist_ok=True)
    engine = PetEngine()
    engine.area = workarea()
    engine.win.show()
    engine._prune_status()  # clear stale session files from previous runs

    # Load sessions that were already running BEFORE the app started. The
    # watcher below only fires on file CHANGES, so pre-existing status files
    # would otherwise never reach the engine.
    engine.update_sessions(read_status())

    create_tray(engine)

    # Launching the app should open the control window too, not just the pet.
    # It runs as its own process so the pet never hosts a browser.
    try:
        spawn_control()
    except Exception:
        pass

    # watcher thread -> push session changes + config/commands to engine.
    # Falls back to polling every 2s if ReadDirectoryChangesW fails permanently
    # (e.g., antivirus lock, network redirect, or missing permissions).
    def watcher():
        last_prune = 0.0
        poll_interval = WATCH_POLL_FALLBACK_SECS
        last_poll = 0.0
        while not engine._shutdown:
            try:
                engine._watch_failures = 0
                for _ in read_dir_changes(PET_DIR):
                    if engine._shutdown:
                        return
                    time.sleep(WATCH_SLEEP_SECS)
                    engine.update_sessions(read_status())
                    engine.config_watch()
                    if time.time() - last_prune >= WATCH_PRUNE_SECS:
                        last_prune = time.time()
                        engine._prune_status()
                    last_poll = time.time()
            except Exception:
                engine._watch_failures += 1
                if engine._watch_failures == 1:
                    import traceback
                    traceback.print_exc()
            # Periodic refresh so sessions that appear (or stale) without a
            # directory-change event still reach the engine.
            if time.time() - last_poll >= poll_interval:
                engine.update_sessions(read_status())
                engine.config_watch()
                if time.time() - last_prune >= WATCH_PRUNE_SECS:
                    last_prune = time.time()
                    engine._prune_status()
                last_poll = time.time()
            time.sleep(poll_interval)
            if engine._shutdown:
                return

    threading.Thread(target=watcher, daemon=True).start()

    def render_loop():
        next_t = time.time()
        while not engine._shutdown:
            engine.update_activity()
            engine.loop()
            now = time.time()
            next_t = max(next_t, now)          # resync: never busy-spin to catch up
            next_t += PetEngine.TICK
            time.sleep(max(0.002, next_t - now))

    threading.Thread(target=render_loop, daemon=True).start()

    # main thread hosts the pet window's message pump (clicks, drag, hit-test)
    engine.win.pump()


if __name__ == "__main__":
    main()
