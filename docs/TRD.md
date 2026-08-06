# OpenCode Pet — Technical Requirements Document (TRD)

Companion to `PRD.md` / `APP_FLOW.md` / `ARCHITECTURE.md`. Every name in
this document was verified against the code on
`feature/productivity-enhancement-sprint`. Items that could not be verified
are flagged `<UNVERIFIED: ...>`.

## 1. Architecture (modules + roles)

| Module | Role |
|---|---|
| `desktop/main.py` | Entry point. Boots `PetEngine`, watcher thread, render thread, tray, spawns control process; single-instance mutex; dispatches `--control` / `--web` modes; re-exports the public API surface used by tests |
| `desktop/engine.py` | `PetEngine`: physics, sprite slicing, state resolution, focus/growth, memory/wake/epoch, chronotype, embodiment, rituals, barter, alerts, presence. Owns the pet window loop |
| `desktop/store.py` | Data layer: paths, config/status/wellbeing persistence, cross-process file locking, ALL pure shared rules (streak, dream, lane, voice, rituals, barter, chronotype, day-health, epochs, focus progress) |
| `desktop/api.py` | `ControlApi` — the JS bridge contract (pywebview `js_api`); runs in the control/`--web` process; talks to the pet via config.json + one-shot commands |
| `desktop/web.py` | `--web` HTTP bridge (`run_web`), control-app launcher (`spawn_control` / `run_control`), HTML asset resolution, `_WEB_SHIM` |
| `desktop/win32.py` | ctypes bindings, GDI layered `PetWindow`, OS activity (`last_input_ms`, `foreground_app`, `cursor_pos`), `read_dir_changes` watcher, workarea, hotkeys |
| `desktop/sprites.py` | Pet registry (`PETS`, 7 pets), state rows (`PET_STATES`), default state map, preview strips (base64 data URIs) |
| `desktop/sounds.py` | Native `winsound` chimes, config-gated, always safe |
| `desktop/tray.py` | pystray system-tray icon + menu (show/hide/focus/control/pets/quit) |
| `desktop/app.html` | Dashboard UI (single file: CSS+JS inline). 5 views: dash/focus/wrapped/companion/pets |
| `desktop/control.html` | Control-window UI (single file): pet picker + behavior settings |
| `desktop/_ambient.css`, `desktop/_focus-ritual.js` | Design-token CSS and the additive focus-ritual enhancement (`_focus-ritual.js` reads the focus card's DOM, zero edits to app.js; injected by build) |

## 2. Data layer

Base dir: `~/.opencode/pet` (`store.PET_DIR`). Redirectable via
`--web --pet-dir DIR` (`web._apply_pet_dir` repoints the globals).

### 2.1 config.json — ALL keys (verified)

Defaults from `store.load_config()` (missing keys merged with defaults on
read; runtime-written keys added on save):

| Key | Default | Meaning |
|---|---|---|
| `petIdx` | 0 | current pet index into `sprites.PETS` |
| `alwaysOnTop` | true | pet window topmost |
| `walk` | 100 | walking activity % (0–100) |
| `breakMin` | 50 | break-nudge threshold minutes (0 = off) |
| `goalMin` | 120 | daily focus goal minutes (`store.GOAL_DEFAULT_MIN`) |
| `lastGoalDate` | "" | last day the goal was met (once/day guard) |
| `stretchMin` | 45 | stretch-nudge threshold minutes (0 = off) |
| `chimes` | true | native chimes gate |
| `pomoMin` / `pomoShort` / `pomoLong` | 25 / 5 / 15 | pomodoro session/break lengths |
| `pomoCount` / `pomoDate` | 0 / "" | daily completed pomodoros + their day |
| `wakeDate` | "" | last day the wake dream ran |
| `wakeIdleAt` | 0 | epoch of last long-idle wake greeting |
| `memoryMin` / `memoryMax` | 60 / 3 | work-minutes between recalls / max recalls per day |
| `memoryDate` / `memoryCount` | "" / 0 | recall budget day + counter |
| `epochFlags` | [] | epoch ids already celebrated (once-ever) |
| `chronoType` | "larval" | night_owl/lark/midday/erratic/balanced/larval |
| `chronoDate` / `chronoWeekDate` | "" / "" | one-time metamorph date / last weekly review |
| `ritualDate` / `ritualList` / `ritualDone` | "" / [] / [] | today's rituals (persisted list) + completed ids |
| `ritualCloseDate` | "" | last quiet day-close |
| `barterBank` / `barterStage` / `barterOfferDate` | 0 / 0 / "" | banked focus minutes / stages done / last offer day |
| `alertDate` | "" | last lifestyle-alert day (once/day guard) |
| `reactTyping` / `reactCursor` / `perchChatter` / `agentMirror` / `wanderIdle` | true | P9 presence toggles |

Runtime-written (not in defaults): `xp`, `level`, `mood`, `focusMin`
(`_save_growth`), `petVisible` (`set_visible`). One-shot command keys
consumed+cleared by `engine.config_watch`: `quit`, `hidePet`, `showPet`,
`focusStart` (int minutes), `focusStop`, `barterPay`, `breakSnooze` (int
minutes).

Reads are retried (3×, 10 ms) against transient lock violations
(`CONFIG_READ_RETRIES`).

### 2.2 wellbeing.json

```json
{
  "date": "YYYY-MM-DD",          // day the live maps belong to
  "apps": { "VS Code": 1234, "Idle": 567, ... },   // TODAY's live per-app seconds
  "history": { "2026-08-05": 7200, ... },          // past-day totals, pruned 30d
  "appHistory": { "2026-08-05": {app: secs}, ... },
  "hourToday": { 9: 1234, ... },                   // today's per-hour seconds
  "hourHistory": { "2026-08-05": {9: 1234}, ... }  // per-day per-hour
}
```

Written every `WELLBEING_SAVE_INTERVAL` (20 s) while the pet runs and at
day rollover; pruned to 30 days (`HISTORY_WINDOW_DAYS`). `read_wellbeing()`
is the single shared read path (3× retry). `_fold_today` folds today's live
`apps` total into history copies for analyses so fresh sessions count
immediately.

### 2.3 focus.json

```json
{ "active": false, "startedAt": 0.0, "targetMin": 25, "wilted": false,
  "app": "", "progress": 0.0, "tag": "" }
```

Written by the pet on start/wilt/stop/complete; `tag` also written directly
by `ControlApi.set_focus_tag`. Progress is recomputed live via
`store.focus_progress` (not trusted from the file snapshot).

### 2.4 status-*.json (per session, written by the OpenCode server plugin)

Consumed fields: `sessionID`, `state` (busy/thinking/error/success/
celebrating/waiting/retry/idle…), `title`, `toolLabel`, `message`,
`updatedAt` (ms), `direction` (left/right).
<UNVERIFIED: writer payload beyond these fields> — the plugin lives outside
this repo.
Rules: `stale` when `updatedAt` older than `STALE_MS` (25 s); files older
than `STATUS_PRUNE_MS` (5 min) are deleted by the engine. `current_app_session`
falls back to the OS foreground app ("desktop-activity", state busy) when no
session file is fresh.

### 2.5 activity-<petId>.jsonl — event kinds (all 33, verified)

One JSON line per event `{"t": epoch, "kind": ..., ...}`; one pet, one
memory (log path uses the CURRENT pet's id; a pet switch logs `petSwitch`
into the NEW pet's log).

| kind | extra fields | source |
|---|---|---|
| `state` | state, sessionID | `_log_activity` on top-session transition |
| `tool` | tool, sessionID | first-seen tool label |
| `active` | app | 1/min while OS active |
| `focusStart` | targetMin, app | `start_focus` |
| `focusDone` | minutes, tag | completion (engine + control stop) |
| `focusEnd` | minutes, completed | manual stop |
| `focusWilt` | minutes / app, fromApp / reason | app-switch or idle wilt |
| `levelUp` | level | XP threshold crossed |
| `goal` | goalMin | daily goal met |
| `dream` | — | wake dream bubble |
| `wake` | idleSecs | long-idle greeting |
| `memory` | template | recall (streak_record/streak_match/session_record/pet_switch/first_of_day/session_count/busy_day/quiet_week) |
| `epoch` | id, name | epoch crossing |
| `metamorph` | to, species, genes | chrono metamorphosis |
| `drift` | to, fromType | weekly chrono drift |
| `embody` | state, intensity | day-state change |
| `static` | errors | storm error-static bubble |
| `ritual` | id, name | ritual completion |
| `dayclose` | pending | 22:00 quiet close |
| `barter` | stage, cost, name | trade executed |
| `barterAsk` | stage, cost | offer asked |
| `petSwitch` | toIdx | pet changed (logged by new pet) |
| `poke` / `jump` | — | click/double-click |
| `typingBurst` | secs | sustained typing bounce |
| `cursorLook` | px, py | cursor dwell glance |
| `perch` | app | perch-chatter line |
| `wanderSide` | app | pet steps toward app |
| `break` | mins | break nudge |
| `breakSnooze` | mins | snooze armed |
| `stretch` | mins | stretch nudge |
| `alert` | alert, line | lifestyle alert (churn/idle_warn/week_review) |
| `agentError` | sessionID | agent-error concern |
| `agentSuccess` | sessionID | agent-win mirror |

## 3. pywebview bridge contract

`_WEB_METHODS` in `desktop/api.py` — **exactly 32 methods** (guarded by
`tests/test_spec_contract.py`, which asserts `_WEB_METHODS == ALL_METHODS`
and that both HTML files call only these):

```
get_config, get_previews, get_sessions, get_logs,
get_wellbeing, get_wellbeing_history, get_wellbeing_insights,
get_focus_state, start_focus, stop_focus, set_focus_tag, get_pet_profile,
get_goal_state, get_pomo_state, get_weekly_wrapped, get_week_apps,
get_focus_peaks, get_memory_state, get_chronotype, get_day_health,
get_rituals, get_barter_state, barter_pay,
get_memory_lane, get_alerts,
save_config, next_pet, prev_pet, hide_pet, show_pet,
hide_control, quit
```

Semantics:

- `get_config` → config merged with `pets` (names), `petVisible`, `petName`,
  live `state` (status file or OS fallback).
- `get_sessions` → ACTIVE sessions only (busy/thinking/error/retry/
  celebrating, non-stale); OS fallback when empty.
- `get_logs(limit=200)` → last N activity lines for the current pet.
- `get_wellbeing` → today's per-app seconds ≥ `APP_MIN_SECS` (30 s),
  top `TOP_APPS_LIMIT` (8).
- `get_wellbeing_history(days=7)` → contiguous zero-filled day series,
  clamp 1..`HISTORY_MAX_DAYS` (90; heatmap uses 90, sparkline 30).
- `get_wellbeing_insights` → week/prevWeek totals, deltaPct, bestDay,
  todaySeconds, topApp, `voice` (0–4 lines).
- `get_focus_peaks(days=7)` → 24 hour buckets, best/runnerUp hour,
  spanLabel (mornings/afternoons/evenings/nights/overnight), clamp 30.
- `get_focus_state` → focus.json + live progress + tag.
- `start_focus(minutes)` / `stop_focus()` → one-shot commands via
  `_cmd("focusStart"|"focusStop")`; the PET owns the session.
- `set_focus_tag(tag)` → writes `tag` into focus.json directly (max 40 ch).
- `get_pet_profile` → level, xp, xpNext, xpPct, mood, streak (via
  `store.streak_from_history`), evolution stage.
- `get_goal_state` → goalMin, todaySeconds, met, streak (goalMin*60
  threshold).
- `get_pomo_state` → count, nextIsLong, pomoMin/Short/Long.
- `get_weekly_wrapped` → week summary + share text; `get_week_apps` → per-app
  week totals (≥60 s, top 8).
- `get_memory_state` → wakeDate, dream (same `build_dream` as the pet),
  memoryCount/Max, epochFlags chips. `get_memory_lane` → 7 narrated days
  (same `build_lane` as the pet).
- `get_chronotype` → chronoType, genes manifest, fingerprint hours,
  activeHours, peakHour, dataDays, neededDays, nextReview, readout.
- `get_day_health` → state/label/intensity/since (same `day_health` rule;
  `since` from the last matching `embody` log line).
- `get_rituals` → today's persisted `ritualList` (falls back to
  `derive_rituals` when the engine hasn't run today) + live progress.
- `get_barter_state` → bank, stage, nextOffer, offered (today's standing
  offer). `barter_pay` → one-shot `barterPay`; the pet executes the trade.
- `get_alerts(limit=3)` → today's alert line + recent `alert` events.
- `save_config(conf)` → merge-save under the cross-process lock (never drops
  petVisible/pending commands).
- `next_pet`/`prev_pet` → save `petIdx` (pet process applies via watcher).
- `hide_pet`/`show_pet` → one-shot commands; `hide_control` → hide window
  only. `quit` → `_cmd("quit")`, brief grace sleep, `sys.exit(0)`.

**`--web` differences** (`web.py`): `_WEB_NOP = {"hide_control"}` (no-op —
the tab IS the UI); `quit` writes the one-shot command but never exits the
server. Requests must be same-origin JSON POST to `/rpc` with Host
`127.0.0.1:*`/`localhost:*`, body ≤ 1 MB (`WEB_MAX_BODY`); unknown methods →
400.

## 4. Event flows

### 4.1 Engine tick path (`render_loop`, 30 FPS)
```
render_loop (30 FPS):
  update_activity()      # 2 Hz gate (0.5 s): OS input/app/cursor, bubbles,
                         # break/stretch nudges, focus tick, mood, track_app_time,
                         # goal, wake, memory, epoch, chrono, embody (30 s),
                         # rituals, barter, alerts (60 s), typing, cursor, perch
  loop()                 # every tick: spawn, physics, frame advance, present
  present: content change -> UpdateLayeredWindow; position-only -> SetWindowPos
```

### 4.2 Watcher thread
```
watcher:
  read_dir_changes(PET_DIR)  # ReadDirectoryChangesW, 65 KB buffer
    on change: sleep 0.15 s -> update_sessions(read_status()) + config_watch()
               + prune (30 s cadence)
  on failure: fallback poll every 2 s; after 30 s -> _prune_status()
```

### 4.3 API polls (app.html)
sessions 1.5 s · config 2.5 s · activity 3 s · wellbeing 5 s · history/
insights 15 s · profile/goal/pomo/memory/chrono/day-body/rituals/barter 10 s
· lane 15 s · wrapped 20 s. `_focus-ritual.js` drives the focus ring via
rAF between polls (skipped under `prefers-reduced-motion`).

### 4.4 One-shot command flow (control → pet)
```
control JS -> api.save_config({breakSnooze:5}) -> config.json (locked)
watcher sees change -> engine.config_watch() -> applies + _clear_command(key)
```

### 4.5 Session flow
```
plugin writes status-<id>.json -> watcher -> update_sessions -> engine state/
bubbles/XP; stale > 25 s -> "stale"; missing fresh + OS active ->
current_app_session() fallback ("desktop-activity")
```

## 5. Constants of note (all in store.py / engine.py)

- Timeouts: `STALE_MS` 25 s, `ACTIVE_MS` 30 s, `STATUS_PRUNE_MS` 5 min,
  `SLEEP_GAP_SECS` 60 s (laptop-sleep guard — a longer tick delta is a gap,
  never credited).
- Goal: `GOAL_DEFAULT_MIN` 120; XP goal bonus 20.
- Streak: `STREAK_MIN_SECS` 30 min, lookback 400 days; today-below doesn't
  break the chain.
- Focus: `FOCUS_DEFAULT_MIN` 25, max 180; wilt after 45 s idle/app-switch;
  +50 XP on completion.
- XP ladder: base 100, +50/level; tool earn 2, complete 5, stretch 2,
  goal 20, streak 25 (every 5 days), epoch 25, metamorph 50, ritual 15,
  barter 20.
- Pomo: long break every 4th completed session.
- Memory: 60 min work-time budget (jittered), 3/day cap.
- Chrono: 3 days min, 7-day review, 30-day window, 600 s/hour active floor,
  35% band share, 20-hour coverage → erratic.
- Embodiment: quiet <600 s; fog >40% idle (ramp 60%); bloom 1 h focus or
  goal; ember ≥4 saturated hours (ramp 6); flow ramp 8 h.
- Rituals: max 3/day; guard 1 h avg best hour; night window 0–6; lark 5–12;
  idle ratio 30%; day-close 22:00.
- Barter: 300/600/900/1500 min; expiry 3 days.
- Alerts: churn ≥20 events with median <60 s; idle ≥60% of ≥30 min day after
  15:00; week review Sunday ≥20:00.
- Presence: typing <2 s input for 30 s; cursor 150 px for 5 s; perch 30 min
  cooldown; wander-sit 2 min idle; agent-error 15 min cooldown.

## 6. Constraints

- Windows 10/11 only: GDI layered window (per-pixel alpha), `msvcrt` byte
  locks, `winsound`, `ReadDirectoryChangesW`, `GetLastInputInfo` (DWORD
  wrap masked).
- Python 3.11+; `PIL`, `pywebview`, `pystray` (see
  `desktop/requirements.txt`).
- Pet process never hosts a browser; control process never touches GDI.
- The pywebview bridge is the untouchable contract (`DESIGN.md`): never
  rename an element id, aria contract, or JS function the bridge uses.
- Corrupt data must never kill the render loop: every file read on the
  render path is guarded (see `_load_wellbeing` numeric filtering,
  `read_wellbeing` retries, `read_status` per-file try).
- Cross-process writes to config.json are serialized (see
  `ARCHITECTURE.md §4`); wellbeing.json is single-writer (pet process only).
