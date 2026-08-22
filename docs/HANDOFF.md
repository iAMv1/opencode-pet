# HANDOFF — opencode-pet

> Canonical resume-state. Update BEFORE reporting done. Last: 2026-08-23 (gauntlet round 3 complete).

## Repo facts
- Path: `C:\Users\ItzP\projects\opencode-pet` · Remote: `github.com/iAMv1/opencode-pet`
- main == origin/main @ `3626e16`. Latest release **v0.6.1**.
- Python via `py -3.12` (`python` alias broken — Store stub).
- Full gate: `py -3.12 tests/run_all.py` (~2–4 min) → **648 pytest + UI 78/78 + real 72/72**.

## Gauntlet log (all pushed)
- **R1** (`fd07ed0`): persistence integrity (.bak/.corrupt recovery, atomic writes, locked focus-tag RMW, honest save bools), bubble priority tiers, echo int-keys, wilt guard, barter expiry clock (`barterOfferSince`), delta persistence in config_watch/set_pet (no more XP rollback), web hardening, mutex use_last_error. +15 regression tests (tests/test_persistence_hardening.py).
- **R2** (`ba20689`, −237 LOC): `_pet_aura` glow ×3→1, `_log_events` scanner ×4→1, `_persist_keys` dance ×11→1, api `_iter_activity_log` ×5→1, frontend drift fixed (Emberkit fallback, ember move sync, dup wbCompare removed, sig-guards), dead _focus-ritual.js deleted, quit paths flush state before os._exit.
- **R3** (`76e613b` + `3626e16`): thread discipline — `@_locked` RLock on 13 mutators (lazy attach for bare test doubles), win32 drag routed through locked drag_start/drag_to/drag_end; app.html view-gated polling (switchView refreshes consumers); multi-monitor — `monitor_workarea_for`, per-monitor clamp in drag_end, WM_DISPLAYCHANGE→refresh_area re-clamp. +8 tests (tests/test_multimonitor.py). 640→648 pytest.
- LESSON (twice now): NEVER rewrite source via PS Set-Content/Get-Content round-trip — BOM + mojibake risk. Use Read/Edit tools only.

## Audit findings RESOLVED (do not re-report)
Data-loss chains, bubble clobber, dead echo/wilt/barter-expiry, stale-cfg rollback, false-success saves, Content-Length DoS, GetLastError race, prune-vs-append loss, multi-monitor clamp, display-change stranding, cross-thread mutation hotspots, hidden-view poll waste, frontend helper drift.

## User directives (standing)
- **LOC budget: 1–2k lines per e2e feature.**
- Wants desktop-native UI eventually (dislikes HTML dashboards). Proposal pending user decision: PySide6/Qt vs WinUI vs TUI. Pet window already native GDI. Layered migration only; never trade working product for unfinished complexity.
- Long-term architecture only; documented debt OK (DEBT-OK lists exist in audit outputs).

## Round 4 queue (remaining meaningful work)
1. **LPC-cat sprite variety** (BUG-7/8): needs new sprite art rows. Pipeline exists (tools/sprite_forge.py + check_sprites.py). Could use free image chain (pollinations batch per playbook) or hand-drawn sheet. Verify with check_sprites.py + visual render.
2. **Native-stack proposal doc**: one-pager comparing PySide6/Qt (reuse engine/store, ~2k LOC new shell) vs WinUI3 (full rewrite) vs TUI (@opentui/solid already in package.json). User picks before any build.
3. **Release v0.6.2**: tag triggers exe workflow. Bundle R1-R3 fixes. Update README proof shots if UI changed (it didn't materially).
4. **Threading completeness** (optional polish): render-loop reads still unsynchronized by design (GIL-atomic per attr) — acceptable; document as DEBT-OK rather than over-lock.
5. Parked user decisions: epic/cleanup branches ("pet unlock system" revival = big merge + test repair), origin/develop deletion.

## Session-end state
All work committed+pushed through `3626e16`. Working tree clean except this HANDOFF edit. Next session: read this file, pick from Round 4 queue, continue loop until queue empty AND no reviewer/specialist can identify stronger alternative.
