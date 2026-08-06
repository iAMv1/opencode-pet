# OpenCode Pet — Product Requirements Document (PRD)

> Companion document to `TRD.md` (technical), `APP_FLOW.md` (user flows),
> `ARCHITECTURE.md` (system design). Describes the product as built on
> branch `feature/productivity-enhancement-sprint`. All feature behavior here
> is verified against `desktop/*.py`, `desktop/app.html`, `desktop/control.html`.

## 1. User

A solo developer who spends 4–12h/day in a terminal, an editor, and an
agentic coding tool (OpenCode). They:

- Are already self-aware about focus but lack a **felt**, persistent record of it.
- Resist dashboards that punish or gamify (streaks-as-shaming, badges-as-spam).
- Want a desktop companion that reflects reality back — "someone noticed" —
  without asking for setup or configuration.
- Leave their machine for long stretches (meetings, sleep) and come back to it.

The pet is ambient. It never interrupts; it accompanies.

## 2. Problems solved

| Problem | How the product solves it |
|---|---|
| Focus data exists but is invisible | A living pet on the screen whose body, aura, and mood ARE the day's data (data-embodiment, chronotype aura, status dot) |
| Streaks/badges punish inconsistency | Honest records: no negative mechanics, quiet day-close, expired barter offers never lose banked minutes |
| Work history is abstract | Episodic memory recalls, the wake dream, memory lane, and pet-voice insights narrate REAL logged events |
| Users don't know when their best work happens | Chronotype metamorphosis + focus peaks surface the hour fingerprint from hourHistory |
| Long sessions burn out | Break nudges, stretch reminders, snooze, pomodoro cycle — all configurable, all gentle |
| Motivation after a run of errors/idle | Storm/fog embodiment states, agent-mirror concern lines — the pet empathizes, never scolds |
| Companion apps feel like noise | Attention barter: form stages are TRADED for real banked focus minutes, not bought with a currency |

## 3. Product thesis

**OpenCode Pet is the living biography of your work life.** Everything the
pet says, becomes, and shows is derived from data the user already produces —
session status files, OS foreground activity, focus sessions, per-app/per-hour
time — and rendered as a companion that visibly carries that story. No polling
abstraction over the user's behavior: the pet's form, aura, moods, memories,
and voice are deterministic functions of real records, so the pet can never
disagree with the dashboard, and the dashboard can never disagree with the pet.

## 4. Feature list

Each sprint system: what it is, why it exists, how it reads real data.
Implementation references in `TRD.md`.

### 4.1 Daily focus goal
- **What:** config `goalMin` (default 120 min) of non-idle tracked time per day;
  the pet celebrates once (`lastGoalDate` guard) with XP + bubble + cast flash.
- **Why:** a single felt daily target; one celebration, never nagging.
- **Data:** today's live per-app map (`wellbeing.json apps`) minus "Idle".

### 4.2 Pomodoro cycle
- **What:** each completed focus session = one "tomato" per day (`pomoCount`,
  reset on `pomoDate` change). Every 4th session earns a long break
  (rule: `store.pomo_next_long` — count+1 % 4 == 0). Bubbles
  "Pomodoro N done! Take a [short|long] break".
- **Why:** bounded session structure without a timer UI.
- **Data:** completed `focusDone` events; `pomoMin/pomoShort/pomoLong` config.

### 4.3 Breaks, snooze, stretch, tags, chimes
- **Break nudge:** after `breakMin` min continuous OS activity, bubble
  "Time for a break — stretch!" + tired mood + low chime. Cooldown 5 min.
- **Snooze (one-shot `breakSnooze` command):** defers the next nudge N min
  and re-arms the streak clock; logged `breakSnooze`.
- **Stretch nudge:** `stretchMin` min unbroken work → "Stretch! Neck + shoulders",
  +2 XP, max 1 per 30 min (`STRETCH_COOLDOWN_SECS`).
- **Tags:** `set_focus_tag` tags the CURRENT focus session (written to
  focus.json `tag`, max 40 chars, next session starts untagged).
- **Chimes:** `chimes` config gates `sounds.play(kind)` (start/complete/break/stretch).

### 4.4 Episodic memory + wake dream ritual
- **Memory bubbles:** after `memoryMin` (default 60) min of WORK time
  (jittered ×0.75–1.25), the pet recalls a REAL past event from its own
  activity log: streak record ("never done before" vs "matches your best"
  via `best_streak`), longest session, pet-switch count, first focus of the
  day, weekly session count. Max `memoryMax` (3) per day, counter in config
  (`memoryCount/memoryDate`) so restarts can't reset it. No XP — bubble +
  brief mood shimmer only.
- **Wake dream:** first wake of a new day (`wakeDate` guard) bubbles the
  deterministic digest of yesterday's data (`store.build_dream`): record day,
  deepest day, night-owl hour, idle-heavy, app count, quiet, or plain summary.
  Long-idle greeting after >60 s idle gap, max 1 per 4 h (`wakeIdleAt`).
- **Why:** the pet has a memory; memory is the basis of "biography".

### 4.5 Epoch markers (P4)
- **What:** 8 one-time life-transition markers
  (first_focus, first_week, ten_hour_total, long_day, night_owl, week_streak,
  xp_500, thirty_days). Each fires ONCE (config `epochFlags`), +25 XP, bubble,
  log.
- **Why:** growth milestones are earned from real thresholds, not given.
- **Data:** history days, hourHistory night mass, streak, XP, focus-count.

### 4.6 Chronotype metamorphosis (P5)
- **What:** the pet's species becomes the user's REAL work schedule. After
  ≥3 days of hourHistory (`CHRONO_MIN_DAYS`), larva metamorphoses into
  night_owl / lark / midday / erratic / balanced (classification:
  erratic-first, then strongest band ≥35% share, else balanced). One-time
  (chronoDate guard), +50 XP, cast, log. Weekly re-review (chronoWeekDate)
  can drift the class (bubble only). Genes are visual: species/color/pattern
  manifest + hour-window aura glow.
- **Why:** "the pet evolves from when you work" — identity from data.
- **Data:** hourHistory per-hour averages, active hours, band shares.

### 4.7 Data-embodiment (P6)
- **What:** the pet's BODY is the dashboard. `store.day_health` derives one
  state from today's live data, priority storm > quiet > fog > bloom > ember
  > flow, with intensity 0–1; aura overlay + mood hint (fog → tired).
  Re-derived every 30 s + forced on goal/focus events.
- **States:** storm (errors/wilt, red static aura + one "static" bubble per
  10 min), quiet (<10 min tracked — pet sleeps), fog (>40% idle — droops),
  bloom (goal met or ≥1 h continuous focus), ember (≥4 saturated hours),
  flow (steady).
- **Why:** the pet looks like your day; no meters, no guilt.

### 4.8 Personal rituals (P7)
- **What:** up to 3 rituals/day derived from the user's OWN history
  (`store.derive_rituals`), priority: guard_hour (historical best hour,
  target 30 min), beat_yesterday (match yesterday's total), break_the_idle
  (reclaim 2 h after >30% idle day), night_guard (night-owl chrono: 1 deep
  hour 0–6), first_light (lark chrono). Live progress vs today's data
  (`ritual_progress`); each completion +15 XP once (`ritualDone`). Quiet
  day-close at 22:00 ("Tomorrow's a new day") when something went
  unfinished — NO punishment, no XP loss.
- **Why:** rituals are promises the data itself suggests, not canned quests.

### 4.9 Attention barter (P7)
- **What:** banked focus minutes (active seconds flushed to `barterBank` in
  whole minutes, max 1 flush/min) are TRADED for 4 form stages
  (300/600/900/1500 min: ears → whiskers → coat → full form). Offer asks once
  per day when the bank covers the next stage; confirmation via `barter_pay`
  deducts bank, advances stage, +20 XP + ceremony. Unconfirmed offers expire
  after 3 days — bank kept, never punished. Stage glow tiers on the sprite.
- **Why:** the user's attention is the only currency; metamorphosis is
  earned attention, not a points store.

### 4.10 Memory lane + pet-voice insights + lifestyle alerts (P8)
- **Memory lane:** last 7 days, one pet-voice narration per day
  (`store.build_lane`/`day_note`) from that day's real shape: record day,
  night-owl, still day, idle-fog %, pet-switch count, errors, top app.
- **Voice insights:** `get_wellbeing_insights.voice` — up to 4 week
  narrations from real week data: wall-to-wall days, midnight > afternoon,
  idle-fog %, "N hats", the honest candle confession (focus sessions started
  with zero completions — non-punitive), streak praise.
- **Lifestyle alerts:** at most ONE per day (`alertDate` guard), priority:
  task-churn (≥20 state transitions with median segment <60 s), idle-fog
  warning (≥60% idle of a ≥30 min day after 15:00), Sunday week-end review
  after 20:00 (week close + next-week tease). Never interrupts a celebration
  (defers while `attention_until` live).
- **Why:** the pet narrates the biography in its own voice, honestly.

### 4.11 Companion presence (P9)
- **What:** five config-gated reactions to the real workflow:
  - `reactTyping`: sustained input (<2 s since last input for 30 s) → busy
    mood; 10% chance tiny bounce cast, max 1/2 min.
  - `reactCursor`: cursor dwelling within 150 px of the pet for 5 s → glance
    (brief thinking-flip), max 1/3 min.
  - `perchChatter`: foreground-app change → app-aware perch line, max 1/30 min;
    plus 20% chance the pet steps toward the app.
  - `agentMirror`: the pet comments on the USER's agent ("Your agent is
    thinking too — we're both working"); error concern max 1/15 min.
  - `wanderIdle`: after 2 min OS idle the pet sits (waiting pose) instead of
    pacing — an energy save.
- **Why:** companionship from data the pet already reads; nothing new to wire.

### 4.12 Dashboards (app.html)
- Dashboard view: live sessions feed (filter/search/sort), rail cards
  (goal, pomodoro, memory, memory lane, chronotype, day-body, rituals,
  barter), pet rail, prev/next pet, hide pet.
- Focus view: live focus session (sprout ring, tag, start/stop), 7-day
  history, insights, activity log, week-vs-last compare, app time today.
- Wrapped view: "Your Week in Focus" summary + copy-to-clipboard share text,
  30-day sparkline, per-app week breakdown.
- Companion view: pet profile (level/XP/stage), 90-day heatmap, milestones,
  streak & sessions, best focus hours (peaks), today.
- Pets & Behavior view: pet picker + behavior toggles (walk %, always-on-top,
  visibility, break/stretch, chimes) and focus-session controls.
- Polling contract: sessions 1.5 s, config 2.5 s, activity 3 s, wellbeing 5 s,
  history/insights 15 s, profile/goal/pomo/memory/chrono/day-body/rituals/barter
  10 s, lane 15 s, wrapped 20 s.

### 4.13 Control window (control.html)
- Pet picker grid, walk slider, always-on-top, visible toggle, break reminder
  (on/off + minutes + snooze 5 min button), stretch reminder (on/off +
  minutes), chimes, and the five P9 presence switches. Saves via
  `save_config` (350 ms debounce), re-reads config every 5 s, works in demo
  mode when the bridge is absent.

## 5. Anti-features (hard rules)

1. **No punishment.** No lost progress, no shame streaks, no "you failed"
   lines. Wilted focus logs `focusWilt` (honest record) but nothing is taken
   away; barter expiry keeps the bank; day-close says "Tomorrow's a new day".
2. **No currency.** XP is earned but never spent; the ONLY trade is
   attention barter (banked focus minutes ↔ form stages). No shop, no
   premium, no points economy.
3. **Honest records.** Every bubble, lane note, voice line, and aura is a
   deterministic function of logged data. The pet confesses honestly when
   sessions were lit and let burn out ("you've lit N candles…"). No flattery.
4. **Anti-badge-spam.** Epochs fire once per life; rituals ≤3/day; memory ≤3
   recalls/day; alerts ≤1/day; voice ≤4 lines/week; cooldowns everywhere
   (break 5 min, stretch 30 min, perch 30 min, cursor 3 min, agent error
   15 min, typing bounce 2 min).

## 6. Non-goals

- Web/cloud sync; all data stays local (`~/.opencode/pet`) — nothing leaves
  the machine.
- Multi-device identity, cross-pet shared memory (one pet, one memory —
  `activity-<petId>.jsonl`).
- Mobile/other-OS ports (Windows 10/11 only: GDI layered window, msvcrt
  locking, winsound).
- Punitive productivity enforcement (website blocking, time limits,
  parental-control style gating).
- Replacement for OpenCode's own session data; the pet READS status files, it
  does not own the tool session lifecycle.
- Custom sprite art per evolution stage (ships with programmatic aura; the
  staged sheet hook exists, art does not).

## 7. Success metrics

| Metric | Instrument |
|---|---|
| DAU/WAU: days the pet runs with sessions present | activity log `state` events per day per install |
| Focus-session completion rate (done / starts) | log `focusStart` vs `focusDone` (the pet voices it) |
| Daily-goal met-rate | `lastGoalDate` vs calendar |
| Ritual completion rate | log `ritual` vs derived count |
| Barter stage progression | `barterStage` growth over install age |
| Chronotype stability | `drift` events per month |
| UI contract health | `tests/test_spec_contract.py` + full suite green (`tests/run_all.py`) |
| Crash surface | wellbeing/focus/config corrupt-file resilience paths exercised in tests |

## 8. Open questions / UNVERIFIED

- <status-*.json writer contract>: the files are written by an external
  OpenCode server plugin NOT in this repo; fields beyond those consumed
  (`sessionID`, `state`, `title`, `toolLabel`, `message`, `updatedAt`,
  `direction`) are UNVERIFIED.
- <get_alerts API>: implemented and in the contract but no UI in app.html /
  control.html calls it today; intended consumer (companion view?) not
  verified.
