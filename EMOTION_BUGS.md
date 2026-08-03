# Emotion System Bug Report

**Scope:** desktop/main.py -- state machine (_state(), _anim_id()), DEFAULT_MAP, PET_STATES, per-pet maps
**Sprite validation:** check_sprites.py run output -- 0 errors, 1 warning (LPC cat row 3 unused)

> **Status (2026-08-02):** BUG-1, BUG-2, BUG-3 and BUG-9 are FIXED in code and
> locked in by `tests/test_state_machine.py`. BUG-6's duplicate `running`
> state was removed (only `walking` remains, row 7). BUG-4's UI-side remap
> is fixed in `desktop/app.html` (celebrating now renders as its own state).
> BUG-5 is a deliberate design trade-off (the break nudge wave is transient).
> BUG-7/BUG-8 (LPC cat visual variety) require new sprite art.

---

## 1. System Architecture Summary

### Data flow

Server (dist/server.js) writes status-<sessionID>.json with state: idle|busy|thinking|error|success|celebrating|waiting
  -> read_status() [main.py:483]: sorted by updatedAt, annotated stale=(now-updatedAt>STALE_MS)
  -> update_sessions() [main.py:881]: self.sessions = sessions
  -> _state() [main.py:729-734]:
       st = sessions[0] or None
       fresh = st and not st.stale
       if fresh: return st.get("state") or "idle"      # raw server string
       else:    return "busy" if os_active else "waiting" # synthetic fallback
  -> _anim_id() [main.py:736-751]:
       our = _state(); m = pet["map"] or DEFAULT_MAP
       if not grounded:          -> "jumping"   [HARDCODED NO pet guard]
       if attention_until>now:   -> "waving"    [guarded by any(s.id=="waving")]
       if walk mode + vx!=0:     -> L/R running [guarded by any(s.id==...)]
       if our=="busy"+sessions:  -> directional [guarded by any(s.id==...)]
       return m.get(our) or "idle"
  -> _compose() [main.py:810-827]:
       anim = next((a for a in pet_states if a["id"]==_anim_id()), pet_states[0])
       frame = _frame_cache.get((anim["id"], frame_idx)) -> blit or silently None

app.html:522 STATE_KEYS maps celebrating -> "success" BEFORE reaching _state().
_state() can return: idle, busy, thinking, error, success, waiting, or synthetic busy/waiting.

---

## 2. Bug Inventory

### BUG-1 -- CRITICAL: LPC cat jumps show idle (no jumping frames cached)
**Location:** _anim_id() lines 739-740, _compose() line 821

_anim_id() returns hardcoded "jumping" when not grounded WITHOUT checking if
the current pet has a "jumping" animation row. LPC Cat (PETS[5]) has only 4 states:
idle, running-right, running-left, waiting. No "jumping" entry.

Frame cache built only for declared states (line 664), so _frame_cache has no
key ("jumping", n) for LPC cat.

In _compose():
  anim = next((a for a in st if a["id"] == self._anim_id()), st[0])
  # _anim_id returns "jumping", not in LPC states -> falls back to st[0]=idle
  frame = self._frame_cache.get((self.anim["id"], self.frame_idx))
  # anim["id"]=="idle" -> finds frame -> pet shows idle while airborne
  # THIS IS A SILENT FAILURE: no error raised

**Effect:** Double-click to jump on LPC cat shows idle mid-air. Pet never shows a jump.
**Root cause:** _anim_id() is pet-agnostic but produces pet-specific IDs. The "jumping"
early return bypasses the any(s["id"]==...) guard used correctly elsewhere.

---

### BUG-2 -- HIGH: LPC cat walking left shows idle (no running-left frames)
**Location:** _anim_id() lines 743-744

When phys["mode"]=="walk" and phys["vx"]<0, _anim_id() immediately returns
"running-left" without checking whether current pet has a "running-left" state.
LPC cat map: {"idle":"idle","busy":"running-right",...} -- no "running-left".
Same silent fallback -> _compose() falls back to st[0]=idle.

**Effect:** LPC cat walking left looks identical to idle. Never appears to run leftward.

---

### BUG-3 -- HIGH: Session stale -> emotion state immediately and silently lost
**Location:** _state() lines 729-734

When a session becomes stale (>5 min no heartbeat), _state() does NOT return "stale".
Instead it immediately substitutes a synthetic state:
    return "busy" if self.os_active else "waiting"

The pet FORGETS what the session was actually doing. All rich emotion states --
thinking, error, success, celebrating -- collapse to either "busy" (->running)
or "waiting" (->waiting) the moment the session times out.

Concrete example:
  1. User error -> session state="error" -> pet shows "failed" animation [OK]
  2. User walks away 5+ min -> session goes stale
  3. _state() returns "waiting" (OS idle) -> pet shows "waiting" [WRONG: should still show failed]
  4. NO visual indication the session ended in an error state

The DEFAULT_MAP key "stale":"waiting" (line 175) is DEAD CODE -- _state() never
returns "stale". The actual stale fallback is hardcoded inside _state() itself.

**Effect:** Pet cannot show that a timed-out session ended in error or thinking state.
All stale sessions collapse to running or waiting regardless of prior emotion.

---

### BUG-4 -- MEDIUM: celebrating server state silently remapped to success
**Location:** app.html:522 STATE_KEYS, DEFAULT_MAP line 174

The server can emit "celebrating" as a session state. STATE_KEYS maps it:
    celebrating: "success"
By the time the state reaches _state(), "celebrating" has become "success".
The pet uses the "jumping" animation (DEFAULT_MAP: success->jumping).

The "celebrating" entry in DEFAULT_MAP (line 174: "celebrating":"waving") is
UNREACHABLE DEAD CODE -- no code path ever produces the string "celebrating"
for _state() to consume.

**Effect:** The dedicated "waving" animation (row 3) is NEVER triggered by sessions.
Server "celebrating" signal is indistinguishable from "success" to the pet.

---

### BUG-5 -- MEDIUM: attention_until waving override masks other emotions
**Location:** _anim_id() lines 741-742, update_activity() line 966

The break-nudge system (line 966) sets attention_until=now+3 to make the pet wave.
_anim_id() checks this timer BEFORE consulting _state() or DEFAULT_MAP:
    if time.time() < self.attention_until and any(s[id]=="waving"...): return "waving"

A waving pet can be in ANY underlying session state (error, busy, idle).
The wave completely hides it. No path shows a "celebrating" animation for a
server "celebrating" state (BUG-4: already remapped to success->jumping).

**Effect:** Waving-to-take-break pet may appear positive while session is in error state.

---

### BUG-6 -- MEDIUM: Semantic collision of string "running" in 3 contexts
**Locations:** PET_STATES row 7 (line 169), DEFAULT_MAP line 173, _state() stale fallback, _anim_id() output

The string "running" has three different meanings:
  Source                        | Meaning                           | Row
  ------------------------------|-----------------------------------|----
  DEFAULT_MAP key "running"       | Raw session state (not emitted)   | 7
  _state() stale fallback(active) | Session timed out, OS active      | 7
  _anim_id() output (walk mode)  | Pet physically walking on screen  | 7

Mostly harmless because _anim_id() checks physics walk mode before the map.
But: a stale busy session looks identical to a fresh running session --
indistinguishable visually. Semantic confusion makes code fragile.

---

### BUG-7 -- LOW: LPC cat waiting state is duplicate of idle
**Location:** LPC pet definition lines 216-217

  {"id": "waiting", "row": 0, "frames": 8, "durationMs": 1500}

Row 0 is already used by "idle". Both have 8 frames, same sprite row. Only
difference is durationMs (1100 vs 1500). When stale->waiting, LPC cat plays idle
at a slower tempo -- no distinct waiting pose.

**Effect:** Stale->waiting transition is invisible on LPC cat.

---

### BUG-8 -- LOW: LPC cat sprite sheet has unused row 3
**Location:** pet-lpc-cat.png (512x256 = 8 cols x 4 rows of 64x64)

The sprite sheet has 4 rows (0-3) but LPC cat states only declare rows 0,1,2.
Row 3 (pixels 192-256) is completely unreachable. Flagged by check_sprites.py.

---

### BUG-9 -- LOW: _state() redundant fallback masks null state
**Location:** _state() line 733

    return st.get("state") or "idle"

If st["state"] is None, this returns "idle" -- identical to healthy idle session.
Cannot distinguish truly idle from server sending bad data.

---

## 3. Summary Table

| ID    | Severity | Description                                          | Lines      |
|-------|----------|------------------------------------------------------|------------|
| BUG-1 | CRITICAL | LPC cat jumps show idle (no jumping guard)            | 739-740    |
| BUG-2 | HIGH     | LPC cat walking left shows idle (no running-left guard)| 743-744    |
| BUG-3 | HIGH     | Stale session emotion lost -> collapses to busy/waiting| 729-734    |
| BUG-4 | MEDIUM   | celebrating remapped to success; map key dead code     | app.html:522, main.py:174 |
| BUG-5 | MEDIUM   | attention_until waving masks actual session emotion    | 741-742,966|
| BUG-6 | MEDIUM   | running string has 3 conflicting meanings              | 169,173,734,743 |
| BUG-7 | LOW      | LPC cat waiting = idle same row, no distinct pose      | 216-217    |
| BUG-8 | LOW      | LPC cat sprite sheet row 3 unused                     | sheet asset|
| BUG-9 | LOW      | Null session state silently treated as idle            | 733        |

---

## 4. Reproducer Test Plan

Write session JSON files to ~/.opencode/pet/ and observe rendered animation:

# BUG-1: LPC cat airborne -> _anim_id returns "jumping", not in pet states
#        _compose falls back to idle -> pet shows idle mid-air
# Test: double-click LPC cat, observe animation while airborne is idle

# BUG-2: LPC cat phys vx<0 -> _anim_id returns "running-left", not in pet states
#        _compose falls back to idle -> pet shows idle while walking left
# Test: set walk factor > 0 for LPC cat, observe leftward walk shows idle

# BUG-3: session state="error" -> wait 5+ min -> observe "waiting" not "failed"
# Test: write error session with old updatedAt, observe stale->waiting not stale->failed

# BUG-4: session state="celebrating" -> observe jumping not waving
# Test: write celebrating session, observe pet jumps instead of waves

---

## 5. Root Cause Analysis

The fundamental design flaw: _anim_id() is pet-agnostic but produces pet-specific
animation IDs. The early-return hardcoded strings "jumping", "waving",
"running-left", "running-right" are resolved WITHOUT consulting pet_states(self.pet),
unlike the directional checks later in the method which correctly use
any(s["id"]==...) guards.

The stale-session problem stems from _state() conflating two concerns:
"what state is the session in?" and "what should the pet look like if unknown?".
These should be separate. _state() should preserve the last-known session emotion;
the fallback to busy/waiting should only apply when there are no sessions at all.

The DEFAULT_MAP keys "stale" and "celebrating" are dead code -- they exist in the
map but _state() never produces those strings, indicating the map was designed for
a richer _state() that no longer exists.

---

## 6. Recommended Fixes

### Fix A -- Guard all _anim_id() early returns with pet state checks

Replace the hardcoded early returns with pet-aware guards:

  if not grounded:
      if any(s["id"]=="jumping" for s in pet_states(self.pet)):
          return "jumping"
      # fall through to map lookup instead

  if attention_until>time.time() and any(s["id"]=="waving" for s in pet_states(self.pet)):
      return "waving"

  if phys["mode"]=="walk" and phys["vx"]!=0:
      if vx<0 and any(s["id"]=="running-left" for s in pet_states(self.pet)):
          return "running-left"
      if any(s["id"]=="running-right" for s in pet_states(self.pet)):
          return "running-right"

  if our=="busy" and sessions:
      d = sessions[0].get("direction")
      if d=="left"  and any(s["id"]=="running-left"  for s in pet_states(self.pet)): ...
      if d=="right" and any(s["id"]=="running-right" for s in pet_states(self.pet)): ...

### Fix B -- Preserve last-known emotion through stale boundary

Split _state() into raw emotion getter + display-state fallback:

  def _raw_state(self):
      st = self.sessions[0] if self.sessions else None
      if st and not st.get("stale"):
          return st.get("state")  # may be None
      return None

  def _state(self):
      raw = self._raw_state()
      if raw is not None: return raw
      return "busy" if self.os_active else "waiting"

Add stale emotion tracker:
  self._stale_emotion = None  # in __init__
  # Update on each session change, use in _anim_id when session is stale

### Fix C -- Remove dead keys from DEFAULT_MAP

Remove "stale" (line 175) and "celebrating" (line 174) from DEFAULT_MAP since
_state() never produces those strings. Re-add "celebrating":"waving" only if the
server is updated to emit raw "celebrating" (not remapped by STATE_KEYS).

### Fix D -- Fix LPC cat directional running (asset work)

Either add a "running-left" row to pet-lpc-cat.png (row 3) and update LPC states
list, OR change the LPC map to use a single non-directional running animation and
remove direction-dependent _anim_id() logic for LPC.

### Fix E -- Unify the "running" naming

Rename PET_STATES row 7 from "running" to "walking" (pet walking on screen,
not a session running state). Update all references. Eliminates semantic collision
with DEFAULT_MAP input "running".

---

## 7. Files Verified

| File | Role |
|------|------|
| desktop/main.py L161-176 | PET_STATES, DEFAULT_MAP definitions |
| desktop/main.py L205-220 | PETS list (5 standard + 1 LPC custom) |
| desktop/main.py L729-751 | _state() and _anim_id() state machine |
| desktop/main.py L810-827 | _compose() frame cache lookup and rendering |
| desktop/main.py L932-972 | update_activity() bubble, attention_until |
| desktop/app.html L518-522 | STATE_LABELS and STATE_KEYS |
| check_sprites.py | Sprite sheet validation (0 errors, 1 warning) |