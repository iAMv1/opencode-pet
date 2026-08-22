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
- **Unlock system REMOVED by user decision** (2026-08-23): epic/cleanup branches + remote develop deleted; evolution system stays.
- Native UI verdict delivered (2026-08-23): HTML production-adequate for v0.6.x; PySide6 incremental panel migration optional in v0.7 — awaiting user greenlight.
- Long-term architecture only; documented debt OK (DEBT-OK lists exist in audit outputs).

## Asset ecosystem research (2026-08-23, web-search verified)
The post-Grok desktop-pet buzz = Codex/Petdex pack format wave:
- Petdex (crafter-station/petdex, ~3.9k stars, MIT): gallery + CLI + petdex.dev/api/manifest HTTP API. Pack = `pet.json` + `spritesheet.webp`, 8x9 grid of 192x208 cells (v2: 8x11), 9 state rows (idle/running-right/running-left/waving/jumping/failed/waiting/running/review).
- OpenPets (openpets.dev, MIT): 1177 companions gallery + submit flow. Also: X-T-E-R/OpenPet (MCP control), AgentCat, agent-pet, OpenAnima (PySide6 — native-migration reference).
- OUR ENGINE IS ALREADY COMPATIBLE: sprites.py PET_STATES = same 9-row petdex layout, 192x208 cells.
- Licensing: runtime import by users = clean; bundling specific pets in the exe requires per-pet license check.
- PROPOSED R4 FEATURE: Petdex-compatible pack loader (user folder + optional manifest fetch) within 1-2k LOC budget. Awaiting user go-ahead.

## Round 4 queue (remaining meaningful work)
1. **Petdex pack loader** — RESEARCHED, spec hardened (research/petdex-r4/SYNTHESIS.md): dimension-inference + alpha-scan frame counts + walking→running alias shim mandatory; naive parsing breaks on live packs. Ready to build on user go.
2. **Native UI**: verdict = PySide6 incremental, control.html first (OpenAnima proof case; Tauri/Electron IPC cost documented in findings). User greenlight pending.
3. **⚠ RELEASE GATE — bundled sprite licensing**: exe ships Pokemon/Doraemon/Gardevoir/Giratina fan art; galleries carry no license data; redistributor exposure > loader exposure. User must pick: replace roster with original/CC0 art vs accept risk. Gates v0.6.2+.
4. Release v0.6.2 after gate decision.
5. Parked: nothing.

## Session-end state
All work committed+pushed through `3626e16`. Working tree clean except this HANDOFF edit. Next session: read this file, pick from Round 4 queue, continue loop until queue empty AND no reviewer/specialist can identify stronger alternative.
