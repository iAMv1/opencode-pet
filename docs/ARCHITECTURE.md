# OpenCode Pet — Architecture (ARCHITECTURE.md)

## 1. Module diagram

```
                        ┌──────────────────────────────────────────────┐
                        │              desktop/main.py                 │
                        │  entry · single-instance mutex · mode router │
                        │  re-exports the public API for tests         │
                        └──────┬───────────────┬───────────────┬───────┘
                               │ spawns         │ spawns        │
                  ┌────────────▼────┐   ┌───────▼──────┐  ┌─────▼──────────┐
                  │ pet process     │   │ control proc │  │ --web server   │
                  │                 │   │              │  │ (any browser)  │
   ┌──────────────▼─────────────┐   │   └──────────────┘  └───────────────┘
   │ engine.py  PetEngine       │   │         │ api.py (ControlApi)       │
   │  physics · states · growth │   │         │  reads store.*, writes    │
   │  focus · memory · chrono   │   │         │  one-shot commands        │
   │  embody · rituals · barter │   │         └──────────┬────────────────┘
   │  alerts · presence         │   │                    │ pywebview js_api
   └───────┬────────────────────┘   │   ┌────────────────▼───────────────┐
           │                        │   │ control.html (pet picker,      │
   ┌───────▼────────┐               │   │ settings, snooze, quit)        │
   │ win32.PetWindow│               │   │ app.html (dashboard, 5 views)  │
   │ GDI layered win│               │   └────────────────────────────────┘
   │ (main thread)  │               │
   └───────┬────────┘               │
           │                        │
   ┌───────▼────────────────────────▼─────────────┐
   │  DATA PLANE  ~/.opencode/pet  (store.py)      │
   │  config.json   ← cross-process, byte-locked   │
   │  wellbeing.json  (pet-writer, retried reads)  │
   │  focus.json      (pet-writer + api tag writes)│
   │  status-*.json   (external plugin writer)     │
   │  activity-<petId>.jsonl (pet-writer, append)  │
   └───────────────────────────────────────────────┘
```

## 2. Process model

| Process | Threads | Responsibilities |
|---|---|---|
| **pet** (`main.py` default) | main: window message pump (clicks/drag/hotkeys, `win32.pump`) · render_loop: `update_activity()` (2 Hz gate) + `loop()` at 30 FPS · watcher: `ReadDirectoryChangesW` on PET_DIR (0.15 s settle, 2 s fallback poll, 30 s prune) · tray: pystray daemon | owns the pet, all growth/memory/chrono/embody/ritual/barter/alert/presence logic, all file writers except config-merge from the control side |
| **control** (`main.py --control` → `web.run_control`) | pywebview window (980×680, min 860×600) + preview pre-warm thread | hosts `ControlApi` as `js_api`; talks to the pet ONLY via config.json + one-shot commands; no GDI, no mutex |
| **--web** (`main.py --web [--port N] [--pet-dir DIR]`) | `ThreadingHTTPServer` on 127.0.0.1 | serves the REAL app.html with the fetch `_WEB_SHIM` bridging `window.pywebview.api` onto `ControlApi`; port printed as `OPENCODE_PET_WEB_PORT=NNNN`; same UI/backend/data as the desktop control |
| **plugin** (external, outside repo) | — | writes `status-<id>.json` for each OpenCode session <UNVERIFIED: plugin location/payload beyond consumed fields> |

Boot order in the pet process: `PetEngine` init → show window →
`update_sessions(read_status())` (pre-existing sessions) → tray →
`spawn_control()` → watcher + render threads → `win.pump()` (main thread
blocks here).

## 3. Threading

- **Single writer per file** where possible: wellbeing.json and
  activity jsonl are written only by the pet engine thread
  (`_save_wellbeing`, `_log`), so no lock is needed there.
- **config.json is multi-writer** (pet `save_config` + control
  `save_config`/`_cmd`) → serialized by `store._config_lock`
  (see §4). All callers go through `store.save_config` or the
  `_cmd`/`_clear_command` locked helpers — never a bare `open(w)`.
- **focus.json is multi-writer** (engine `_save_focus_state` and
  `api.set_focus_tag`). Both replace the whole dict; the engine re-reads
  the authoritative `tag` via `_focus_tag_now()` at completion, so a
  dashboard tag can't be clobbered. No lock — writes are whole-file and
  the loss window is a stale tag only.
- **Render thread safety**: `_build_frame_cache` builds into a local dict
  and swaps atomically; `_load_sheet` runs in the same thread as the
  render loop.
- Test seam: OS activity (`last_input_ms`, `foreground_app`, `cursor_pos`)
  is resolved through the `desktop.main` namespace at call time so the
  suite can monkeypatch it.

## 4. Cross-process file locking (config.json)

```
store._config_lock() (context manager):
  1. module threading.Lock          # serializes THIS process
  2. os.open(CONFIG_FILE, O_RDWR|O_CREAT)
  3. msvcrt.locking(fd, LK_NBLCK, 1)  # byte-range lock, non-blocking,
     retried 50 × 20 ms               # serializes across processes
  4. read/write THROUGH the lock-holding fd
     (_read_locked_fd / _write_locked_fd: seek + read / truncate + write
     + fsync)  — Windows refuses reads/writes of a locked region from a
     DIFFERENT handle (ERROR_LOCK_VIOLATION), so a plain open() inside the
     lock would silently fail
  5. unlock + close + release thread lock
lock failure -> degrade to thread lock only (never block forever);
reads retry 3× on transient violations (CONFIG_READ_RETRIES)
```

Windows-specific gotchas handled: byte-range locks conflict even between
two handles in the same process (hence the thread lock); LK_LOCK can stall
~10 s (hence LK_NBLCK + retry).

## 5. Event / data flows (summary map)

```
status-*.json ──watcher──> update_sessions ──> engine state/emotion/XP
config.json   ──watcher──> config_watch ─────> pet switch, walk, breaks,
                                                chimes, goal, topmost,
                                                one-shots (focusStart/
                                                focusStop/barterPay/
                                                breakSnooze/hidePet/
                                                showPet/quit) — each
                                                cleared after apply
OS activity (2 Hz) ──────> update_activity ───> bubbles, nudges, focus
                                                tick, wellbeing accrual,
                                                goal/wake/memory/epoch/
                                                chrono/embody/ritual/
                                                barter/alert/presence
api polls (JS) ──────────> ControlApi ────────> store reads + one-shots
```

## 6. Extension guides

### 6.1 Add an API method (3 places + parity test)

1. `desktop/api.py` — implement the method on `ControlApi` AND append its
   name to `_WEB_METHODS` (the `--web` shim generates the fetch client
   from this list).
2. `tests/test_spec_contract.py` — add the name to `ALL_METHODS` (this IS
   the parity test: it asserts `_WEB_METHODS == ALL_METHODS`, that
   `ControlApi` implements all of them, and that `app.html`/`control.html`
   never call anything outside the list).
3. Call it from the UI: `window.pywebview.api.<name>(...)` via the
   `whenBridge()` helper (both HTML files). If it's a browser no-op, add
   to `_WEB_NOP`; if it's `quit`-like, special-case in `web.py`.
4. `python tests/run_all.py` (pytest + frontend checks + optional Chrome
   self-test) — all three contract tests must stay green.

### 6.2 Add a new activity-log kind

1. Emit it with `self._log("myKind", **fields)` in `engine.py` (append
   JSON line to `activity-<petId>.jsonl`).
2. Consume it where needed with the same `json.loads(line)` +
   `e.get("kind") == "myKind"` pattern used by `_read_memory_events`,
   `_errors_today`, `_state_flap_median`, `get_memory_lane`, `get_alerts`.
3. If the dashboard should show it, expose via a ControlApi getter (or a
   field on an existing one) and render it in `app.html`.
4. Add a fixture-driven test in `tests/` (log file is per-pet id —
   `sprites.PETS[petIdx]["id"]`).

### 6.3 Add a config key

1. Give it a default in `store.load_config()` (the merge fills it in for
   old configs — the file itself never needs migration).
2. Apply it on the pet side in `engine.config_watch()` if it changes
   behavior live (mirroring the P9 toggle pattern) and/or read it in the
   relevant `_init_*`.
3. Surface it: `get_config` returns the whole merged config, so the
   control window reads it automatically; write it via `save_config` (or
   one-shot `_cmd` + `_clear_command` for commands).
4. Document in `docs/TRD.md §2.1` table.

### 6.4 Add a new day-state (embodiment)

1. Add the state to `store.day_health` priority chain + `EMBODY_AURA` +
   `EMBODY_LABELS`.
2. Threshold constants go in `store.py` (like `EMBER_SATURATED`).
3. No engine change needed — `_embody_tick` re-derives from `day_health`
   and `get_day_health` shares the same pure rule, so the pet and the
   dashboard card agree by construction.

## 7. Build / packaging notes

- `desktop/build.bat` → PyInstaller spec `OpenCodePet.spec`; `_MEIPASS`
  resolution in `sprites.sprites_dir` / `web._file` keeps assets working
  frozen.
- `_ambient.css` and `_focus-ritual.js` are additive enhancements; the
  pywebview bridge contract is untouchable (see `DESIGN.md` craft floor).

## 8. Verification story

- `tests/run_all.py`: pytest (`tests/`, incl. `test_spec_contract.py`),
  frontend checks (`check_frontend.py`), headless Chrome UI self-test of
  the REAL app.html via `--web` (no mocks; `tests/web_bridge.py` drives the
  HTTP bridge).
- Engine unit coverage: state machine, config/status, goal, pomodoro,
  memory, rituals, barter, chronotype, embodiment, alerts, presence,
  voice/lane, web bridge, stress/hardening, spec contracts.
