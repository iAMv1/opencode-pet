# HANDOFF — opencode-pet

> Canonical resume-state. Update BEFORE reporting done. Last: 2026-08-23 (gauntlet round 1).

## Repo facts
- Path: `C:\Users\ItzP\projects\opencode-pet` · Remote: `github.com/iAMv1/opencode-pet`
- main == origin/main @ `fd07ed0`. Latest release **v0.6.1**.
- Python via `py -3.12` (`python` alias broken — Store stub).
- Full gate: `py -3.12 tests/run_all.py` (~3 min) → **640 pytest + UI 78/78 + real 72/72**.

## Gauntlet round 1 (2026-08-23, commit fd07ed0) — DONE
5 read-only audit agents swept engine/store/api/web/win32/frontend/tests → 40+ findings → triaged P0-P3 → fixed through independent critical review (FIX-FIRST items resolved):
- Persistence integrity: .bak/.corrupt recovery scheme (store), atomic wellbeing/focus writes, locked focus-tag RMW w/ session-scoped ownership, activity-log lock+atomic prune, honest save bools.
- Bubble priority system `_say(pri 1/2/3)` — milestones no longer clobbered ≤0.5s by chatter.
- Echo int-hour keys (feature was dead), wilt guard real idle tracking + grace, barter offer expiry via `barterOfferSince`, backward-clock rollover guard.
- Delta persistence in config_watch/set_pet (settings toggle no longer rolls back XP/level/goal/chrono).
- web.py Content-Length hardening; single-instance guard use_last_error fix.
- 15 new regression tests in tests/test_persistence_hardening.py; 3 tests updated that masked bugs.
- LESSON: never rewrite test files via PS Set-Content (mojibake'd UTF-8 once; reverted). Use edit tool only.

## Parked / open decisions (user-owned)
- Branches parked: epic/project-completion-sprint + feature/autonomous-cleanup-sprint ("pet unlock system", +8.2k/−13.8k, predates Aug-7 main, heavy conflicts if revived). chore/comprehensive-cleanup ≈ main. origin/develop dead.
- BUG-7/8 LPC-cat sprite variety needs new sprite art (tools/sprite_forge.py pipeline).

## User directives (standing)
- **LOC budget: 1–2k lines per e2e complete feature.**
- Not fond of HTML dashboards — wants desktop-native stack eventually. Options to propose at checkpoint: PySide6/Qt (stays Python, reuses engine/store) vs C#/WinUI rewrite vs TUI (@opentui/solid dep exists in package.json). Pet window itself already native GDI. Do NOT rip out working UI mid-loop; layer it.
- Long-term architecture only, no stopgaps; grow in layers; debt OK when documented (DEBT-OK sections in audits).

## Next high-value steps (round 2 queue)
1. Batch 5 dedup (audit-verified, ~230 LOC savings): persist_config_keys helper ×11 sites (~45 ln), radial-glow helper ×5 (~75 ln), JSONL scanner helper ×4 (~50 ln), api activity-log iterator ×6 (~60 ln).
2. Frontend drift fixes: control FALLBACK_PETS missing Emberkit; app save() persists only 4 keys vs control's 7; focusMoveFor vs ritual TYPES ember mismatch; delete dead _focus-ritual.js (verify); dup wbCompare element id; companion renderers missing sig-guard.
3. Hidden-view polling waste (app.html intervals fire for hidden views).
4. os._exit(0) quit skips final flush (wellbeing ≤20s loss) — add flush before exit.
5. Multi-monitor: pet confined to primary workarea; WM_DISPLAYCHANGE unhandled → stranded pet on dock/undock (feature-sized work, respect LOC budget).
6. Cut v0.6.2 tag when next feature lands (tag triggers exe build workflow).
7. Native-stack migration proposal (user ask) — needs agency-design-pipeline skill if it produces UI.
