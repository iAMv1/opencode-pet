# OpenCode Pet — Application Flows (APP_FLOW.md)

Verified user journeys across the pet process, control window
(`control.html`), and dashboard (`app.html`). Timings from code constants.

## 1. Boot / wake dream

```
launch main.py
  ├─ single-instance mutex (zombie mutex tolerated if pet window dead)
  ├─ PetEngine.__init__  -> load config / sheet / focus / wellbeing
  ├─ show pet window (workarea)
  ├─ prune stale status-*.json (5 min)
  ├─ update_sessions(read_status())   # pre-existing sessions before watcher
  ├─ tray icon (pystray thread)
  ├─ spawn_control()                  # control window in its own process
  ├─ watcher thread  (ReadDirectoryChangesW -> 2 s fallback poll)
  └─ render_loop (30 FPS) + pet window message pump (main thread)

first tick while OS active:
  _try_dream: wakeDate != today AND wellbeing has a completed day
    -> bubble "I dreamt of terminals… yesterday: 5.2h. VS Code led the way."
    (deterministic; store.build_dream)  + log "dream"
  else stay quiet, retry next wake

after >60 s idle then active again (4 h cooldown, wakeIdleAt):
  bubble "Back! I kept the seat warm." + log "wake"
```

## 2. Daily loop

```
OS active ──> track_app_time (2 Hz): apps[fg] += dt; hourToday[hour] += dt;
              work-time -> memory budget; active seconds -> barter bank
              (flush whole minutes, max 1/min)
   │
   ├─ goal_tick (once/day, lastGoalDate guard): non-idle total >= goalMin*60
   │     -> +20 XP, bubble "Daily goal met!", cast, log "goal", embody force
   ├─ focus_tick (when session live, ~2 Hz): grows; wilt on app-switch or
   │     45 s idle; complete at target -> +50 XP, pomodoro tick, chime,
   │     cast, embody force
   ├─ memory_tick: work-time budget (60 min, jittered) -> recall bubble
   │     (real past event, no XP), max 3/day
   ├─ epoch_tick: threshold crossed -> once-ever celebration (+25 XP)
   ├─ chrono_tick (once/day): 3 data days -> metamorph; weekly drift
   ├─ embody_tick (30 s + force): day state -> aura/mood
   ├─ ritual_tick: derive ≤3 rituals/day; live progress; +15 XP each;
   │     22:00 quiet day-close
   ├─ barter_tick: bank flush; daily offer ask when bank covers next stage;
   │     pay -> -bank, +stage, +20 XP, ceremony
   ├─ alert_tick (≤1/day): churn > idle-warn > Sunday review
   ├─ typing_tick / cursor_tick / perch_tick (P9 reactions)
   └─ break_nudge (breakMin) / stretch_nudge (stretchMin) run earlier
```

Break nudge detail (with snooze):
```
breakMin*60 of continuous OS activity ->
  snooze armed? -> "Snoozed N min — see you at HH:MM", re-arm clock,
                   log "breakSnooze", chime
  else -> "Time for a break — stretch!", tired mood, log "break", chime
idle resets the streak clock
```

## 3. Focus session lifecycle

```
dashboard Focus view:  set tag (fsTagIn -> api.set_focus_tag)
                       Start (api.start_focus(min)) -> config.json focusStart
                       Stop  (api.stop_focus)       -> config.json focusStop

engine.config_watch (watcher, ~0.15 s):
  focusStart -> start_focus(min): log focusStart; sprout grows while
                os_app == session app
  mid-session app-switch / 45 s idle -> wilt (focusWilt, "Hey, you left!")
  target reached -> focusDone, +50 XP, pomodoro tick, cast, chime
control Stop -> stop_focus(): focusEnd (no bonus) or focusWilt if wilted

dashboard ring: get_focus_state -> progress recomputed live
  (store.focus_progress), rAF-smoothed by _focus-ritual.js (seed/sprout/
  leaf/bloom/wilt phases; "Focusing in <app>" chip; break ritual on bloom)
```

## 4. Pomodoro cycle

```
focusDone -> _pomo_tick:
  day changed (pomoDate) -> count = 0
  count += 1; long = (count % 4 == 0)
  bubble "Pomodoro N done! Take a [long|short] break"  (wins over XP line)
  config: pomoCount, pomoDate, pomoShort, pomoLong
dashboard: get_pomo_state -> count, nextIsLong, lengths (rail card)
```

## 5. Metamorphosis (chronotype)

```
collect hourHistory daily (>= 3 days needed)
once/day check:
  larval + enough days -> chronotype_class(profile):
     erratic (>=20 hours with data, or 2 far masses) first
     then strongest band of night 0-6 / lark 5-12 / midday 10-16
     >= 35% share, else balanced
  -> one-time metamorph: chronoDate, +50 XP, cast,
     bubble "Nocturnal genes detected — I see your 3 AM self."
     log "metamorph", chime, new aura window
weekly re-review (chronoWeekDate + 7 days):
  class changed -> "My genes are drifting…" + log "drift"
  else just advances the review date
dashboard: get_chronotype -> genes/fingerprint/peak/nextReview/readout
```

## 6. Breaks / stretch (already covered by §2 — user-facing summary)

- Break nudge: after `breakMin` continuous work; snooze via control window
  button (`save_config({breakSnooze: 5})`) or one-shot.
- Stretch: after `stretchMin` unbroken work, +2 XP, max 1/30 min.

## 7. Dashboard views (app.html)

```
sidebar: Dashboard | Focus | Wrapped | Companion | Pets & Behavior

Dashboard:  sessions feed (state filter chips, search, sort) + rail cards
            [goal ring | pomodoro | memory | memory lane | chronotype |
             day-body | rituals | barter] + pet rail + prev/next/hide pet
Focus:      live focus session card (ring/tag/start/stop) · 7-day history
            bars · insights (week vs prev, delta) · activity log (80 lines)
            · app time today + total
Wrapped:    week summary card + copy-share · 30-day sparkline · week apps
Companion:  pet profile (level/XP/stage/mood/streak) · 90-day heatmap ·
            growth milestones · streak & sessions · best focus hours
            (peaks + span label) · today's live total
Pets & Behavior: pet picker (7) · walk % · always-on-top · visible ·
            break on/off+min · stretch on/off+min · chimes
```

## 8. Control panel toggles (control.html)

```
pet picker grid (radio; keyboard arrows/Home/End)   -> save_config petIdx
walk slider 0-100                                   -> save_config walk
always-on-top switch                                -> save_config alwaysOnTop
show/hide pet switch                                -> api.show_pet/hide_pet
break reminder switch + minutes + "Snooze 5 min"    -> save_config breakMin / breakSnooze
stretch reminder switch + minutes                   -> save_config stretchMin
chimes switch                                       -> save_config chimes
reactTyping / reactCursor / perchChatter /
  agentMirror / wanderIdle switches                 -> save_config (5 keys)
Escape / X: hide window (api.hide_control); Quit: confirm -> api.quit
save: 350 ms debounce; config re-read every 5 s (tray actions reflected);
demo mode (no bridge) renders fallback pets, saves nothing
```

## 9. Rituals daily rhythm

```
midnight -> derive_rituals (from yesterday + chrono + hour profile):
  guard_hour (sharpest hour, 30 min) > beat_yesterday > break_the_idle >
  night_guard (night-owl) / first_light (lark); max 3
persist ritualList/ritualDate; live progress all day (ritual_progress);
completion -> +15 XP + bubble + log "ritual" (once, ritualDone)
22:00, anything unfinished -> "Tomorrow's a new day" (no penalty)
dashboard: get_rituals -> persisted list + live current/done
```

## 10. Barter lifecycle

```
active seconds -> barterBank (whole minutes)
bank >= next offer cost (300/600/900/1500) & no offer today:
  bubble "I can shift form — trade 300 focus-minutes?"  log "barterAsk"
dashboard shows confirm (get_barter_state.offered)
barter_pay -> engine._barter_pay: -bank, +stage, +20 XP,
              "Shift complete: Perk up ears ✨", cast, log "barter"
offer unconfirmed 3 days -> quiet expiry (bank kept), re-ask tomorrow
stage > 0 -> periodic radiance shimmer (90 s)
```

## 11. Lifestyle alerts (≤1/day)

```
churn:  >= 20 state transitions today with median segment < 60 s
        -> "You're flitting between tasks every few seconds — I'll keep pace"
idle-warn: >= 60% idle of >= 30 min tracked, after 15:00
        -> "Half the day is fog — save it while it's yours"
week_review: Sunday >= 20:00 -> "The week closed at 12.4h — next week
        I'll guard your sharpest hour." (store.week_end_review)
guards: alertDate once/day; defers while a celebration bubble is live;
logged kind "alert" (dashboard get_alerts reads it back)
```

## 12. Companion presence (P9)

```
typing: input fresh (<2 s) for 30 s -> mood busy; 10%/2 min bounce cast
cursor: within 150 px for 5 s -> glance (thinking flip 2.5 s), 1/3 min
perch:  foreground app changed -> perch line (1/30 min); 20% step toward it
mirror: thinking -> agent-mirror lines; error -> concern (1/15 min);
        success -> happy + cast + log "agentSuccess"
wander: OS idle >= 2 min -> waiting pose (sits); stays put when idle
toggles: reactTyping, reactCursor, perchChatter, agentMirror, wanderIdle
```
